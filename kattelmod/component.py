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
        super(TelstateUpdatingComponent, self).__init__()

    def __setattr__(self, attr_name, value):
        object.__setattr__(self, attr_name, value)
        if not attr_name.startswith('_') and self._telstate:
            sensor_name = "{}_{}".format(self._name, attr_name)
            print "telstate", sensor_name, value
            # self._telstate.add(sensor_name, value,
            #                    immutable=attr_name in self._immutables)

    def _update(self, timestamp):
        pass

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
    _not_shared = ('_name', '_immutables', '_comps')

    def __init__(self, comps):
        super(MultiComponent, self).__init__()
        self._comps = list(comps)
        def api_methods(obj):
            return {k: getattr(obj, k) for k in dir(obj)
                    if callable(getattr(obj, k)) and not k.endswith('__')}
        # Register methods
        for comp in self._comps:
            existing = api_methods(self).keys()
            for name, method in api_methods(comp).items():
                if name not in existing:
                    multimethod = MultiMethod(self._comps, name, method.__doc__)
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
            comp = self._comps[0]
            module = comp.__class__.__module__.replace('kattelmod.systems.', '')
            comp_type = comp.__class__.__name__
            comps = " with {} {}.{}".format(len(self._comps), module, comp_type)
            comps = comps + 's' if len(self._comps) > 1 else comps
        else:
            comps = ""
        return "<MultiComponent '{}'{} at {}>".format(self._name, comps, id(self))
