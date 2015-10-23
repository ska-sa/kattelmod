from katcp.resource_client import (IOLoopThreadWrapper, KATCPClientResource,
                                   ThreadSafeKATCPClientResourceWrapper)
from katsdptelstate.endpoint import endpoint_parser


class Component(object):
    def __init__(self):
        self.name = ''
        self._immutables = []

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
            sensor_name = "{}_{}".format(self.name, attr_name)
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
