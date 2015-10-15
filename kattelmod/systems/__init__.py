"""Telescope systems supported for observation."""

import sys
import os.path
import pkgutil

systems_module = sys.modules[__name__]
systems_path = os.path.dirname(systems_module.__file__)
systems = [s for _, s, _ in pkgutil.iter_modules([systems_path])]
# Hard-code for now as KAT7 and RTS are broken without katcorelib
systems = ['mkat']

session = {}
# model = {}
for system in systems:
    parent = "%s.%s" % (__name__, system)
    system_module = __import__(parent + '.session', fromlist=[parent])
    session[system] = system_module.CaptureSession
#    model[system] = os.path.join(systems_path, system, 'model.cfg')

del systems_module, systems_path, parent, system_module