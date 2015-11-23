from katpoint import Antenna, Target
from katcp.resource_client import (IOLoopThreadWrapper, KATCPClientResource,
                                   ThreadSafeKATCPClientResourceWrapper,
                                   TimeoutError)

from kattelmod.telstate import endpoint_parser


# Minimum time that has to elapse before rate-limited sensor values are sent again
SENSOR_MIN_PERIOD = 0.4

def is_rate_limited(sensor_name):
    """Test whether sensor will have rate-limited updates."""
    return sensor_name.startswith('pos_')

def _sensor_transform(sensor_value):
    """Extract appropriate representation for sensors to put in telstate."""
    # Katpoint objects used to be averse to pickling but we also want to match
    # what CAM puts into telstate, which are description strings
    custom = {Antenna: lambda obj: obj.description,
              Target: lambda obj: obj.description}
    return custom.get(sensor_value.__class__, lambda obj: obj)(sensor_value)


class Component(object):
    """Basic element of telescope system that provides monitoring and control."""
    def __init__(self):
        self._name = ''
        self._immutables = []
        self._ioloop = None

    @classmethod
    def _type(cls):
        module = cls.__module__.replace('kattelmod.systems.', '')
        return "{}.{}".format(module, cls.__name__)

    def __repr__(self):
        return "<{} '{}' at {}>".format(self._type(), self._name, id(self))

    def _initialise_attributes(self, params):
        """Assign parameters in dict *params* to attributes."""
        if 'self' in params:
            del params['self']
        self._immutables = params.keys()
        for name, value in params.items():
            setattr(self, name, value)

    def _add_dummy_methods(self, names, func=None):
        for name in names.split(' '):
            setattr(self.__class__, name.strip(),
                    func if func else lambda self: None)

    def _start(self, ioloop):
        self._ioloop = ioloop

    def _stop(self):
        self._ioloop = None

    def _update(self, timestamp):
        pass


class TelstateUpdatingComponent(Component):
    """Component that will update telstate when its attributes are set."""
    def __init__(self):
        self._telstate = None
        self._elapsed_time = 0.0
        self._last_update = 0.0
        self._last_rate_limited_send = 0.0
        super(TelstateUpdatingComponent, self).__init__()

    def __setattr__(self, attr_name, value):
        object.__setattr__(self, attr_name, value)
        # Do sensor updates (either event or event-rate SENSOR_MIN_PERIOD)
        time_to_send = not is_rate_limited(attr_name) or \
                       self._last_rate_limited_send == self._last_update
        if not attr_name.startswith('_') and self._telstate and time_to_send:
            sensor_name = "{}_{}".format(self._name, attr_name)
            ts = self._ioloop.time()
            # If this is initial sensor update, move it into recent past to
            # avoid race conditions in e.g. CBF simulator that reads it
            if not self._last_update:
                ts -= 10.0
            print "telstate", ts, sensor_name, _sensor_transform(value)
            self._telstate.add(sensor_name, _sensor_transform(value),
                               ts=ts, immutable=attr_name in self._immutables)

    def _update(self, timestamp):
        self._elapsed_time = timestamp - self._last_update \
                             if self._last_update else 0.0
        self._last_update = timestamp
        if timestamp - self._last_rate_limited_send > SENSOR_MIN_PERIOD:
            self._last_rate_limited_send = timestamp

    def _start(self, ioloop):
        if self._ioloop:
            return
        super(TelstateUpdatingComponent, self)._start(ioloop)
        # Reassign values to object attributes to trigger output to telstate
        for name in dir(self):
            if not name.startswith('_') and not callable(getattr(self, name)):
                setattr(self, name, getattr(self, name))


class KATCPComponent(Component):
    """Component based around a KATCP client connected to an external service."""
    def __init__(self, endpoint):
        super(KATCPComponent, self).__init__()
        self._client = None
        self._endpoint = endpoint_parser(-1)(endpoint)
        if self._endpoint.port < 0:
            raise ValueError("Please specify port for KATCP client '{}'"
                             .format(endpoint))

    def _start(self, ioloop):
        if self._ioloop:
            return
        super(KATCPComponent, self)._start(ioloop)
        resource_spec = dict(name=self._name, controlled=True,
                             address=(self._endpoint.host, self._endpoint.port))
        async_client = KATCPClientResource(resource_spec)
        async_client.set_ioloop(ioloop)
        ioloop.add_callback(async_client.start)
        wrapped_ioloop = IOLoopThreadWrapper(ioloop)
        wrapped_ioloop.default_timeout = 1
        self._client = ThreadSafeKATCPClientResourceWrapper(async_client,
                                                            wrapped_ioloop)
        try:
            self._client.until_synced()
        except TimeoutError:
            raise TimeoutError("Timed out trying to connect '{}' to client '{}'"
                               .format(self._name, self._endpoint))

    def _stop(self):
        if not self._ioloop:
            return
        if self._client:
            self._client.stop()
        super(KATCPComponent, self)._stop()


class MultiMethod(object):
    """Call the same method on multiple similar objects."""
    def __init__(self, objects, name, description):
        self.objects = objects
        self.name = name
        self.__doc__ = description

    def __call__(self, *args, **kwargs):
        for obj in self.objects:
            method = getattr(obj, self.name, None)
            if method:
                method(*args, **kwargs)


class MultiComponent(Component):
    """Combine multiple similar components into a single component."""
    _not_shared = ('_name', '_immutables', '_ioloop', '_comps')

    def __init__(self, name, comps):
        super(MultiComponent, self).__init__()
        self._name = name
        self._comps = list(comps)
        # Create corresponding attributes to access components
        for comp in comps:
            super(MultiComponent, self).__setattr__(comp._name, comp)
        def api_methods(obj):
            return {k: getattr(obj, k) for k in dir(obj)
                    if callable(getattr(obj, k)) and not k.endswith('__')}
        # Register methods
        methods = {}
        for comp in self._comps:
            for name, method in api_methods(comp).items():
                methods[name] = methods.get(name, []) + [method]
        for name, meths in methods.items():
            # Only create a top-level method if all components below have it
            if len(meths) == len(self._comps):
                multimethod = MultiMethod(self._comps, name, meths[0].__doc__)
                super(MultiComponent, self).__setattr__(name, multimethod)

    def __setattr__(self, attr_name, value):
        if attr_name in self._not_shared:
            super(MultiComponent, self).__setattr__(attr_name, value)
        else:
            # Set attribute on underlying components but not on self
            for comp in self._comps:
                setattr(comp, attr_name, value)

    def __repr__(self):
        if len(self._comps) > 0:
            comp_types = [comp._type() for comp in self._comps]
            comp_type = comp_types[0] if len(set(comp_types)) == 1 else 'Component'
            comps = " with {} {}".format(len(self._comps), comp_type)
            comps = comps + 's' if len(self._comps) > 1 else comps
        else:
            comps = ""
        return "<MultiComponent '{}'{} at {}>".format(self._name, comps, id(self))

    def __iter__(self):
        return iter(self._comps)

    def __getitem__(self, key):
        return self._comps[key] if isinstance(key, int) else getattr(self, key)


class TargetObserverMixin(object):
    """Add Target and Observer properties to any component."""
    def __init__(self):
        # NB to call super() here - see "The Sadness of Python's super()"
        super(TargetObserverMixin, self).__init__()
        self._observer = self._target = ''

    @property
    def observer(self):
        return self._observer
    @observer.setter
    def observer(self, observer):
        self._observer = Antenna(observer) if observer else ''
        if self._target:
            self._target.antenna = self._observer

    @property
    def target(self):
        return self._target
    @target.setter
    def target(self, target):
        self._target = Target(target, antenna=self._observer) if target else ''
