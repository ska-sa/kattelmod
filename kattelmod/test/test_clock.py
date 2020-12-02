import unittest
import time
import asyncio
import functools
from socket import socketpair
from typing import Any, cast

import asynctest

from ..clock import Clock, WarpEventLoop


# Testing clocks is tricky because they change every time you look. This
# is the maximum amount we allow the clock to advance while executing code.
CLOCK_TOL = 0.05
START_TIME = 1234567890.0


class TestRealClock(unittest.TestCase):
    def test_realtime(self):
        """Default-constructed clock should track real time"""
        clock = Clock()
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

    def test_non_realtime(self):
        """Clock with non-unit rate"""
        clock = Clock(rate=0.25)
        real_now1 = time.monotonic()
        now1 = clock.time()
        mono1 = clock.monotonic()
        time.sleep(0.5)
        real_now2 = time.monotonic()
        now2 = clock.time()
        mono2 = clock.monotonic()
        real_elapsed = real_now2 - real_now1
        self.assertAlmostEqual((now2 - now1) * 0.25, real_elapsed, delta=CLOCK_TOL)
        self.assertAlmostEqual((mono2 - mono1) * 0.25, real_elapsed, delta=CLOCK_TOL)

    def test_start_time(self):
        """Clock with explicit start time"""
        clock = Clock(1.0, START_TIME)
        time1 = clock.time()
        mono1 = clock.monotonic()
        time.sleep(0.5)
        time2 = clock.time()
        mono2 = clock.monotonic()
        self.assertAlmostEqual(time1, START_TIME, delta=CLOCK_TOL)
        self.assertAlmostEqual(time2, START_TIME + 0.5, delta=CLOCK_TOL)
        self.assertAlmostEqual(mono2 - mono1, 0.5, delta=CLOCK_TOL)


class TestWarpClock(unittest.TestCase):
    def test(self):
        clock = Clock(0.0, START_TIME)
        monotonic_start = clock.monotonic()
        self.assertEqual(clock.time(), START_TIME)

        clock.advance(3.5)
        self.assertEqual(clock.time(), START_TIME + 3.5)
        self.assertEqual(clock.monotonic(), monotonic_start + 3.5)


def run_with_loop(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        loop = WarpEventLoop(Clock(0.0, START_TIME))
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


class WarpEventLoopPolicy(asyncio.AbstractEventLoopPolicy):
    """Policy used in other tests to set up a warp event loop for the test."""

    def __init__(self, original: asyncio.AbstractEventLoopPolicy,
                 rate: float, start_time: float) -> None:
        self.original = original
        self.rate = rate
        self.start_time = start_time

    def get_event_loop(self) -> asyncio.AbstractEventLoop:
        return self.original.get_event_loop()

    def set_event_loop(self, loop) -> None:
        self.original.set_event_loop(loop)

    def new_event_loop(self) -> asyncio.AbstractEventLoop:
        return WarpEventLoop(Clock(self.rate, self.start_time))

    def get_child_watcher(self) -> Any:
        return self.original.get_child_watcher()

    def set_child_watcher(self, watcher: Any) -> None:
        self.original.set_child_watcher(watcher)


class WarpEventLoopTestCase(asynctest.TestCase):
    RATE = 0.0
    START_TIME = 1234567890.0

    @classmethod
    def setUpClass(cls) -> None:
        # Make asynctest create a WarpEventLoop
        policy = WarpEventLoopPolicy(asyncio.get_event_loop_policy(), cls.RATE, cls.START_TIME)
        asyncio.set_event_loop_policy(policy)

    @classmethod
    def tearDownClass(cls) -> None:
        policy = cast(WarpEventLoopPolicy, asyncio.get_event_loop_policy())
        asyncio.set_event_loop_policy(policy.original)
