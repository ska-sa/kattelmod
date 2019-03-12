import time
import logging

try:
    import katsdptelstate
except ImportError:
    katsdptelstate = None


class FakeTelescopeState:
    """Fake version of katsdptelstate.TelescopeState."""
    def __init__(self, endpoint=None, db=0):
        # If endpoint is given, we typically have a missing dependency issue
        if endpoint:
            logger = logging.getLogger('kat.session')
            logger.warning('No katsdptelstate/redis found, using fake telstate')
        self.db = {}

    def add(self, key, value, ts=None, immutable=False):
        if immutable and key in self.db:
            raise KeyError("Attempt to overwrite immutable key.")
        ts = time.time() if ts is None else ts
        ts_values = self.db.get(key, [])
        ts_values.append((ts, value))
        self.db[key] = ts_values


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
