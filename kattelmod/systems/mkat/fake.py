"""Components for a fake telescope."""

from katpoint import Target, rad2deg, deg2rad, wrap_angle, construct_azel_target

from kattelmod.component import TelstateUpdatingComponent, TargetObserverMixin
from kattelmod.session import CaptureState


class Subarray(TelstateUpdatingComponent):
    def __init__(self, config_label='unknown', band='l', product='c856M4k',
                 dump_rate=1.0, sub_nr=1):
        super(Subarray, self).__init__()
        self._initialise_attributes(locals())


class AntennaPositioner(TargetObserverMixin, TelstateUpdatingComponent):
    def __init__(self, observer='',
                 real_az_min_deg=-185, real_az_max_deg=275,
                 real_el_min_deg=15, real_el_max_deg=92,
                 max_slew_azim_dps=2.0, max_slew_elev_dps=1.0,
                 inner_threshold_deg=0.01):
        super(AntennaPositioner, self).__init__()
        self._initialise_attributes(locals())
        self.activity = 'stop'
        self.target = ''
        self.pos_actual_scan_azim = self.pos_request_scan_azim = 0.0
        self.pos_actual_scan_elev = self.pos_request_scan_elev = 90.0

    @property
    def target(self):
        return self._target
    @target.setter
    def target(self, target):
        new_target = Target(target, antenna=self._observer) if target else ''
        if new_target != self._target and self.activity in ('scan', 'track', 'slew'):
            self.activity = 'slew' if new_target else 'stop'
        self._target = new_target

    def _update(self, timestamp):
        super(AntennaPositioner, self)._update(timestamp)
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
        # print 'elapsed: %g, max_daz: %g, max_del: %g, daz: %g, del: %g, error: %g' % (elapsed_time, max_delta_az, max_delta_el, delta_az, delta_el, error)


class Environment(TelstateUpdatingComponent):
    def __init__(self):
        super(Environment, self).__init__()
        self._initialise_attributes(locals())
        self.pressure = 1020.3
        self.relative_humidity = 60.0
        self.temperature = 25.0
        self.wind_speed = 4.2
        self.wind_direction = 90.0


class CorrelatorBeamformer(TargetObserverMixin, TelstateUpdatingComponent):
    def __init__(self, product='c856M4k', n_chans=4096, n_accs=104448,
                 bls_ordering=[], bandwidth=856000000.0, sync_time=1443692800,
                 int_time=0.49978856074766354, scale_factor_timestamp=1712000000,
                 center_freq=1284000000.0, observer=''):
        super(CorrelatorBeamformer, self).__init__()
        self._initialise_attributes(locals())
        self.target = ''
        self.auto_delay_enabled = True
        self._add_dummy_methods('capture_start capture_stop')


class ScienceDataProcessor(TelstateUpdatingComponent):
    def __init__(self):
        super(ScienceDataProcessor, self).__init__()
        self._initialise_attributes(locals())
        self._add_dummy_methods('product_deconfigure capture_init capture_done')

    def product_configure(self, product, dump_rate, receptors, sub_nr):
        return CaptureState.STARTED

    def get_telstate(self):
        return ''


class Observation(TelstateUpdatingComponent):
    def __init__(self):
        super(Observation, self).__init__()
        self._initialise_attributes(locals())
        self.label = ''
        self.params = ''
        self.script_log = ''
