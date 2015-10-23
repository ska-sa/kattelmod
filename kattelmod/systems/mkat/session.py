from kattelmod.session import CaptureSession as BaseCaptureSession

class CaptureSession(BaseCaptureSession):
    """Capture session for the MeerKAT system."""

    def argparser(self, *args, **kwargs):
        parser = super(CaptureSession, self).argparser(*args, **kwargs)
        parser.add_argument('--blah')
        return parser

    def product_configure(self):
        pass

    def capture_init(self):
        pass

    def capture_start(self):
        pass

    def capture_stop(self):
        pass

    def capture_done(self):
        pass
