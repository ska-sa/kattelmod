import unittest
import time
import asyncio
import functools
from socket import socketpair

from ..clock import RealClock, WarpClock, WarpEventLoop


# Testing clocks is tricky because they change every time you look. This
# is the maximum amount we allow the clock to advance while executing code.
CLOCK_TOL = 0.05
START_TIME = 1234567890.0


class TestRealClock(unittest.TestCase):
    def test_realtime(self):
        """Default-constructed clock should track real time"""
        clock = RealClock()
        now1 = time.time()
        now2 = clock.time()
        now3 = time.time()
        self.assertLessEqual(now1, now2)
        self.assertLessEqual(now2, now3)

        now1 = time.monotonic()
        now2 = clock.monotonic()
        now3 = time.monotonic()
        self.assertLessEqual(now1, now2)
        self.assertLessEqual(now2, now3)

    def test_start_time(self):
        """Clock with explicit start time"""
        clock = RealClock(START_TIME)
        time1 = clock.time()
        mono1 = clock.monotonic()
        time.sleep(0.5)
        time2 = clock.time()
        mono2 = clock.monotonic()
        self.assertAlmostEqual(time1, START_TIME, delta=CLOCK_TOL)
        self.assertAlmostEqual(time2, START_TIME + 0.5, delta=CLOCK_TOL)
        self.assertAlmostEqual(mono2 - mono1, 0.5, delta=CLOCK_TOL)

    def test_advance(self):
        """Test that clock can be advanced"""
        clock = RealClock(START_TIME)
        mono1 = clock.monotonic()
        clock.advance(3.5)
        mono2 = clock.monotonic()
        self.assertAlmostEqual(clock.time(), START_TIME + 3.5, delta=CLOCK_TOL)
        self.assertAlmostEqual(mono2 - mono1, 3.5, delta=CLOCK_TOL)


class TestWarpClock(unittest.TestCase):
    def test(self):
        clock = WarpClock(START_TIME)
        monotonic_start = clock.monotonic()
        self.assertEqual(clock.time(), START_TIME)

        clock.advance(3.5)
        self.assertEqual(clock.time(), START_TIME + 3.5)
        self.assertEqual(clock.monotonic(), monotonic_start + 3.5)


def run_with_loop(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        loop = WarpEventLoop(WarpClock(START_TIME))
        args[0].addCleanup(loop.close)
        loop.run_until_complete(func(*args, **kwargs))

    return wrapper


class TestWarpEventLoop(unittest.TestCase):
    async def _periodic(self, period, repeats, events):
        """Wake up periodically and record the time to `events`"""
        for i in range(repeats):
            await asyncio.sleep(period)
            events.append(asyncio.get_event_loop().time())

    @run_with_loop
    async def test_sleep(self):
        loop = asyncio.get_event_loop()
        self.assertEqual(loop.time(), 0.0)
        events = []
        await asyncio.gather(
            self._periodic(5, 3, events),
            self._periodic(4, 4, events))
        self.assertEqual(events, [4, 5, 8, 10, 12, 15, 16])

    @run_with_loop
    async def test_socket(self):
        loop = asyncio.get_event_loop()
        rsock, wsock = socketpair()
        self.addCleanup(rsock.close)
        self.addCleanup(wsock.close)

        reader, writer = await asyncio.open_connection(sock=rsock)
        self.addCleanup(writer.close)

        wsock.send(b'somedata')
        self.assertEqual(loop.time(), 0.0)
        data = await asyncio.wait_for(reader.read(8), timeout=5)
        self.assertEqual(data, b'somedata')
        # The data was there immediately, so time should not have advanced
        self.assertEqual(loop.time(), 0.0)

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.read(8), timeout=5)
        self.assertEqual(loop.time(), 5.0)
