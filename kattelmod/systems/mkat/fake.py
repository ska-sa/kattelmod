"""Components for a fake telescope."""

from typing import List, Tuple, Dict, Any, Union, Optional

from katpoint import Antenna, Target, rad2deg, deg2rad, wrap_angle, construct_azel_target

from kattelmod.component import TelstateUpdatingComponent, TargetObserverMixin
from kattelmod.session import CaptureState


class Subarray(TelstateUpdatingComponent):
    def __init__(self, config_label: str = 'unknown', band: str = 'l', product: str = 'c856M4k',
                 dump_rate: float = 1.0, sub_nr: int = 1, pool_resources: str = '') -> None:
        super().__init__()
        self._initialise_attributes(locals())


class AntennaPositioner(TargetObserverMixin, TelstateUpdatingComponent):
    def __init__(self, observer: str = '',
                 real_az_min_deg: float = -185.0, real_az_max_deg: float = 275.0,
                 real_el_min_deg: float = 15.0, real_el_max_deg: float = 92.0,
                 max_slew_azim_dps: float = 2.0, max_slew_elev_dps: float = 1.0,
                 inner_threshold_deg: float = 0.01) -> None:
        super().__init__()
        self._initialise_attributes(locals())
        self.activity = 'stop'
        self.target = ''
        self.pos_actual_scan_azim = self.pos_request_scan_azim = 0.0
        self.pos_actual_scan_elev = self.pos_request_scan_elev = 90.0

    @property
    def target(self) -> Union[str, Target]:
        return self._target
    @target.setter  # noqa: E301
    def target(self, target: Union[str, Target]) -> None:
        new_target = Target(target, antenna=self._observer) if target else ''
        if new_target != self._target and self.activity in ('scan', 'track', 'slew'):
            self.activity = 'slew' if new_target else 'stop'
        self._target = new_target

    def _update(self, timestamp: float) -> None:
        super()._update(timestamp)
        elapsed_time = self._elapsed_time
        if self.activity in ('error', 'stop'):
            return
        az, el = self.pos_actual_scan_azim, self.pos_actual_scan_elev
        target = construct_azel_target(deg2rad(az), deg2rad(90.0)) \
            if self.activity == 'stow' else self.target
        if not target:
            return
        requested_az, requested_el = target.azel(timestamp, self.observer)
        requested_az = rad2deg(wrap_angle(requested_az))
        requested_el = rad2deg(requested_el)
        delta_az = wrap_angle(requested_az - az, period=360.)
        delta_el = requested_el - el
        # Truncate velocities to slew rate limits and update position
        max_delta_az = self.max_slew_azim_dps * elapsed_time
        max_delta_el = self.max_slew_elev_dps * elapsed_time
        az += min(max(delta_az, -max_delta_az), max_delta_az)
        el += min(max(delta_el, -max_delta_el), max_delta_el)
        # Truncate coordinates to antenna limits
        az = min(max(az, self.real_az_min_deg), self.real_az_max_deg)
        el = min(max(el, self.real_el_min_deg), self.real_el_max_deg)
        # Check angular separation to determine lock
        dish = construct_azel_target(deg2rad(az), deg2rad(el))
        error = rad2deg(target.separation(dish, timestamp, self.observer))
        lock = error < self.inner_threshold_deg
        if lock and self.activity == 'slew':
            self.activity = 'track'
        elif not lock and self.activity == 'track':
            self.activity = 'slew'
        # Update position sensors
        self.pos_request_scan_azim = requested_az
        self.pos_request_scan_elev = requested_el
        self.pos_actual_scan_azim = az
        self.pos_actual_scan_elev = el
        # print 'elapsed: %g, max_daz: %g, max_del: %g, daz: %g, del: %g, error: %g' % \
        #       (elapsed_time, max_delta_az, max_delta_el, delta_az, delta_el, error)


class Environment(TelstateUpdatingComponent):
    def __init__(self) -> None:
        super().__init__()
        self._initialise_attributes(locals())
        self.pressure = 1020.3
        self.relative_humidity = 60.0
        self.temperature = 25.0
        self.wind_speed = 4.2
        self.wind_direction = 90.0


class CorrelatorBeamformer(TargetObserverMixin, TelstateUpdatingComponent):
    def __init__(self, product: str = 'c856M4k', n_chans: int = 4096, n_accs: int = 104448,
                 bls_ordering: List[Tuple[str, str]] = [], bandwidth: float = 856000000.0,
                 sync_time: float = 1443692800.0,
                 int_time: float = 0.49978856074766354,
                 scale_factor_timestamp: float = 1712000000,
                 center_freq: float = 1284000000.0, observer: str = ''):
        super().__init__()
        self._initialise_attributes(locals())
        self.target = ''
        self.auto_delay_enabled = True
        self._add_dummy_methods('capture_start capture_stop product_deconfigure')

    async def product_configure(self, endpoint: str) -> None:
        pass


class ScienceDataProcessor(TelstateUpdatingComponent):
    def __init__(self) -> None:
        super().__init__()
        self._initialise_attributes(locals())
        self._add_dummy_methods('product_deconfigure capture_init capture_done')

    async def product_configure(self, sub: Subarray, receptors: List[Antenna],
                                start_time: Optional[float] = None) -> CaptureState:
        return CaptureState.STARTED

    async def get_telstate(self) -> str:
        return ''


class Observation(TelstateUpdatingComponent):
    def __init__(self, params: Dict[str, Any] = {}):
        super().__init__()
        self._initialise_attributes(locals())
        self.label = ''
        self.script_log = ''
        self.activity = 'idle'
