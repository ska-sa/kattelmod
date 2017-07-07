import inspect
import time

from collections import namedtuple

from katpoint import is_iterable
from katcp import Sensor
from katcp.client import AsyncClient
from katcp.sampling import SampleStrategy
from katcp.resource import KATCPSensorsManager


# class FakeSensor(KATCPSensor):
#     """Fake sensor."""
#     def __init__(self, name, sensor_type, description, units='', params=None, clock=time):
#         super(FakeSensor, self).__init__()
#         self.name = name
#         sensor_type = Sensor.parse_type(sensor_type)
#         params = str(params).split(' ') if params else None
#         self._sensor = Sensor(sensor_type, name, description, units, params)
#         self.__doc__ = self.description = description
#         self._clock = clock
#         self._last_update = SensorUpdate(0.0, 0.0, 'unknown', None)
#         self._strategy = None
#         self.set_strategy('none')


class FakeSensorsManager(KATCPSensorsManager):
    def __init__(self):
        self.strategies = {}
        self.sensors = {}

    def add_sensor(self, sensor_description):
        sensor = resource.KATCPSensor(sensor_description, self)
        sensor_name = sensor_description['name']
        self.sensors[sensor_name] = sens

    def get_sampling_strategy(self, sensor_name):
        """Get the current sampling strategy for the named sensor

        Parameters
        ----------

        sensor_name : str
            Name of the sensor

        Returns
        -------

        strategy : tuple of str
            contains (<strat_name>, [<strat_parm1>, ...]) where the strategy names and
            parameters are as defined by the KATCP spec
        """
        cached = self._strategy_cache.get(sensor_name)
        if not cached:
            return resource.normalize_strategy_parameters('none')
        else:
            return cached


class FakeAsyncClient(AsyncClient):
    pass


def sensor_args_to_kwargs(sensor_args):
    arg_names = inspect.getargspec(katcp.core.Sensor.__init__).args
    return {k: v for k, v in zip(arg_names, sensor_args)}
