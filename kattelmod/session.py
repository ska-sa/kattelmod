import logging
import argparse
import asyncio

from enum import IntEnum
from katpoint import Timestamp, Catalogue

from kattelmod.clock import RealClock, WarpClock, WarpEventLoop
from kattelmod.updater import PeriodicUpdater
from kattelmod.logger import configure_logging
from kattelmod.component import Component


# Period of component updates, in seconds
JIFFY = 0.1


# Ideally use an OrderedEnum but there should be no confusion with only one enum
class CaptureState(IntEnum):
    """State of data capturing subsystem."""
    UNKNOWN = 0
    UNCONFIGURED = 10
    CONFIGURED = 20
    INITED = 30
    STARTED = 40


def flatten(obj):
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
    def __init__(self, components=()):
        # Initial logging setup just ensures that we can display early errors
        configure_logging(logging.WARN)
        self.components = components
        # Create corresponding attributes to access components
        for comp in components:
            setattr(self, comp._name, comp)
        self._clock = self._updater = None
        self.targets = False
        self.obs_params = {}
        self.logger = logging.getLogger('kat.session')
        self.dry_run = False      # Updated by connect

    def __contains__(self, key):
        """True if CaptureSession contains top-level component(s) by name or value."""
        if isinstance(key, Component):
            return key in self.components
        elif hasattr(key, '__iter__') and not isinstance(key, str):
            return all(comp in self for comp in key)
        else:
            return hasattr(self, key) and getattr(self, key) in self.components

    async def __aenter__(self):
        """Enter context."""
        if self._initial_state < CaptureState.STARTED:
            await self.capture_start()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        """Exit context."""
        if self._initial_state < CaptureState.STARTED:
            await self.capture_stop()
        await self.disconnect()
        # Don't suppress exceptions
        return False

    def time(self):
        """Current time in UTC seconds since Unix epoch."""
        return self._clock.time()

    async def sleep(self, seconds, condition=None):
        """Sleep for the requested duration in seconds."""
        # TODO: need to handle the condition
        await asyncio.sleep(seconds)

    def argparser(self, *args, **kwargs):
        parser = argparse.ArgumentParser(*args, **kwargs)
        parser.add_argument('--config', default='mkat/fake_2ant.cfg')
        parser.add_argument('--description')
        parser.add_argument('--dont-stop', action='store_true')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--log-level', default='INFO')
        parser.add_argument('--start-time')
        # Positional arguments are assumed to be targets
        if self.targets:
            parser.add_argument('targets', metavar='target', nargs='+')
        return parser

    def collect_targets(self, *args):
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

    def _fake(self):
        """Construct an equivalent fake session."""
        if hasattr(self.components, '_fake'):
            return type(self)(self.components._fake())
        else:
            return type(self)([comp._fake() for comp in self.components])

    def _configure_logging(self, log_level=None, script_log=True):
        if log_level is None:
            log_level = self.obs_params['log_level']
        script_log_cmd = None
        if script_log and 'obs' in self:
            def script_log_cmd(msg):
                self.obs.script_log = msg
        configure_logging(log_level, script_log_cmd, self._clock, self.dry_run)

    async def _start(self, args):
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

    async def _stop(self):
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

    def make_event_loop(self, args=None):
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
        clock = WarpClock(start_time) if self.dry_run else RealClock(start_time)
        return WarpEventLoop(clock, dry_run)

    async def connect(self, args=None):
        loop = asyncio.get_event_loop()
        self._clock = loop.clock
        self.dry_run = isinstance(self._clock, WarpClock)
        updatable_comps = [c for c in flatten(self.components) if c._updatable]
        self._updater = PeriodicUpdater(updatable_comps, self._clock, JIFFY) \
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

    async def disconnect(self):
        if self._initial_state < CaptureState.INITED:
            await self.capture_done()
        if not self.obs_params['dont_stop']:
            await self._stop()

    def new_compound_scan(self):
        yield self

    @property
    def label(self):
        return self.obs.label
    @label.setter  # noqa: E301
    def label(self, label):
        self.obs.label = label

    @property
    def target(self):
        return self.cbf.target if 'cbf' in self else \
            self.ants[0].target if 'ants' in self else None
    @target.setter  # noqa: E301
    def target(self, target):
        if 'ants' in self:
            self.ants.target = target
        if 'cbf' in self:
            self.cbf.target = target

    @property
    def observer(self):
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
