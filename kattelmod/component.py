class Component(object):
    _registry = {}

    @property
    def name(self):
        return Component._registry.get(self, '')


class TelstateUpdatingComponent(Component):
    def __init__(self):
        self._telstate = None

    def __setattr__(self, attr_name, value):
        object.__setattr__(self, attr_name, value)
        if not attr_name.startswith('_') and self._telstate:
            sensor_name = "{}_{}".format(self.name, attr_name)
            print "telstate", sensor_name, value
#            self._telstate.add(sensor_name, value)

    def initialise_attributes(self, params):
        """Assign parameters in dict *params* to attributes."""
        # Also call base initialiser while we are at it
        super(self.__class__, self).__init__()
        if 'self' in params:
            del params['self']
        for name, value in params.items():
            setattr(self, name, value)

    def update(self, timestamp):
        pass
