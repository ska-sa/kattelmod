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
    # Don't enable --help as full argument list is not yet available
    args, other = CaptureSession().argparser(add_help=False).parse_known_args()
    session = session_from_config(args.config)
    session.targets = targets
    return session

# BEGIN VERSION CHECK
# Get package version when locally imported from repo or via -e develop install
try:
    import katversion as _katversion
except ImportError:
    import time as _time
    __version__ = "0.0+unknown.%s" % (_time.strftime('%Y%m%d%H%M'),)
else:
    __version__ = _katversion.get_version(__path__[0])  # noqa: F821
# END VERSION CHECK
