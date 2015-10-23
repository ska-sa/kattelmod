import os.path as _path
import pkgutil as _pkgutil
import argparse as _argparse

import kattelmod.systems
from kattelmod.session import CaptureSession
from kattelmod.config import session_from_config


_systems_path = _path.dirname(kattelmod.systems.__file__)
telescope_systems = [s for _, s, _ in _pkgutil.iter_modules([_systems_path])]

def session_from_commandline():
    """Construct capture session from observation script parameters."""
    _parser = _argparse.ArgumentParser()
    _parser.add_argument('--config')
    args, other = _parser.parse_known_args()
    return session_from_config(args.config)

# Keep API clean when inspected by user via e.g. IPython
del session, config, s
