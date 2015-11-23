import logging
import collections
import argparse
import time

from katcp.ioloop_manager import IOLoopManager


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


class ScriptLogHandler(logging.Handler):
    """Logging handler that writes observation log records to obs component.

    Parameters
    ----------
    obs : :class:`kattelmod.component.Component` object
        Observation component for the session

    """
    def __init__(self, obs):
        logging.Handler.__init__(self)
        self.obs = obs
        self.busy_emitting = False

    def emit(self, record):
        """Emit a logging record."""
        # Do not emit from within emit()
        # This occurs when the script_log setting fails and logs an error itself
        if self.busy_emitting:
            return
        try:
            self.busy_emitting = True
            msg = self.format(record)
            self.obs.script_log = msg
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)
        finally:
            self.busy_emitting = False


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


class CaptureSession(object):
    """Capturing a single subarray product."""
    def __init__(self, components=(), targets=False):
        self.components = components
        # Create corresponding attributes to access components
        for comp in components:
            setattr(self, comp._name, comp)
        self.targets = targets
        self._ioloop = self._ioloop_manager = None
        self._script_log_handler = self._root_log_handler = None
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

    def argparser(self, *args, **kwargs):
        parser = argparse.ArgumentParser(*args, **kwargs)
        parser.add_argument('--config', default='mkat/fake_rts.cfg')
        parser.add_argument('--description')
        parser.add_argument('--dump-rate', type=float, default=2.0)
        parser.add_argument('--log-level', default='INFO')
        parser.add_argument('--dont-stop', action='store_true')
        if self.targets:
            parser.add_argument('targets', metavar='target', nargs='+')
        return parser

    def collect_targets(self, targets):
        return list(targets)

    def _setup_logging(self, args):
        self.logger.setLevel(args.log_level)
        # Script log formatter has UT timestamps
        fmt='%(asctime)s.%(msecs)dZ %(levelname)-8s %(message)s'
        formatter = logging.Formatter(fmt, datefmt='%Y-%m-%d %H:%M:%S')
        formatter.converter = time.gmtime
        # Add special script log handler
        if hasattr(self, 'obs'):
            self._script_log_handler = ScriptLogHandler(self.obs)
            self._script_log_handler.setLevel(args.log_level)
            self._script_log_handler.setFormatter(formatter)
            self.logger.addHandler(self._script_log_handler)
        # Add root handler if none exists - similar to logging.basicConfig()
        if not logging.root.handlers:
            self._root_log_handler = logging.StreamHandler()
            logging.root.addHandler(self._root_log_handler)
        for handler in logging.root.handlers:
            handler.setLevel(args.log_level)
            handler.setFormatter(formatter)

    def _teardown_logging(self):
        if self._script_log_handler:
            self.logger.removeHandler(self._script_log_handler)
        if self._root_log_handler:
            logging.root.removeHandler(self._root_log_handler)

    def _start(self, args):
        self._ioloop_manager = IOLoopManager()
        self._ioloop = self._ioloop_manager.get_ioloop()
        self._ioloop.make_current()
        self._ioloop_manager.start()
        self._setup_logging(args)
        self._initial_state = self.product_configure(args)
        self.components._start(self._ioloop)

    def _stop(self):
        if self._initial_state < CaptureState.CONFIGURED:
            self.product_deconfigure()
        self.components._stop()
        self._teardown_logging()
        self._ioloop_manager.stop()
        self._ioloop_manager.join()

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
            time.sleep(duration)
            return
        self.ants.activity = 'slew'
        self.logger.info('slewing to target')
        # Wait until we are on target
        while set(ant.activity for ant in self.ants) != set(['track']):
            time.sleep(JIFFY)
            self.components._update(time.time())
        self.logger.info('target reached')
        # Stay on target for desired time
        self.logger.info('tracking target')
        end_time = time.time() + duration
        while time.time() < end_time:
            time.sleep(JIFFY)
            self.components._update(time.time())
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
