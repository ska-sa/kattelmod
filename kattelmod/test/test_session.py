"""Unit tests for CaptureSession."""

import unittest
import os.path
from subprocess import Popen, PIPE

import kattelmod


testpath = os.path.dirname(kattelmod.test.__file__)


class TestBasicTrack(unittest.TestCase):
    def test_run_script(self):
        script = os.path.join(testpath, 'basic_track.py')
        target = 'Sun, special'
        cmd = ['python', script, target, '--dry-run',
               '--start-time=2016-02-25 10:14:00']
        process = Popen(cmd, stdout=PIPE, stderr=PIPE)
        stdout, stderr = process.communicate()
        print(stdout)
        print(stderr)
        self.assertEqual(process.returncode, 0)
