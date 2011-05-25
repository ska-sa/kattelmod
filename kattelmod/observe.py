"""Set of useful routines to do standard observations with KAT."""

import optparse
import uuid

from .defaults import user_logger
from .utility import tbuild
from .session1 import CaptureSession as CaptureSession1, TimeSession as TimeSession1
from .session2 import CaptureSession as CaptureSession2, TimeSession as TimeSession2, projections, default_proj

def standard_script_options(usage, description):
    """Create option parser pre-populated with standard observation script options.

    Parameters
    ----------
    usage, description : string
        Usage and description strings to be used for script help

    Returns
    -------
    parser : :class:`optparse.OptionParser` object
        Parser populated with standard script options

    """
    parser = optparse.OptionParser(usage=usage, description=description)

    parser.add_option('-s', '--system', help='System configuration file to use, relative to conf directory '
                      '(default reuses existing connection, or falls back to systems/local.conf)')
    parser.add_option('-u', '--experiment-id', help='Experiment ID used to link various parts of experiment '
                      'together (UUID generated by default)')
    parser.add_option('-o', '--observer', help='Name of person doing the observation (**required**)')
    parser.add_option('-d', '--description', default='No description.',
                      help="Description of observation (default='%default')")
    parser.add_option('-a', '--ants', help="Comma-separated list of antennas to include " +
                      "(e.g. 'ant1,ant2'), or 'all' for all antennas (**required** - safety reasons)")
    parser.add_option('-f', '--centre-freq', type='float', default=1822.0,
                      help='Centre frequency, in MHz (default=%default)')
    parser.add_option('-r', '--dump-rate', type='float', default=1.0, help='Dump rate, in Hz (default=%default)')
# This option used to be in observe1, but did not make it to the common set of options of observe1 / observe2
#    parser.add_option('-w', '--discard-slews', dest='record_slews', action='store_false', default=True,
#                      help='Do not record all the time, i.e. pause while antennas are slewing to the next target')
    parser.add_option('-n', '--nd-params', default='coupler,10,10,180',
                      help="Noise diode parameters as 'diode,on,off,period', in seconds (default='%default')")
    parser.add_option('-p', '--projection', type='choice', choices=projections, default=default_proj,
                      help="Spherical projection in which to perform scans, one of '%s' (default), '%s'" %
                           (projections[0], "', '".join(projections[1:])))
    parser.add_option('-y', '--dry-run', action='store_true', default=False,
                      help="Do not actually observe, but display script actions at predicted times (default=%default)")
    parser.add_option('--stow-when-done', action='store_true', default=False,
                      help="Stow the antennas when the capture session ends.")
    parser.add_option('--dbe', default='dbe', help="DBE proxy / correlator to use for experiment (default='%default')")

    return parser

def verify_and_connect(opts):
    """Verify command-line options, build KAT configuration and connect to devices.

    This inspects the parsed options and requires at least *ants*, *observer*
    and *system* to be set. It generates an experiment ID if missing and
    verifies noise diode parameters if given. It then creates a KAT connection
    based on the *system* option, reusing an existing connection or falling back
    to the local system if required. The resulting KATHost object is returned.

    Parameters
    ----------
    opts : :class:`optparse.Values` object
        Parsed command-line options (will be updated by this function). Should
        contain at least the options *ants*, *observer* and *system*.

    Returns
    -------
    kat : :class:`utility.KATHost` object
        KAT connection object associated with this experiment

    Raises
    ------
    ValueError
        If required options are missing

    """
    # Various non-optional options...
    if not hasattr(opts, 'ants') or opts.ants is None:
        raise ValueError('Please specify the antennas to use via -a option (yes, this is a non-optional option...)')
    if not hasattr(opts, 'observer') or opts.observer is None:
        raise ValueError('Please specify the observer name via -o option (yes, this is a non-optional option...)')
    if not hasattr(opts, 'experiment_id') or opts.experiment_id is None:
        # Generate unique string via RFC 4122 version 1
        opts.experiment_id = str(uuid.uuid1())

    # If given, verify noise diode parameters (should be 'string,number,number,number') and convert to dict
    if hasattr(opts, 'nd_params'):
        try:
            opts.nd_params = eval("{'diode':'%s', 'on':%s, 'off':%s, 'period':%s}" %
                                  tuple(opts.nd_params.split(',')), {})
        except (TypeError, NameError):
            raise ValueError("Noise diode parameters are incorrect (should be 'diode,on,off,period')")
        for key in ('on', 'off', 'period'):
            if opts.nd_params[key] != float(opts.nd_params[key]):
                raise ValueError("Parameter nd_params['%s'] = %s (should be a number)" % (key, opts.nd_params[key]))

    # Try to build KAT configuration (which might be None, in which case try to reuse latest active connection)
    # This connects to all the proxies and devices and queries their commands and sensors
    try:
        kat = tbuild(opts.system)
    # Fall back to *local* configuration to prevent inadvertent use of the real hardware
    except ValueError:
        kat = tbuild('systems/local.conf')
    user_logger.info("Using KAT connection with configuration: %s" % (kat.config_file,))

    return kat

def start_session(kat, dbe='dbe', dry_run=False, **kwargs):
    """Start capture session (real or fake).

    This starts a capture session initialised with the given arguments, choosing
    the appropriate session class to use based on the arguments. The *dbe*
    parameter selects which version of :class:`CaptureSession` to use, while
    the *dry_run* parameter decides whether a fake :class:`TimeSession` will
    be used instead.

    Parameters
    ----------
    kat : :class:`utility.KATHost` object
        KAT connection object associated with this experiment
    dbe : string, optional
        Name of DBE proxy to use (effectively selects the correlator)
    dry_run : {False, True}, optional
        True if no real capturing will be done, only timing of the commands
    kwargs : dict, optional
        Ignore any other keyword arguments (simplifies passing options as dict)

    Returns
    -------
    session : :class:`CaptureSession` or :class:`TimeSession` object
        Session object associated with started session

    Raises
    ------
    ValueError
        If DBE proxy device is unknown

    """
    if dbe == 'dbe':
        return TimeSession1(kat, dbe, **kwargs) if dry_run else CaptureSession1(kat, dbe, **kwargs)
    elif dbe == 'dbe7':
        return TimeSession2(kat, dbe, **kwargs) if dry_run else CaptureSession2(kat, dbe, **kwargs)
    else:
        raise ValueError("Unknown DBE proxy device specified - should be 'dbe' (FF) or 'dbe7' (KAT-7)")

def lookup_targets(kat, args):
    """Look up targets by name in default catalogue, or keep as description string.

    Parameters
    ----------
    kat : :class:`utility.KATHost` object
        KAT connection object associated with this experiment
    args : list of strings
        Argument list containing mixture of target names and description strings

    Returns
    -------
    targets : list of strings and :class:`katpoint.Target` objects
        Targets as objects or description strings

    Raises
    ------
    ValueError
        If final target list is empty

    """
    # Look up target names in catalogue, and keep target description strings as is
    targets = []
    for arg in args:
        # With no comma in the target string, assume it's the name of a target to be looked up in the standard catalogue
        if arg.find(',') < 0:
            target = kat.sources[arg]
            if target is None:
                user_logger.info("Unknown source '%s', skipping it" % (arg,))
            else:
                targets.append(target)
        else:
            # Assume the argument is a target description string
            targets.append(arg)
    if len(targets) == 0:
        raise ValueError("No known targets found")
    return targets
