import logging
import collections
import argparse
import time

from kattelmod.updater import WarpClock, PeriodicUpdaterThread
from kattelmod.logger import configure_logging


# Period of component updates, in seconds
JIFFY = 0.1


class CaptureState(object):
    """State of data capturing subsystem."""
    UNKNOWN = 0
    UNCONFIGURED = 10
    CONFIGURED = 20
    INITED = 30
    STARTED = 40

    @classmethod
    def name(cls, code):
        states = [v for v in vars(cls) if not v.startswith('_') and v != 'name']
        return dict((getattr(cls, s), s) for s in states)[code]


class ObsParams(collections.MutableMapping):
    """Dictionary-ish that writes observation parameters to obs component.

    Parameters
    ----------
    obs : :class:`kattelmod.component.Component` object
        Observation component for the session

    Notes
    -----
    This is based on the collections.MutableMapping abstract base class instead
    of dict itself. This ensures that dict is properly extended by containing
    a dict inside ObsParams instead of deriving from it. The problem is that
    methods such as dict.update() do not honour custom __setitem__ methods.

    """
    def __init__(self, obs):
        self._dict = dict()
        self.obs = obs

    def __getitem__(self, key):
        return self._dict[key]

    def __setitem__(self, key, value):
        """Set item both in dictionary and component."""
        self.obs.params = "{} {}".format(key, repr(value))
        self._dict[key] = value

    def __delitem__(self, key):
        self.obs.params = key
        del self._dict[key]

    def __iter__(self):
        return iter(self._dict)

    def __len__(self):
        return len(self._dict)

    def __contains__(self, key):
        return key in self._dict

    def __str__(self):
        return str(self._dict)

    def __repr__(self):
        return repr(self._dict)


def flatten(obj):
    """http://rightfootin.blogspot.co.za/2006/09/more-on-python-flatten.html"""
    try:
        it = iter(obj)
    except TypeError:
        yield obj
    else:
        for e in it:
            for f in flatten(e):
                yield f


class CaptureSession(object):
    """Capturing a single subarray product."""
    def __init__(self, components=()):
        self.components = components
        # Create corresponding attributes to access components
        for comp in components:
            setattr(self, comp._name, comp)
        self._clock = WarpClock()
        updatable = lambda c: hasattr(c, '_update') and callable(c._update)
        updatable_comps = [c for c in flatten(components) if updatable(c)]
        self._updater = PeriodicUpdaterThread(updatable_comps, self._clock, JIFFY) \
                        if updatable_comps else None
        self.targets = False
        self.obs_params = ObsParams(self.obs) if hasattr(self, 'obs') else {}
        self.logger = logging.getLogger('kat.session')

    def __enter__(self):
        """Enter context."""
        if self._initial_state < CaptureState.STARTED:
            self.capture_start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Exit context."""
        if self._initial_state < CaptureState.STARTED:
            self.capture_stop()
        self.disconnect()
        # Don't suppress exceptions
        return False

    def time(self):
        """Current time in UTC seconds since Unix epoch."""
        return self._clock.time()

    def sleep(self, seconds, condition=None):
        """Sleep for the requested duration in seconds."""
        self._clock.sleep(seconds, condition)

    @property
    def dry_run(self):
        return self._clock.warp
    @dry_run.setter
    def dry_run(self, flag):
        updatable = lambda c: hasattr(c, '_update') and callable(c._update)
        fake = lambda c: updatable(c) and c.__class__.__module__.endswith('.fake')
        all_fake = all([fake(c) for c in flatten(self.components)])
        if flag and not all_fake:
            self.logger.warning('Could not enable dry-running as session contains non-fake components')
        self._clock.warp = flag and all_fake

    def argparser(self, *args, **kwargs):
        parser = argparse.ArgumentParser(*args, **kwargs)
        parser.add_argument('--config', default='mkat/fake_rts.cfg')
        parser.add_argument('--description')
        parser.add_argument('--dont-stop', action='store_true')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--dump-rate', type=float, default=2.0)
        parser.add_argument('--log-level', default='INFO')
        if self.targets:
            parser.add_argument('targets', metavar='target', nargs='+')
        return parser

    def collect_targets(self, targets):
        return list(targets)

    def _configure_logging(self, log_level):
        script_log_cmd = None
        if hasattr(self, 'obs'):
            def script_log_cmd(msg):
                self.obs.script_log = msg
        configure_logging(log_level, script_log_cmd, self._clock, self.dry_run)

    def _start(self, args):
        self._configure_logging(args.log_level)
        self._initial_state = self.product_configure(args)
        self.components._start()
        if self._updater:
            self._updater.start()

    def _stop(self):
        if self._initial_state < CaptureState.CONFIGURED:
            self.product_deconfigure()
        if self._updater:
            self._updater.stop()
            self._updater.join()
        self.components._stop()

    def connect(self, args=None):
        if args is None:
            args = self.argparser().parse_args()
        self._start(args)
        if self._initial_state < CaptureState.INITED:
            self.capture_init()
        self.obs_params.update(vars(args))
        if self.targets:
            self.targets = self.collect_targets(args.targets)
        return self

    def disconnect(self):
        if self._initial_state < CaptureState.INITED:
            self.capture_done()
        if not self.obs_params['dont_stop']:
            self._stop()

    def new_compound_scan(self):
        yield self

    @property
    def label(self):
        return self.obs.label
    @label.setter
    def label(self, label):
        self.obs.label = label

    @property
    def target(self):
        return self.cbf.target if hasattr(self, 'cbf') else \
               self.ants[0].target if hasattr(self, 'ants') else None
    @target.setter
    def target(self, target):
        if hasattr(self, 'ants'):
            self.ants.target = target
        if hasattr(self, 'cbf'):
            self.cbf.target = target

    @property
    def observer(self):
        return self.cbf.observer if hasattr(self, 'cbf') else \
               self.ants[0].observer if hasattr(self, 'ants') else None

    def track(self, target, duration):
        self.target = target
        if not hasattr(self, 'ants'):
            self.sleep(duration)
            return
        self.ants.activity = 'slew'
        self.logger.info('slewing to target')
        # Wait until we are on target
        cond = lambda: set(ant.activity for ant in self.ants) == set(['track'])
        self.sleep(200, cond)
        self.logger.info('target reached')
        # Stay on target for desired time
        self.logger.info('tracking target')
        self.sleep(duration)
        self.logger.info('target tracked for {} seconds'.format(duration))

"""
    time
    sleep

    receptors - m062, m063, ...
    cbf
    sdp
    enviro
    obs -> label / script_log

    target

req:
    configure
#    fire_noise_diode

    capture_init
    capture_start
    capture_stop
    capture_done

sensor:
    centre_freq
    band
    dump_rate
    product

receptors:
    on_target
    load_scan
    track
    scan
"""
