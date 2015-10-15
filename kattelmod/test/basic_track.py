#!/usr/bin/env python
# Track target(s) for a specified time.

from kattelmod import CaptureSession

session = CaptureSession.from_commandline()
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
    # Iterate through source list, picking the next one that is up
    for target in session.targets:
        session.label('track')
        session.track(target, duration=args.track_duration)
