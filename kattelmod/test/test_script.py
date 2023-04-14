"""Unit tests for basic observation scripts."""

import os.path
import subprocess

import kattelmod.test


testpath = os.path.dirname(kattelmod.test.__file__)


def test_run_script():
    script = os.path.join(testpath, 'basic_track.py')
    target = 'Sun, special'
    cmd = ['python3', script, target, '--dry-run',
            '--start-time=2016-02-25 10:14:00']
    process = subprocess.run(cmd, capture_output=True)
    print(process.stdout)
    print(process.stderr)
    assert process.returncode == 0
