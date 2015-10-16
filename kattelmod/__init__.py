import sys as _sys

from kattelmod.session import CaptureSession
from kattelmod.systems import session as _system_session

def session_from_commandline():
    """Construct capture session from observation script parameters."""
    return _system_session['mkat'](cmdline=_sys.argv)

# Keep API clean when inspected by user via e.g. IPython
del session, systems
