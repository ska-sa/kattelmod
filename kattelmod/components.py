from katpoint import (Antenna, Target, rad2deg, deg2rad, wrap_angle,
                      construct_azel_target)


class Component(object):
    _registry = {}

    def __init__(self):
        self._aggregates = {}
        self._telstate = None

    def __setattr__(self, attr_name, value):
        object.__setattr__(self, attr_name, value)
        if not attr_name.startswith('_') and self._telstate:
            sensor_name = "{}_{}".format(self.name, attr_name)
            print "telstate", sensor_name, value
#            self._telstate.add(sensor_name, value)

    def update(self, timestamp):
        pass

    @property
    def name(self):
        return Component._registry.get(self, '')


def initialise_attributes(obj, params):
    """Assign parameters in dict *params* to attributes on object *obj*."""
    # Also call base initialiser while we are at it
    super(obj.__class__, obj).__init__()
    if 'self' in params:
        del params['self']
    for name, value in params.items():
        setattr(obj, name, value)


class AntennaPositioner(Component):
    def __init__(self, observer,
                 real_az_min_deg=-185, real_az_max_deg=275,
                 real_el_min_deg=15, real_el_max_deg=92,
                 max_slew_azim_dps=2.0, max_slew_elev_dps=1.0,
                 inner_threshold_deg=0.01):
        # Simplistically assign all parameters to corresponding attributes
        initialise_attributes(self, locals())
        self.activity = 'stop'
        self.target = ''
        self.pos_actual_scan_azim = self.pos_request_scan_azim = 0.0
        self.pos_actual_scan_elev = self.pos_request_scan_elev = 90.0
        self._last_update = 0.0

    @property
    def observer(self):
        return self._observer
    @observer.setter
    def observer(self, observer):
        self._observer = Antenna(observer)

    @property
    def target(self):
        return self._target
    @target.setter
    def target(self, target):
        self._target = Target(target) if target else None
        if self.activity in ('scan', 'track', 'slew'):
            self.activity = 'slew' if self._target else 'stop'

    def update(self, timestamp):
        elapsed_time = timestamp - self._last_update if self._last_update else 0.0
        self._last_update = timestamp
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
        print 'elapsed: %g, max_daz: %g, max_del: %g, daz: %g, del: %g, error: %g' % (elapsed_time, max_delta_az, max_delta_el, delta_az, delta_el, error)


class CorrelatorBeamformer(Component):
    def __init__(self, n_chans, n_accs, n_bls, bls_ordering, bandwidth,
                 sync_time, int_time, scale_factor_timestamp,
                 observer='ref, -30:42:47.412, 21:26:38.004, 1035'):
        initialise_attributes(self, locals())
        self.product = 'c856M4k'
        self.target = 'Zenith, azel, 0, 90'
        self.auto_delay = True

    @property
    def observer(self):
        return self._observer
    @observer.setter
    def observer(self, observer):
        self._observer = Antenna(observer)

    @property
    def target(self):
        return self._target
    @target.setter
    def target(self, target):
        self._target = Target(target) if target else None
        self._target.antenna = self.observer


class Environment(Component):
    def __init__(self):
        initialise_attributes(self, locals())
        self.pressure = 1020
        self.relative_humidity = 60.0
        self.temperature = 25.0
        self.wind_speed = 4.2
        self.wind_direction = 90.0


class Digitiser(Component):
    def __init__(self):
        initialise_attributes(self, locals())
        self.overflow = False


class Observation(Component):
    def __init__(self):
        initialise_attributes(self, locals())
        self.label = ''
        self.params = ''
