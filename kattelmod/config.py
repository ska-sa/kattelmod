import os.path
from ConfigParser import SafeConfigParser, NoSectionError, Error
from importlib import import_module
from collections import OrderedDict

import numpy as np

import kattelmod.systems


def _create_component(cfg, system, comp_name, comp_type, **kwargs):
    comp_module, _, comp_class = comp_type.rpartition('.')
    module_path = "kattelmod.systems.{}.{}".format(system, comp_module)
    try:
        Component = getattr(import_module(module_path), comp_class)
    except (ImportError, AttributeError):
        raise Error("No component class named '{}.{}'".format(system, comp_type))
    params = {k: np.safe_eval(v) for k, v in cfg.items(comp_name)} \
             if cfg.has_section(comp_name) else {}
    params.update(kwargs)
    comp = Component(**params)
    comp.name = comp_name
    return comp


def session_from_config(config_file):
    # Default place to look for system config files is in systems module
    systems_path = os.path.dirname(kattelmod.systems.__file__)
    if not os.path.exists(config_file):
        config_file = os.path.join(systems_path, config_file)
    cfg = SafeConfigParser(allow_no_value=True)
    files_read = cfg.read(config_file)
    if files_read != [config_file]:
        raise Error("Could not open config file '{}'".format(config_file))
    # Get intended telescope system and verify that it is supported
    main = [sect for sect in cfg.sections() if sect.startswith('Telescope')]
    if not main:
        raise Error("Config file '{}' has no Telescope section".format(config_file))
    system = main[0].partition(' ')[2]
    try:
        import_module('kattelmod.systems.{}'.format(system))
    except ImportError:
        raise Error("Unknown telescope system '{}', expected one of {}"
                    .format(system, kattelmod.telescope_systems))
    # Load antenna descriptions
    all_ants = file(os.path.join(systems_path, system, 'antennas.txt')).readlines()
    all_ants = {line.split(',')[0]: line.strip() for line in all_ants}
    # Construct all components
    components = OrderedDict()
    receptors = ''
    for comp_name, comp_type in cfg.items('Telescope {}'.format(system)):
        # Expand receptor groups
        if comp_name.endswith('*') and cfg.has_section(comp_name[:-1]):
            names = []
            for initial, final in cfg.items(comp_name[:-1]):
                if not initial.endswith('+'):
                    continue
                names += [initial[:-1] + f for f in final if f in '0123456789']
            receptors = ','.join(names)
        else:
            names = [comp_name]
        for name in names:
            if comp_type.endswith('AntennaPositioner'):
                extras = {'observer': all_ants.get(name, '')}
            elif comp_type.endswith('Subarray'):
                extras = {'receptors': receptors}
            else:
                extras = {}
            components[name] = _create_component(cfg, system, name, comp_type,
                                                 **extras)
    # Construct session object
    module_path = "kattelmod.systems.{}.session".format(system)
    CaptureSession = getattr(import_module(module_path), 'CaptureSession')
    return CaptureSession(components)
