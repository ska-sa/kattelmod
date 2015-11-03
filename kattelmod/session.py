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


class CaptureSession(object):
    """Capturing a single subarray product."""
    def __init__(self, components=(), targets=True):
        self.components = components
        # Create corresponding attributes to access components
        for comp in components:
            setattr(self, comp._name, comp)
        self.targets = targets
        self._ioloop = self._ioloop_manager = None

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
