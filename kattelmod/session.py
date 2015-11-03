import collections
import argparse

from katcp.ioloop_manager import IOLoopManager


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


class CaptureSession(object):
    """Capturing a single subarray product."""
    def __init__(self, components=(), targets=True):
        self.components = components
        # Create corresponding attributes to access components
        for comp in components:
            setattr(self, comp._name, comp)
        self.targets = targets
        self._ioloop = self._ioloop_manager = None
        self.obs_params = ObsParams(self.obs) if hasattr(self, 'obs') else {}

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
        if self.targets:
            parser.add_argument('targets', metavar='target', nargs='+')
        return parser

    def collect_targets(self, targets):
        return list(targets)

    def connect(self, args):
        if self.targets:
            self.targets = self.collect_targets(args.targets)
        self._ioloop_manager = IOLoopManager()
        self._ioloop = self._ioloop_manager.get_ioloop()
        self._ioloop.make_current()
        self._ioloop_manager.start()
        self._initial_state = self.product_configure(args)
        self.components._start(self._ioloop)
        if self._initial_state < CaptureState.INITED:
            self.capture_init()
        return self

    def disconnect(self):
        if self._initial_state < CaptureState.INITED:
            self.capture_done()
        if self._initial_state < CaptureState.CONFIGURED:
            self.product_deconfigure()
        self.components._stop()
        self._ioloop_manager.stop()
        self._ioloop_manager.join()

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
        pass

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
