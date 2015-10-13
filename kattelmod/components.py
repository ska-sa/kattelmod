from functools import wraps
import inspect

from katpoint import (Antenna, Target, rad2deg, deg2rad, wrap_angle,
                      construct_azel_target)


def auto_assign_parameters(func):
    """Automatically assigns all parameters to object attributes.

    Adapted from http://stackoverflow.com/questions/1389180.

    >>> class process:
    ...     @auto_assign_parameters
    ...     def __init__(self, cmd, reachable=False, user='root'):
    ...         pass
    >>> p = process('halt', True)
    >>> p.cmd, p.reachable, p.user
    ('halt', True, 'root')

    """
    names, varargs, keywords, defaults = inspect.getargspec(func)
    # Pass through name + docstring + argument list of original function
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # Set explicit args and kwargs
        for name, arg in list(zip(names[1:], args)) + list(kwargs.items()):
            setattr(self, name, arg)
        # Set implicit kwargs with default values
        if defaults:
            for name, default in zip(reversed(names), reversed(defaults)):
                if not hasattr(self, name):
                    setattr(self, name, default)
        func(self, *args, **kwargs)
    return wrapper


class Component(object):
    def update(self, timestamp):
        pass

        

class AntennaPositioner(Component):
    @auto_assign_parameters
    def __init__(self, observer='', real_az_min_deg=-185, real_az_max_deg=275,
                 real_el_min_deg=15, real_el_max_deg=92, max_slew_azim_dps=2.0,
                 max_slew_elev_dps=1.0, inner_threshold_deg=0.01):
        self.mode = 'STOP'
#        self.req_target('')
        self.activity = 'stop'
        self.pos_actual_scan_azim = self.pos_request_scan_azim = 0.0
        self.pos_actual_scan_elev = self.pos_request_scan_elev = 90.0
        self._last_update = 0.0

    def req_target(self, target):
        self.target = target
        self._target = Target(target) if target else None
        self.lock = False
        self.scan_status = 'none'
        if not self._target and self.mode in ('POINT', 'SCAN'):
            self.req_mode('STOP')

    def req_mode(self, mode):
        self.mode = mode

    def req_scan_asym(self):
        pass

    def _aggregate_activity(self, mode, scan_status, lock):
        if mode in ('ERROR', 'STOW', 'STOP'):
            return mode.lower()
        elif mode in ('POINT', 'SCAN'):
            if scan_status == 'ready':
                return 'scan_ready'
            elif scan_status == 'during':
                return 'scan'
            elif scan_status == 'after':
                return 'scan_complete'
            elif lock:
                return 'track'
            else:
                return 'slew'
        else:
            return 'unknown'

    def update(self, timestamp):
        elapsed_time = timestamp - self._last_update if self._last_update else 0.0
        self._last_update = timestamp
        if self.mode not in ('POINT', 'SCAN', 'STOW'):
            return
        az, el = self.pos_actual_scan_azim, self.pos_actual_scan_elev
        target = construct_azel_target(deg2rad(az), deg2rad(90.0)) \
                 if self.mode == 'STOW' else self._target
        if not target:
            return
        requested_az, requested_el = target.azel(timestamp, self.ant)
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
        error = rad2deg(target.separation(dish, timestamp, self.ant))
        self.lock = error < self.lock_threshold
        # Update position sensors
        self.pos_request_scan_azim = requested_az
        self.pos_request_scan_elev = requested_el
        self.pos_actual_scan_azim = az
        self.pos_actual_scan_elev = el
#        print 'elapsed: %g, max_daz: %g, max_del: %g, daz: %g, del: %g, error: %g' % (elapsed_time, max_delta_az, max_delta_el, delta_az, delta_el, error)


class CorrelatorBeamformer(Component):
    def __init__(self, n_chans, n_accs, n_bls, bls_ordering, bandwidth,
                 sync_time, int_time, scale_factor_timestamp, ref_ant, **kwargs):
        self.dbe_mode = 'c8n856M32k'
        self.ref_ant = Antenna(ref_ant)
        self.req_target('Zenith, azel, 0, 90')
        self.auto_delay = True

    def req_target(self, target):
        self.target = target
        self._target = Target(target)
        self._target.antenna = self.ref_ant


class Environment(Component):
    def __init__(self, **kwargs):
        self.air_pressure = 1020
        self.air_relative_humidity = 60.0
        self.air_temperature = 25.0
        self.wind_speed = 4.2
        self.wind_direction = 90.0


class Digitiser(Component):
    def __init__(self, **kwargs):
        self.overflow = False


class Observation(Component):
    def __init__(self, **kwargs):
        self.label = ''
        self.params = ''
