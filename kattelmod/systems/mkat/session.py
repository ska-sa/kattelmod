from kattelmod.session import CaptureState, CaptureSession as BaseCaptureSession
from kattelmod.telstate import TelescopeState


class CaptureSession(BaseCaptureSession):
    """Capture session for the MeerKAT system."""

    def argparser(self, *args, **kwargs):
        parser = super(CaptureSession, self).argparser(*args, **kwargs)
        parser.add_argument('--telstate')
        return parser

    def _get_telstate(self, args):
        if getattr(args, 'telstate', None):
            endpoint = args.telstate
        elif hasattr(self, 'sdp'):
            endpoint = self.sdp.get_telstate()
        else:
            endpoint = ''
        return TelescopeState(endpoint) if endpoint else None

    def product_configure(self, args):
        if all(hasattr(self, comp) for comp in ('sub', 'sdp', 'ants')):
            ants = [var for var in vars(self.ants) if not var.startswith('_')]
            self.sdp._start(self._ioloop)
            prod_conf = self.sdp.product_configure
            initial_state = prod_conf(self.sub.product, self.sub.dump_rate,
                                      ','.join(sorted(ants)), self.sub.sub_nr)
        self._telstate = self.components._telstate = self._get_telstate(args)
        return initial_state

    def capture_init(self):
        if hasattr(self, 'sdp'):
            self.sdp.capture_init()

    def capture_start(self):
        if hasattr(self, 'cbf'):
            self.cbf.capture_start()

    def capture_stop(self):
        if hasattr(self, 'cbf'):
            self.cbf.capture_stop()

    def capture_done(self):
        if hasattr(self, 'sdp'):
            self.sdp.capture_done()

    def product_deconfigure(self):
        if hasattr(self, 'sdp'):
            self.sdp.product_deconfigure()
