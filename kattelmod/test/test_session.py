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
        cmd = '/usr/bin/env python {} "Sun, special"'.format(script)
#        subprocess.check_call(shlex.split(cmd))
        process = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        print stdout
        print stderr
        self.assertEqual(process.returncode, 0)
