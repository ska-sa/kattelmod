#!/usr/bin/env python
# Track target(s) for a specified time.

import asyncio

from kattelmod import session_from_commandline

session = session_from_commandline(targets=True)
parser = session.argparser(description='Track one or more targets for a specified time.')
# Add experiment-specific options
parser.add_argument('-t', '--track-duration', metavar='DURATION', type=float, default=20.0,
                    help='Length of time to track each source, in seconds (default=%(default)s)')
# Set default value for any option (both standard and experiment-specific options)
parser.set_defaults(description='Basic track')
# Parse the command line
args = parser.parse_args()

async def run():
    # Start capture session, which creates HDF5 file
    async with await session.connect(args):
        for target in session.targets:
            # Start a new compound scan (skip if dish will hit horizon or azimuth wrap)
            for compscan in session.new_compound_scan():
                compscan.label = 'track'
                await compscan.track(target, duration=args.track_duration)


loop = session.make_event_loop(args)
asyncio.set_event_loop(loop)
loop.run_until_complete(run())
