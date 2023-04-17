from collections import deque
import logging
from importlib import import_module
import inspect
import asyncio
from typing import (List, Dict, Mapping, MutableMapping, Sequence, Iterable, Iterator,
                    Awaitable, Callable, Optional, Any, Union)

import aiokatcp
from katpoint import Antenna, Target

from katsdptelstate.endpoint import endpoint_parser

from .clock import get_clock, real_timeout


logger = logging.getLogger(__name__)


# Minimum time that has to elapse before rate-limited sensor values are sent again
SENSOR_MIN_PERIOD = 0.4


class ComponentNotReadyError(RuntimeError):
    """Component not ready to perform requested action."""


def is_rate_limited(sensor_name: str) -> bool:
    """Test whether sensor will have rate-limited updates."""
    return sensor_name.startswith('pos_')


def _sensor_transform(sensor_value: Any) -> Any:
    """Extract appropriate representation for sensors to put in telstate."""
    # Katpoint objects used to be averse to pickling but we also want to match
    # what CAM puts into telstate, which are description strings
    custom = {Antenna: lambda obj: obj.description,
              Target: lambda obj: obj.description}
    return custom.get(sensor_value.__class__, lambda obj: obj)(sensor_value)


class Component:
    """Basic element of telescope system that provides monitoring and control."""
    def __init__(self) -> None:
        self._name = ''
        self._immutables = []    # type: List[str]
        self._started = False

    @classmethod
    def _type(cls) -> str:
        module = cls.__module__.replace('kattelmod.systems.', '')
        return f"{module}.{cls.__name__}"

    def __repr__(self) -> str:
        return f"<{self._type()} '{self._name}' at {id(self)}>"

    @property
    def _updatable(self) -> bool:
        """True if component is updatable via an updater thread."""
        return callable(getattr(self, '_update', None))

    @property
    def _is_fake(self) -> bool:
        """True if component is fake."""
        return self._updatable and self.__class__.__module__.endswith('.fake')

    @property
    def _sensors(self) -> List[str]:
        return [name for name in sorted(dir(self))
                if not name.startswith('_') and not callable(getattr(self, name))]

    def _initialise_attributes(self, params: MutableMapping[str, Any]) -> None:
        """Assign parameters in dict *params* to attributes."""
        if 'self' in params:
            del params['self']
        self._immutables = sorted(params.keys())
        for name, value in params.items():
            setattr(self, name, value)

    @classmethod
    def _add_dummy_methods(cls, names: str, func: Callable = None) -> None:
        async def dummy_coro(self):
            pass

        for name in names.split(' '):
            setattr(cls, name.strip(), func if func else dummy_coro)

    async def _start(self) -> None:
        self._started = True

    async def _stop(self) -> None:
        self._started = False

    def _fake(self) -> 'Component':
        """Construct an equivalent fake component."""
        orig_type = self._type().rsplit('.', 2)
        fake_type = f'{orig_type[0]}.fake.{orig_type[2]}'
        params = {attr: getattr(self, attr) for attr in self._immutables}
        fake_comp = construct_component(fake_type, self._name, params)
        for sensor_name in self._sensors:
            if sensor_name not in self._immutables:
                setattr(fake_comp, sensor_name, getattr(self, sensor_name))
        return fake_comp


class TelstateUpdatingComponent(Component):
    """Component that will update telstate when its attributes are set.

    The updates to telstate are scheduled as asyncio tasks. Use
    :meth:`_flush` to ensure that they have been successfully sent to
    telstate.
    """

    def __init__(self) -> None:
        self._telstate = None
        self._update_queue = deque()
        self._update_time = 0.0
        self._elapsed_time = 0.0
        self._last_update = 0.0
        self._last_rate_limited_send = 0.0
        super().__init__()

    def __setattr__(self, attr_name: str, value: Any) -> None:
        super().__setattr__(attr_name, value)
        # Do sensor updates (either event or event-rate SENSOR_MIN_PERIOD)
        time_to_send = not is_rate_limited(attr_name) or \
            self._last_rate_limited_send == self._last_update
        if not attr_name.startswith('_') and self._telstate and time_to_send:
            sensor_name = f"{self._name}_{attr_name}"
            # Use fixed update time while within an update() call
            ts = self._update_time if self._update_time else get_clock().time()
            # If this is initial sensor update, move it into recent past to
            # avoid race conditions in e.g. CBF simulator that reads it
            if not self._last_update:
                ts -= 300.0
            logger.debug("telstate {} {} {}"
                         .format(ts, sensor_name, _sensor_transform(value)))
            update_task = asyncio.get_event_loop().create_task(
                self._telstate.add(sensor_name, _sensor_transform(value),
                                   ts=ts, immutable=attr_name in self._immutables)
            )
            self._update_queue.append(update_task)

    def _update(self, timestamp: float) -> None:
        self._elapsed_time = timestamp - self._last_update \
            if self._last_update else 0.0
        self._last_update = timestamp
        if timestamp - self._last_rate_limited_send > SENSOR_MIN_PERIOD:
            self._last_rate_limited_send = timestamp

    async def _flush(self) -> None:
        """Wait for asynchronous telstate updates to complete."""
        while self._update_queue:
            await self._update_queue[0]
            self._update_queue.popleft()

    async def _start(self) -> None:
        if self._started:
            return
        await super()._start()
        # Reassign values to object attributes to trigger output to telstate
        for name in self._sensors:
            setattr(self, name, getattr(self, name))
        await self._flush()


class KATCPComponent(Component):
    """Component based around a KATCP client connected to an external service."""
    def __init__(self, endpoint: str) -> None:
        super().__init__()
        self._client = None    # type: Optional[aiokatcp.Client]
        self._endpoint = endpoint_parser(-1)(endpoint)
        if self._endpoint.port < 0:
            raise ValueError("Please specify port for KATCP client '{}'"
                             .format(endpoint))

    async def _start(self) -> None:
        if self._started:
            return
        await super()._start()
        try:
            async with real_timeout(5):
                self._client = await aiokatcp.Client.connect(self._endpoint.host, self._endpoint.port)
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError("Timed out trying to connect '{}' to client '{}'"
                                       .format(self._name, self._endpoint)) from None

    async def _stop(self) -> None:
        if not self._started:
            return
        if self._client:
            self._client.close()
            await self._client.wait_closed()
        await super()._stop()


class MultiMethod:
    """Call the same method on multiple similar objects. If any of them
    returns an awaitable, return an awaitable that gathers the
    results.

    Parameters
    ----------
    objects : sequence of objects
        Similar objects
    name : string
        Name of method to call on objects
    description : string
        Docstring of method, added to :class:`MultiMethod` object

    Notes
    -----
    If any of the objects does not have the method, skip them quietly.
    On the other hand, the :class:`MultiComponent` object ensures that
    all objects do have the method before it constructs this object.

    """
    def __init__(self, objects: Sequence[object], name: str, description: str) -> None:
        self.objects = objects
        self.name = name
        self.__doc__ = description

    def __call__(self, *args: Any, **kwargs: Any) -> Optional[Awaitable]:
        awaitables = []      # type: List[Awaitable]
        for obj in self.objects:
            method = getattr(obj, self.name, None)
            if method:
                result = method(*args, **kwargs)
                if inspect.isawaitable(result):
                    awaitables.append(result)
        if awaitables:
            return asyncio.gather(*awaitables)
        else:
            return None


class MultiComponent(Component):
    """Combine multiple similar components into a single component."""
    _not_shared = ('_name', '_immutables', '_started', '_comps', '_fake')

    def __init__(self, name: str, comps: Iterable[Component]) -> None:
        super().__init__()
        self._name = name
        self._comps = list(comps)
        # Create corresponding attributes to access components
        for comp in comps:
            super().__setattr__(comp._name, comp)

        def api_methods(obj: object) -> Dict[str, Any]:
            return {k: getattr(obj, k) for k in dir(obj)
                    if callable(getattr(obj, k)) and not k.endswith('__')}
        # Register methods
        methods = {}      # type: Dict[str, Any]
        for comp in self._comps:
            for name, method in api_methods(comp).items():
                methods[name] = methods.get(name, []) + [method]
        for name, meths in methods.items():
            # Only create a top-level method if all components below have it
            if len(meths) == len(self._comps) and name not in self._not_shared:
                multimethod = MultiMethod(self._comps, name, meths[0].__doc__)
                super().__setattr__(name, multimethod)

    def __setattr__(self, attr_name: str, value: Any) -> None:
        if attr_name in self._not_shared:
            super().__setattr__(attr_name, value)
        else:
            # Set attribute on underlying components but not on self
            for comp in self._comps:
                setattr(comp, attr_name, value)

    def __repr__(self) -> str:
        if len(self._comps) > 0:
            comp_types = [comp._type() for comp in self._comps]
            comp_type = comp_types[0] if len(set(comp_types)) == 1 else 'Component'
            comps = f" with {len(self._comps)} {comp_type}"
            comps = comps + 's' if len(self._comps) > 1 else comps
        else:
            comps = ""
        return f"<MultiComponent '{self._name}'{comps} at {id(self)}>"

    def __iter__(self) -> Iterator[Component]:
        return iter(self._comps)

    def __getitem__(self, key: str) -> Component:
        """Access underlying component *key* via name."""
        comp = getattr(self, key, None)
        if comp in self._comps:
            return comp
        else:
            raise KeyError(f"No component '{key}' in '{self._name}'")

    def __contains__(self, key: Union[str, Component, Iterable[Union[str, Component]]]) -> bool:
        """Test whether MultiComponent contains component(s) by name or value."""
        if isinstance(key, Component):
            return key in self._comps
        elif isinstance(key, str):
            return hasattr(self, key) and getattr(self, key) in self._comps
        else:
            return all(comp in self for comp in key)

    @property
    def _sensors(self) -> List[str]:
        return []

    def _fake(self) -> 'MultiComponent':
        """Construct an equivalent fake component by faking subcomponents."""
        fake_comps = [comp._fake() for comp in self._comps]
        return MultiComponent(self._name, fake_comps)


class TargetObserverMixin:
    """Add Target and Observer properties to any component."""
    def __init__(self) -> None:
        # NB to call super() here - see "The Sadness of Python's super()"
        super().__init__()
        self._observer = self._target = ''

    @property
    def observer(self) -> Union[str, Antenna]:
        return self._observer
    @observer.setter  # noqa: E301
    def observer(self, observer: Union[str, Antenna]) -> None:
        self._observer = Antenna(observer) if observer else ''
        if self._target:
            self._target.antenna = self._observer

    @property
    def target(self) -> Union[str, Target]:
        return self._target
    @target.setter  # noqa: E301
    def target(self, target: Union[str, Target]) -> None:
        self._target = Target(target, antenna=self._observer) if target else ''


def construct_component(comp_type: str, comp_name: str = None, params: Mapping[str, Any] = None) -> Component:
    """Construct component with given type string, name and parameters."""
    comp_module, comp_class = comp_type.rsplit('.', 1)
    module_path = "kattelmod.systems." + comp_module
    try:
        NewComponent = getattr(import_module(module_path), comp_class)
    except (ImportError, AttributeError):
        raise TypeError(f"No component class named '{comp_type}'")
    params = params if params else {}
    # Cull any unknown parameters before constructing object
    # XXX Figure out a better way to construct from another similar component
    expected_args = NewComponent.__init__.__code__.co_varnames[1:]
    params = {k: v for (k, v) in params.items() if k in expected_args}
    try:
        comp = NewComponent(**params)
    except TypeError as e:
        raise TypeError('Could not construct {}: {}'
                        .format(NewComponent._type(), e))
    comp._name = comp_name if comp_name else ''
    return comp
