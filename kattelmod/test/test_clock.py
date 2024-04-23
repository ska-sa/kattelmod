import contextlib
import time
import asyncio
import functools
from socket import socketpair
from typing import Any

from kattelmod.clock import Clock, WarpEventLoop
import pytest


# Testing clocks is tricky because they change every time you look. This
# is the maximum amount we allow the clock to advance while executing code.
CLOCK_TOL = 0.05
START_TIME = 1234567890.0


def _almost_equal(a, b):
    return a == pytest.approx(b, abs=CLOCK_TOL)


def test_realtime_clock():
    """Default-constructed clock should track real time"""
    clock = Clock()
    now1 = time.time()
    now2 = clock.time()
    now3 = time.time()
    assert now1 <= now2
    assert now2 <= now3

    now1 = time.monotonic()
    now2 = clock.monotonic()
    now3 = time.monotonic()
    assert now1 <= now2
    assert now2 <= now3


def test_non_realtime_clock():
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
    assert _almost_equal((now2 - now1) * 0.25, real_elapsed)
    assert _almost_equal((mono2 - mono1) * 0.25, real_elapsed)


def test_clock_with_start_time():
    """Clock with explicit start time"""
    clock = Clock(1.0, START_TIME)
    time1 = clock.time()
    mono1 = clock.monotonic()
    time.sleep(0.5)
    time2 = clock.time()
    mono2 = clock.monotonic()
    assert _almost_equal(time1, START_TIME)
    assert _almost_equal(time2, START_TIME + 0.5)
    assert _almost_equal(mono2 - mono1, 0.5)


def test_warp_clock():
    clock = Clock(0.0, START_TIME)
    monotonic_start = clock.monotonic()
    assert clock.time() == START_TIME
    time.sleep(0.5)
    assert clock.time() == START_TIME  # WarpClock does not follow wall time

    clock.advance(3.5)
    assert clock.time() == START_TIME + 3.5
    assert clock.monotonic() == monotonic_start + 3.5


def run_with_loop(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        loop = WarpEventLoop(Clock(0.0, START_TIME))
        try:
            loop.run_until_complete(func(*args, **kwargs))
        finally:
            loop.close()

    return wrapper


@contextlib.asynccontextmanager
async def _wsock_reader():
    rsock, wsock = socketpair()
    try:
        reader, writer = await asyncio.open_connection(sock=rsock)
        yield wsock, reader
        writer.close()
    finally:
        wsock.close()
        rsock.close()


async def _record_periodic(period, repeats, events):
    """Wake up periodically and record the time to `events`"""
    for i in range(repeats):
        await asyncio.sleep(period)
        events.append(asyncio.get_event_loop().time())


@run_with_loop
async def test_warp_event_loop_sleep():
    loop = asyncio.get_event_loop()
    assert loop.time() == 0.0
    events = []
    await asyncio.gather(
        _record_periodic(5, 3, events),
        _record_periodic(4, 4, events))
    assert events == [4, 5, 8, 10, 12, 15, 16]


@run_with_loop
async def test_warp_event_loop_socket():
    loop = asyncio.get_event_loop()
    async with _wsock_reader() as (wsock, reader):
        wsock.send(b'somedata')
        assert loop.time() == 0.0
        data = await asyncio.wait_for(reader.read(8), timeout=5)
        assert data == b'somedata'
        # The data was there immediately, so time should not have advanced
        assert loop.time() == 0.0

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.read(8), timeout=5)
        assert loop.time() == 5.0


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


class WarpEventLoopTestCase:
    RATE = 0.0
    START_TIME = 1234567890.0

    @classmethod
    @pytest.fixture
    def event_loop_policy(cls):
        original = asyncio.get_event_loop_policy()
        policy = WarpEventLoopPolicy(original, cls.RATE, cls.START_TIME)
        asyncio.set_event_loop_policy(policy)
        yield policy
        asyncio.set_event_loop_policy(original)

    @classmethod
    @pytest.fixture
    def event_loop(cls, event_loop_policy):
        loop = event_loop_policy.new_event_loop()
        yield loop
        loop.close()
