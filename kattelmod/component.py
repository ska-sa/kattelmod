import time
import logging
from importlib import import_module

from katpoint import Antenna, Target
from katcp.resource_client import (IOLoopThreadWrapper, KATCPClientResource,
                                   ThreadSafeKATCPClientResourceWrapper,
                                   TimeoutError)
from katcp.ioloop_manager import IOLoopManager

from kattelmod.telstate import endpoint_parser


logger = logging.getLogger(__name__)


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


def flatten(obj):
    """http://rightfootin.blogspot.co.za/2006/09/more-on-python-flatten.html"""
    try:
        it = iter(obj)
    except TypeError:
        yield obj
    else:
        for e in it:
            for f in flatten(e):
                yield f


class Component(object):
    """Basic element of telescope system that provides monitoring and control."""
    def __init__(self):
        self._name = ''
        self._immutables = []
        self._started = False

    @classmethod
    def _type(cls):
        module = cls.__module__.replace('kattelmod.systems.', '')
        return "{}.{}".format(module, cls.__name__)

    def __repr__(self):
        return "<{} '{}' at {}>".format(self._type(), self._name, id(self))

    @property
    def _updatable(self):
        """True if component is updatable via an updater thread."""
        return hasattr(self, '_update') and callable(self._update)

    @property
    def _is_fake(self):
        """True if component is fake."""
        return self._updatable and self.__class__.__module__.endswith('.fake')

    @property
    def _sensors(self):
        return [name for name in sorted(dir(self))
                if not name.startswith('_') and
                   not callable(getattr(self, name))]

    def _initialise_attributes(self, params):
        """Assign parameters in dict *params* to attributes."""
        if 'self' in params:
            del params['self']
        self._immutables = sorted(params.keys())
        for name, value in params.iteritems():
            setattr(self, name, value)

    @classmethod
    def _add_dummy_methods(cls, names, func=None):
        for name in names.split(' '):
            setattr(cls, name.strip(), func if func else lambda self: None)

    def _start(self):
        self._started = True

    def _stop(self):
        self._started = False

    def _fake(self):
        """Construct an equivalent fake component."""
        orig_type = self._type().rsplit('.', 2)
        fake_type = '{}.fake.{}'.format(orig_type[0], orig_type[2])
        params = {attr: getattr(self, attr) for attr in self._immutables}
        fake_comp = construct_component(fake_type, self._name, params)
        for sensor_name in self._sensors:
            if sensor_name not in self._immutables:
                setattr(fake_comp, sensor_name, getattr(self, sensor_name))
        return fake_comp


class TelstateUpdatingComponent(Component):
    """Component that will update telstate when its attributes are set."""
    def __init__(self):
        self._telstate = None
        self._clock = time
        self._update_time = 0.0
        self._elapsed_time = 0.0
        self._last_update = 0.0
        self._last_rate_limited_send = 0.0
        super(TelstateUpdatingComponent, self).__init__()

    def __setattr__(self, attr_name, value):
        super(TelstateUpdatingComponent, self).__setattr__(attr_name, value)
        # Do sensor updates (either event or event-rate SENSOR_MIN_PERIOD)
        time_to_send = not is_rate_limited(attr_name) or \
                       self._last_rate_limited_send == self._last_update
        if not attr_name.startswith('_') and self._telstate and time_to_send:
            sensor_name = "{}_{}".format(self._name, attr_name)
            # Use fixed update time while within an update() call
            ts = self._update_time if self._update_time else self._clock.time()
            # If this is initial sensor update, move it into recent past to
            # avoid race conditions in e.g. CBF simulator that reads it
            if not self._last_update:
                ts -= 10.0
            logger.debug("telstate {} {} {}"
                         .format(ts, sensor_name, _sensor_transform(value)))
            self._telstate.add(sensor_name, _sensor_transform(value),
                               ts=ts, immutable=attr_name in self._immutables)

    def _update(self, timestamp):
        self._elapsed_time = timestamp - self._last_update \
                             if self._last_update else 0.0
        self._last_update = timestamp
        if timestamp - self._last_rate_limited_send > SENSOR_MIN_PERIOD:
            self._last_rate_limited_send = timestamp

    def _start(self):
        if self._started:
            return
        super(TelstateUpdatingComponent, self)._start()
        # Reassign values to object attributes to trigger output to telstate
        for name in self._sensors:
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
        # Each KATCP component will have its own IOLoop, which is not great,
        # but this is tolerable since there is currently only one instance
        # of this component (sdp.ScienceDataProcessor)
        self._ioloop_manager = IOLoopManager()
        # Ensure that the background thread will actually die on script crashes
        self._ioloop_manager.setDaemon(True)

    def _start(self):
        if self._started:
            return
        super(KATCPComponent, self)._start()
        ioloop = self._ioloop_manager.get_ioloop()
        self._ioloop_manager.start()
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
        if not self._started:
            return
        if self._client:
            self._client.stop()
        self._ioloop_manager.stop()
        self._ioloop_manager.join()
        super(KATCPComponent, self)._stop()


class MultiMethod(object):
    """Call the same method on multiple similar objects.

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
    _not_shared = ('_name', '_immutables', '_started', '_comps', '_fake')

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
            for name, method in api_methods(comp).iteritems():
                methods[name] = methods.get(name, []) + [method]
        for name, meths in methods.iteritems():
            # Only create a top-level method if all components below have it
            if len(meths) == len(self._comps) and name not in self._not_shared:
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
        """Access underlying component *key* via name."""
        comp = getattr(self, key, None)
        if comp in self._comps:
            return comp
        else:
            raise KeyError("No component '{}' in '{}'".format(key, self._name))

    def __contains__(self, key):
        """Test whether MultiComponent contains component(s) by name or value."""
        if isinstance(key, Component):
            return key in self._comps
        elif hasattr(key, '__iter__'):
            return all(comp in self for comp in key)
        else:
            return hasattr(self, key) and getattr(self, key) in self._comps

    @property
    def _sensors(self):
        sensors = []
        for comp in flatten(self._comps):
            sensors.extend('{}_{}'.format(comp._name, s) for s in comp._sensors)
        return sensors

    def _fake(self):
        """Construct an equivalent fake component by faking subcomponents."""
        fake_comps = [comp._fake() for comp in self._comps]
        return MultiComponent(self._name, fake_comps)


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


def construct_component(comp_type, comp_name=None, params=None):
    """Construct component with given type string, name and parameters."""
    comp_module, comp_class = comp_type.rsplit('.', 1)
    module_path = "kattelmod.systems." + comp_module
    try:
        NewComponent = getattr(import_module(module_path), comp_class)
    except (ImportError, AttributeError):
        raise TypeError("No component class named '{}'".format(comp_type))
    params = params if params else {}
    # Cull any unknown parameters before constructing object
    # XXX Figure out a better way to construct from another similar component
    expected_args = NewComponent.__init__.im_func.func_code.co_varnames[1:]
    params = {k: v for (k, v) in params.iteritems() if k in expected_args}
    try:
        comp = NewComponent(**params)
    except TypeError as e:
        raise TypeError('Could not construct {}: {}'
                        .format(NewComponent._type(), e))
    comp._name = comp_name if comp_name else ''
    return comp
