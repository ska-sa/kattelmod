#!/usr/bin/env python
# Track target(s) for a specified time.

from kattelmod import session_from_commandline

session = session_from_commandline(targets=True)
parser = session.argparser(description='Track one or more targets for a specified time.')
# Add experiment-specific options
parser.add_argument('-t', '--track-duration', metavar='DURATION', type=float, default=20.0,
                    help='Length of time to track each source, in seconds (default=%(default)s)')
# Set default value for any option (both standard and experiment-specific options)
parser.set_defaults(description='Basic track', dump_rate=1.0)
# Parse the command line
args = parser.parse_args()

# Start capture session, which creates HDF5 file
with session.connect(args):
    for target in session.targets:
        # Start a new compound scan (skip if dish will hit horizon or azimuth wrap)
        for compscan in session.new_compound_scan():
            compscan.label = 'track'
            compscan.track(target, duration=args.track_duration)
