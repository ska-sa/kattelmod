from katcp.resource_client import (IOLoopThreadWrapper, KATCPClientResource,
                                   ThreadSafeKATCPClientResourceWrapper)
from katsdptelstate.endpoint import endpoint_parser


class Component(object):
    def __init__(self):
        self._name = ''
        self._immutables = []

    def __repr__(self):
        module = self.__class__.__module__.replace('kattelmod.systems.', '')
        comp = self.__class__.__name__
        return "<{}.{} '{}' at {}>".format(module, comp, self._name, id(self))

    def _initialise_attributes(self, params):
        """Assign parameters in dict *params* to attributes."""
        if 'self' in params:
            del params['self']
        self._immutables = params.keys()
        for name, value in params.items():
            setattr(self, name, value)


class TelstateUpdatingComponent(Component):
    def __init__(self):
        self._telstate = None
        self._elapsed_time = 0.0
        self._last_update = 0.0
        super(TelstateUpdatingComponent, self).__init__()

    def __setattr__(self, attr_name, value):
        object.__setattr__(self, attr_name, value)
        # Default strategy for sensor updates:
        # event-rate 0.4 for position sensors and standard event for the rest
        time_to_send = self._elapsed_time > 0.4 \
                       if attr_name.startswith('pos_') else True
        if not attr_name.startswith('_') and self._telstate and time_to_send:
            sensor_name = "{}_{}".format(self._name, attr_name)
            print "telstate", sensor_name, value
            # self._telstate.add(sensor_name, value,
            #                    immutable=attr_name in self._immutables)

    def _update(self, timestamp):
        self._elapsed_time = timestamp - self._last_update \
                             if self._last_update else 0.0
        self._last_update = timestamp

    def _start(self, ioloop):
        # Reassign values to object attributes to trigger output to telstate
        for attr_name in vars(self):
            if not attr_name.startswith('_'):
                setattr(self, attr_name, getattr(self, attr_name))

    def _stop(self):
        pass


class KATCPComponent(Component):
    def __init__(self, endpoint):
        super(KATCPComponent, self).__init__()
        self._client = None
        self._endpoint = endpoint_parser(-1)(endpoint)
        if self._endpoint.port < 0:
            raise ValueError("Please specify port for KATCP client '{}'"
                             .format(endpoint))

    def _start(self, ioloop):
        resource_spec = dict(name=str(self.__class__), controlled=True,
                             address=(self._endpoint.host, self._endpoint.port))
        async_client = KATCPClientResource(resource_spec)
        async_client.set_ioloop(ioloop)
        ioloop.add_callback(async_client.start)
        wrapped_ioloop = IOLoopThreadWrapper(ioloop)
        wrapped_ioloop.default_timeout = 1
        self._client = ThreadSafeKATCPClientResourceWrapper(async_client,
                                                            wrapped_ioloop)
        self._client.until_synced()

    def _stop(self):
        if self._client:
            self._client.stop()


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
    _not_shared = ('_name', '_immutables', '_started', '_comps')

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
            comp_types = ['{}.{}'.format(comp.__class__.__module__,
                                         comp.__class__.__name__)
                          for comp in self._comps]
            comp_type = comp_types[0].replace('kattelmod.systems.', '') \
                        if len(set(comp_types)) == 1 else 'Component'
            comps = " with {} {}".format(len(self._comps), comp_type)
            comps = comps + 's' if len(self._comps) > 1 else comps
        else:
            comps = ""
        return "<MultiComponent '{}'{} at {}>".format(self._name, comps, id(self))

    def __iter__(self):
        return iter(self._comps)
