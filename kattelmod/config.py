import os.path
from ConfigParser import SafeConfigParser, Error
from importlib import import_module

import numpy as np

import kattelmod.systems
from kattelmod.component import MultiComponent, construct_component


def session_from_config(config_file):
    # Default place to look for system config files is in systems module
    systems_path = os.path.dirname(kattelmod.systems.__file__)
    cfg = SafeConfigParser(allow_no_value=True)
    # Handle file-like objects separately
    if hasattr(config_file, 'readline'):
        cfg.readfp(config_file)
    else:
        if not os.path.exists(config_file):
            config_file = os.path.join(systems_path, config_file)
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
                    names += [name.strip() for name in final.split(',')]
                elif initial.endswith('+'):
                    names += [initial[:-1] + f for f in final if f in '0123456789']
        else:
            names = [comp_name]
        comps = []
        for name in names:
            params = {k: np.safe_eval(v) for k, v in cfg.items(name)} \
                if cfg.has_section(name) else {}
            if comp_type.endswith('AntennaPositioner'):
                # XXX Complain if antenna is unknown
                params['observer'] = all_ants.get(name, '')
            full_comp_type = '.'.join((system, comp_type))
            try:
                comp = construct_component(full_comp_type, name, params)
            except TypeError as e:
                raise Error(e.message)
            comps.append(comp)
        # XXX Complain if comps is empty
        components.append(MultiComponent(comp_name, comps) if group else comps[0])
    # Construct session object
    module_path = "kattelmod.systems.{}.session".format(system)
    CaptureSession = getattr(import_module(module_path), 'CaptureSession')
    return CaptureSession(MultiComponent(system, components))
