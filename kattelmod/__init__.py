import os.path as _path
import pkgutil as _pkgutil

import kattelmod.systems
from kattelmod.session import CaptureSession
from kattelmod.config import session_from_config


_systems_path = _path.dirname(kattelmod.systems.__file__)
telescope_systems = [s for _, s, _ in _pkgutil.iter_modules([_systems_path])]

def session_from_commandline(targets=False):
    """Construct capture session from observation script parameters."""
    # Make dummy CaptureSession just to get --config entry from command line
    args, other = CaptureSession().argparser().parse_known_args()
    session = session_from_config(args.config)
    session.targets = targets
    return session

# Keep API clean when inspected by user via e.g. IPython
del s
