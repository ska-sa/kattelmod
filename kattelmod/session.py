import logging
import argparse
import asyncio
import signal
from typing import (Dict, Generator, Callable, Iterable, Coroutine,   # noqa: F401
                    Any, Optional, Union, TypeVar)

from enum import IntEnum
from katpoint import Timestamp, Catalogue, Target, Antenna

from kattelmod.clock import Clock, WarpEventLoop, get_clock
from kattelmod.updater import PeriodicUpdater
from kattelmod.logger import configure_logging
from kattelmod.component import Component, MultiComponent


_T = TypeVar('_T')


# Ideally use an OrderedEnum but there should be no confusion with only one enum
class CaptureState(IntEnum):
    """State of data capturing subsystem."""
    UNKNOWN = 0
    UNCONFIGURED = 10
    CONFIGURED = 20
    INITED = 30
    STARTED = 40


def flatten(obj: Any) -> Generator[Any, None, None]:
    """http://rightfootin.blogspot.co.za/2006/09/more-on-python-flatten.html"""
    try:
        it = iter(obj)
    except TypeError:
        yield obj
    else:
        for e in it:
            yield from flatten(e)


class CaptureSession:
    """Capturing a single capture block."""
    def __init__(self, components: Union[MultiComponent, Iterable[Component]] = ()) -> None:
        # Initial logging setup just ensures that we can display early errors
        configure_logging(logging.WARN)
        if not isinstance(components, MultiComponent):
            self.components = MultiComponent('', components)
        else:
            self.components = components
        # Create corresponding attributes to access components
        for comp in components:
            setattr(self, comp._name, comp)
        self._updater = None      # type: Optional[PeriodicUpdater]
        self.targets = False
        self.obs_params = {}      # type: Dict[str, Any]
        self.logger = logging.getLogger('kat.session')
        self.dry_run = False      # Updated by connect

    def __contains__(self, key: Union[str, Component, Iterable[Union[str, Component]]]) -> bool:
        """True if CaptureSession contains top-level component(s) by name or value."""
        if isinstance(key, Component):
            return key in self.components
        elif isinstance(key, str):
            return hasattr(self, key) and getattr(self, key) in self.components
        else:
            return all(comp in self for comp in key)

    async def __aenter__(self) -> 'CaptureSession':
        """Enter context."""
        if self._initial_state < CaptureState.STARTED:
            await self.capture_start()
        return self

    async def __aexit__(self, *args) -> None:
        """Exit context."""
        if self._initial_state < CaptureState.STARTED:
            await self.capture_stop()
        await self.disconnect()

    def time(self) -> float:
        """Current time in UTC seconds since Unix epoch."""
        return get_clock().time()

    async def sleep(self, seconds: float, condition: Callable[[], _T] = None) -> Union[bool, _T]:
        """Sleep for the requested duration in seconds.

        If condition is specified and is satisfied before the sleep interval,
        returns its value. Otherwise, return False.
        """
        if condition is None:
            await asyncio.sleep(seconds)
            return False
        else:
            future = asyncio.get_event_loop().create_future()
            assert self._updater is not None
            self._updater.add_condition(condition, future)
            try:
                result = await asyncio.wait_for(future, seconds)
                return result
            except asyncio.TimeoutError:
                return False
            finally:
                self._updater.remove_condition(condition, future)

    def argparser(self, *args: Any, **kwargs: Any) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(*args, **kwargs)
        parser.add_argument('--config', default='mkat/fake_2ant.cfg')
        parser.add_argument('--description')
        parser.add_argument('--dont-stop', action='store_true')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--log-level', default='INFO')
        parser.add_argument('--start-time')
        parser.add_argument('--clock-ratio', type=float, default=1.0)
        parser.add_argument('--update-period', type=float, default=0.1)
        # Positional arguments are assumed to be targets
        if self.targets:
            parser.add_argument('targets', metavar='target', nargs='+')
        return parser

    def collect_targets(self, *args: str) -> Catalogue:
        """Collect targets specified by description string or catalogue file."""
        from_strings = from_catalogues = num_catalogues = 0
        targets = Catalogue(antenna=self.observer)
        for arg in args:
            try:
                # First assume the string is a catalogue file name
                count_before_add = len(targets)
                try:
                    targets.add(open(arg))
                except ValueError:
                    self.logger.warning("Catalogue %r contains bad targets", arg)
                from_catalogues += len(targets) - count_before_add
                num_catalogues += 1
            except IOError:
                # If file failed to load, assume it is target description string
                try:
                    targets.add(arg)
                    from_strings += 1
                except ValueError as err:
                    self.logger.warning("Invalid target %r, skipping it [%s]",
                                        arg, err)
        if len(targets) == 0:
            raise ValueError("No known targets found in argument list")
        self.logger.info("Found %d target(s): %d from %d catalogue(s) and "
                         "%d as target string(s)", len(targets),
                         from_catalogues, num_catalogues, from_strings)
        return targets

    def _fake(self) -> 'CaptureSession':
        """Construct an equivalent fake session."""
        return type(self)(self.components._fake())

    def _configure_logging(self, log_level: Union[int, str] = None, script_log: bool = True) -> None:
        if log_level is None:
            log_level = self.obs_params['log_level']
        script_log_cmd = None
        if script_log and 'obs' in self:
            def script_log_cmd(msg):
                self.obs.script_log = msg
        configure_logging(log_level, script_log_cmd, get_clock(), self.dry_run)

    async def _start(self, args: argparse.Namespace) -> None:
        # Do product_configure first to get telstate
        self._initial_state = await self.product_configure(args)
        # Now start components to send attributes to telstate (once-off),
        # but delay starting the obs component until capture_init
        for comp in self.components:
            if comp._name != 'obs':
                await comp._start()
        # After initial telstate updates it is OK to start periodic updates
        if self._updater:
            self._updater.start()

    async def _stop(self) -> None:
        # Stop updates first as telstate will disappear in product_deconfigure
        if self._updater:
            self._updater.stop()
            await self._updater.join()
        # Now stop script log handler for same reason
        self._configure_logging(script_log=False)
        if self._initial_state < CaptureState.CONFIGURED:
            await self.product_deconfigure()
        # Stop components (including SDP) after all commands are done
        await self.components._stop()

    def make_event_loop(self, args: argparse.Namespace = None) -> WarpEventLoop:
        # Get parameters from command line by default for a quick session init
        if args is None:
            args = self.argparser().parse_args()
        all_fake = all([comp._is_fake for comp in flatten(self.components)])
        # Set up clock once start_time is known
        if args.dry_run and not all_fake:
            self.logger.warning('Could not enable dry-running as session '
                                'contains non-fake components')
        dry_run = args.dry_run and all_fake
        start_time = Timestamp(args.start_time).secs if args.start_time else None
        clock = Clock(0.0 if dry_run else args.clock_ratio, start_time)
        return WarpEventLoop(clock, dry_run)

    async def connect(self, args: argparse.Namespace = None) -> 'CaptureSession':
        self.dry_run = get_clock().rate == 0.0
        updatable_comps = [c for c in flatten(self.components) if c._updatable]
        self._updater = PeriodicUpdater(updatable_comps, args.update_period) \
            if updatable_comps else None
        # Set up logging once log_level is known and clock is available
        self._configure_logging(args.log_level)
        await self._start(args)
        self.obs_params.update(vars(args))
        if self._initial_state < CaptureState.INITED:
            await self.capture_init()
        if self.targets:
            self.targets = self.collect_targets(*args.targets)
        return self

    async def disconnect(self) -> None:
        if self._initial_state < CaptureState.INITED:
            await self.capture_done()
        if not self.obs_params['dont_stop']:
            await self._stop()

    def run(self, args: argparse.Namespace,
            body: Callable[['CaptureSession', argparse.Namespace], Coroutine[Any, Any, _T]]) -> _T:
        """Convenience function to handle setup.

        It creates and starts the event loop, connects and enters the
        session, then runs the `body` asynchronously. This replaces the
        event loop of the thread, so should generally only be run from
        a top-level script.
        """
        async def wrapper(body: Callable[['CaptureSession', argparse.Namespace],
                                         Coroutine[Any, Any, _T]]) -> _T:
            async with await self.connect(args):
                return await body(self, args)

        loop = self.make_event_loop(args)
        try:
            asyncio.set_event_loop(loop)
            task = loop.create_task(wrapper(body))
            loop.add_signal_handler(signal.SIGINT, task.cancel)
            return loop.run_until_complete(task)
        finally:
            loop.close()

    def new_compound_scan(self) -> Generator['CaptureSession', None, None]:
        yield self

    @property
    def label(self) -> str:
        return self.obs.label
    @label.setter  # noqa: E301
    def label(self, label: str) -> None:
        self.obs.label = label

    @property
    def target(self) -> Union[str, Target]:
        return self.cbf.target if 'cbf' in self else \
            self.ants[0].target if 'ants' in self else None
    @target.setter  # noqa: E301
    def target(self, target: Union[str, Target]) -> None:
        if 'ants' in self:
            self.ants.target = target
        if 'cbf' in self:
            self.cbf.target = target

    @property
    def observer(self) -> Union[str, Antenna]:
        return self.cbf.observer if 'cbf' in self else \
            self.ants[0].observer if 'ants' in self else None

    async def track(self, target, duration, announce=True):
        self.target = target
        if announce:
            self.logger.info("Initiating {:g}-second track on target '{}'"
                             .format(duration, self.target.name))
        if 'ants' in self:
            self.ants.activity = self.obs.activity = 'slew'
            self.logger.info('slewing to target')
            # Wait until we are on target
            cond = lambda: set(ant.activity for ant in self.ants) == set(['track'])  # noqa: E731
            await self.sleep(200, cond)
            self.logger.info('target reached')
        # Stay on target for desired time
        self.obs.activity = 'track'
        self.logger.info('tracking target')
        await self.sleep(duration)
        self.logger.info('target tracked for {:g} seconds'.format(duration))
        return True

    async def product_configure(self, args: argparse.Namespace) -> CaptureState:
        raise NotImplementedError          # pragma: nocover

    async def capture_init(self) -> None:
        raise NotImplementedError          # pragma: nocover

    async def capture_start(self) -> None:
        raise NotImplementedError          # pragma: nocover

    async def capture_stop(self) -> None:
        raise NotImplementedError          # pragma: nocover

    async def capture_done(self) -> None:
        raise NotImplementedError          # pragma: nocover

    async def product_deconfigure(self) -> None:
        raise NotImplementedError          # pragma: nocover


"""
    time
    sleep

    receptors - m062, m063, ...
    cbf
    sdp
    enviro
    obs -> label / script_log

    target

req:
    configure
#    fire_noise_diode

    capture_init
    capture_start
    capture_stop
    capture_done

sensor:
    centre_freq
    band
    dump_rate
    product

receptors:
    on_target
    load_scan
    track
    scan
"""
