"""Unit tests for CaptureSession."""

import unittest2 as unittest
import os.path
import shlex
import subprocess

import kattelmod


testpath = os.path.dirname(kattelmod.test.__file__)

class TestBasicTrack(unittest.TestCase):
    def test_run_script(self):
        script = os.path.join(testpath, 'basic_track.py')
        cmd = '/usr/bin/env python {} --help'.format(script)
        subprocess.check_call(shlex.split(cmd))
