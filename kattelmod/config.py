import os.path
from ConfigParser import SafeConfigParser, NoSectionError, Error
from importlib import import_module

import numpy as np

import kattelmod.systems
from kattelmod.component import MultiComponent


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
    try:
        comp = Component(**params)
    except TypeError as e:
        raise TypeError('Could not construct {}: {}'.format(Component._type(), e))
    comp._name = comp_name
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
    components = []
    for comp_name, comp_type in cfg.items('Telescope {}'.format(system)):
        # Expand receptor groups
        group = comp_name.endswith('*') and cfg.has_section(comp_name[:-1])
        if group:
            comp_name = comp_name[:-1]
            names = []
            for initial, final in cfg.items(comp_name):
                if initial == 'names':
                    names += final.split(',')
                elif initial.endswith('+'):
                    names += [initial[:-1] + f for f in final if f in '0123456789']
        else:
            names = [comp_name]
        comps = []
        for name in names:
            if comp_type.endswith('AntennaPositioner'):
                extras = {'observer': all_ants.get(name, '')}
            else:
                extras = {}
            comps.append(_create_component(cfg, system, name, comp_type, **extras))
        components.append(MultiComponent(comp_name, comps) if group else comps[0])
    # Construct session object
    module_path = "kattelmod.systems.{}.session".format(system)
    CaptureSession = getattr(import_module(module_path), 'CaptureSession')
    return CaptureSession(MultiComponent(system, components))
