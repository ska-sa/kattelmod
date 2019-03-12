import time
from collections import namedtuple

from katpoint import is_iterable
from katcp import Sensor
from katcp.sampling import SampleStrategy
from katcp.resource import KATCPSensor, escape_name, normalize_strategy_parameters


class SensorUpdate(namedtuple('SensorUpdate', 'update_seconds value_seconds '
                                              'status value')):
    """Sensor update record.

    Attributes
    ----------
    update_seconds : float
        Timestamp when sensor update has been received by observer
    value_seconds : float
        Timestamp at which the sensor value was determined
    status : string
        Sensor status
    value : object
        Sensor value with native sensor type

    """

class FakeSensor(KATCPSensor):
    """Fake sensor."""
    def __init__(self, name, sensor_type, description, units='', params=None, clock=time):
        super().__init__()
        self.name = name
        sensor_type = Sensor.parse_type(sensor_type)
        params = str(params).split(' ') if params else None
        self._sensor = Sensor(sensor_type, name, description, units, params)
        self.__doc__ = self.description = description
        self._clock = clock
        self._last_update = SensorUpdate(0.0, 0.0, 'unknown', None)
        self._strategy = None
        self._next_period = None
        self.set_strategy('none')

    @property
    def value(self):
        return self._last_update.value

    @property
    def status(self):
        return self._last_update.status

    def get_value(self):
        # XXX Check whether this also triggers a sensor update a la strategy
        return self._sensor.value()

    def _set_value(self, value, status=Sensor.NOMINAL):
        self._sensor.set_value(value, status, self._clock.time())

    def _update_value(self, timestamp, status_str, value_str):
        update_seconds = self._clock.time()
        value = self._sensor.parse_value(value_str)
        self._last_update = SensorUpdate(update_seconds, timestamp,
                                         status_str, value)
        for listener in set(self._listeners):
            listener(update_seconds, timestamp, status_str, value_str)

    def set_strategy(self, strategy, params=None):
        """Set sensor strategy."""
        def inform_callback(sensor, reading):
            """Inform callback for sensor strategy."""
            timestamp_str, status_str, value_str = sensor.format_reading(reading)
            self._update_value(reading.timestamp, status_str, value_str)
            print(sensor.name, timestamp_str, status_str, value_str)

        if self._strategy:
            self._strategy.detach()
        params = normalize_strategy_parameters(params)
        self._strategy = SampleStrategy.get_strategy(strategy, inform_callback,
                                                     self._sensor, *params)
        self._strategy.attach()
        self._next_period = self._strategy.periodic(self._clock.time())

    def update(self, timestamp):
        while self._next_period and timestamp >= self._next_period:
            self._next_period = self._strategy.periodic(self._next_period)
