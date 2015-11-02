import time
try:
    import katsdptelstate
except ImportError:
    katsdptelstate = None


class FakeTelescopeState(object):
    """Fake version of katsdptelstate.TelescopeState."""
    def __init__(self, endpoint='localhost', db=0, clock=time):
        self.db = []
        self.clock = clock
        self.sensors = set()

    def add(self, sensor_name, value, immutable=False):
        if immutable and sensor_name in self.sensors:
            raise KeyError("Attempt to overwrite immutable key.")
        self.sensors.add(sensor_name)
        self.db.append((self.clock.time(), sensor_name, value))


if katsdptelstate:
    from katsdptelstate.endpoint import endpoint_parser
    from katsdptelstate import TelescopeState

else:
    from collections import namedtuple

    Endpoint = namedtuple('Endpoint', 'host port')
    Endpoint.__str__ = lambda self: "{}:{}".format(self.host, self.port)

    def endpoint_parser(default_port):
        """Simplistic version of katsdptelstate endpoint parser."""
        def parser(text):
            host, _, port = text.partition(':')
            port = int(port) if port else default_port
            return Endpoint(host, port)
        return parser

    TelescopeState = FakeTelescopeState
