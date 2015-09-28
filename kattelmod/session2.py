import sys
import argparse


class CaptureSession(object):
    """Capturing a single subarray product."""
    def __init__(self, cmdline=None, targets=True):
        self.targets = targets

    @classmethod
    def from_commandline(cls):
        """Construct capture session from observation script parameters."""
        return cls(cmdline=sys.argv)

    def __enter__(self):
        """Enter context."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Exit context."""
        # Don't suppress exceptions
        return False

    def argparser(self, *args, **kwargs):
        parser = argparse.ArgumentParser(*args, **kwargs)
        parser.add_argument('--description')
        parser.add_argument('--dump-rate', type=float, default=2.0)
        if self.targets:
            parser.add_argument('targets', metavar='target', nargs='+')
        return parser

    def collect_targets(self, targets):
        return list(targets)

    def connect(self, args):
        if self.targets:
            self.targets = self.collect_targets(self.targets)
        return self

    @property
    def targets_up(self):
        return iter(self.targets)

    def label(self, label):
        pass

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
