#!/usr/bin/env python
# Track target and calibrators for imaging.

from kattelmod import session_from_commandline

session = session_from_commandline(targets=True)
parser = session.argparser(description='Track target and calibrators for imaging.')
# Add experiment-specific options
parser.add_argument('-t', '--target-duration', type=float, default=300.,
                    metavar='DURATION',
                    help='Minimum duration to track the imaging target per '
                         'visit, in seconds (default=%(default)s)')
parser.add_argument('-b', '--bpcal-duration', type=float, default=300.,
                    metavar='DURATION',
                    help='Minimum duration to track bandpass calibrator per '
                         'visit, in seconds (default=%(default)s)')
parser.add_argument('-i', '--bpcal-interval', type=float, metavar='INTERVAL',
                    help='Minimum interval between bandpass calibrator visits, '
                         'in seconds (visits each source in turn by default)')
parser.add_argument('-g', '--gaincal-duration', type=float, default=60.,
                    metavar='DURATION',
                    help='Minimum duration to track gain calibrator per '
                         'visit, in seconds (default=%(default)s)')
parser.add_argument('-m', '--max-duration', type=float, metavar='DURATION',
                    help='Maximum duration of script, in seconds (the default '
                         'is to keep observing until all sources have set)')
# Set default value for any option (both standard and experiment-specific options)
parser.set_defaults(description='Imaging run')
# Parse the command line
args = parser.parse_args()

# Start capture session, which creates data set
async def run(session, args):
    bpcals = session.targets.filter('bpcal')
    gaincals = session.targets.filter('gaincal')
    targets = session.targets.filter(['~bpcal', '~gaincal'])
    session.logger.info("Imaging targets are [%s]",
                        ', '.join([repr(target.name) for target in targets]))
    session.logger.info("Bandpass calibrators are [%s]",
                        ', '.join([repr(bpcal.name) for bpcal in bpcals]))
    session.logger.info("Gain calibrators are [%s]",
                        ', '.join([repr(gaincal.name) for gaincal in gaincals]))
    duration = {'target': args.target_duration, 'bpcal': args.bpcal_duration,
                'gaincal': args.gaincal_duration}

    start_time = session.time()
    # If bandpass interval is specified, force first visit to be to
    # the bandpass calibrator(s)
    time_of_last_bpcal = 0
    loop = True

    while loop:
        source_observed = [False] * len(session.targets)
        # Loop over sources in catalogue in sequence
        for n, source in enumerate(session.targets):
            # The bandpass calibrator is due for a visit
            if (args.bpcal_interval is not None and
               session.time() - time_of_last_bpcal >= args.bpcal_interval):
                time_of_last_bpcal = session.time()
                for bpcal in bpcals:
                    for compscan in session.new_compound_scan():
                        compscan.label = 'track'
                        await compscan.track(bpcal, duration['bpcal'])
            # Visit source if it is not a bandpass calibrator
            # (or bandpass calibrators are not treated specially)
            # If there are no targets specified, assume the calibrators are the targets, else
            if args.bpcal_interval is None or 'bpcal' not in source.tags or not targets:
                # Set the default track duration for a target with no recognised tags
                track_duration = duration['target']
                for tag in source.tags:
                    track_duration = duration.get(tag, track_duration)
                for compscan in session.new_compound_scan():
                    compscan.label = 'track'
                    success = await compscan.track(source, track_duration)
                source_observed[n] = success
            if args.max_duration and session.time() > start_time + args.max_duration:
                session.logger.info('Maximum script duration (%d s) exceeded, '
                                    'stopping script', args.max_duration)
                loop = False
                break
        if loop and not any(source_observed):
            session.logger.warning('All imaging targets and gain cals are '
                                   'currently below horizon, stopping script')
            loop = False

session.run(args, run(session, args))
