import asyncio
import asyncio.unix_events
import time
import threading
import socket
from selectors import DefaultSelector, BaseSelector, SelectorKey
from typing import Union, List, Tuple, Mapping, Any


_FileObject = Union[int, socket.socket]


class Clock:
    """Clock that doesn't necessarily track wall clock time.

    It can be discontinuously advanced in time, and it can run at a different
    rate than real time (including zero, meaning that time only changes when
    jumped).

    It is thread-safe because the current time may be accessed by the logging
    system from other threads.

    Parameters
    ----------
    rate
        Amount of real time it takes for a second to pass on this clock.
        Zero is allowed but is treated specially: the user must call
        :meth:`advance` to update the simulated time.
    start_time
        UNIX epoch time reported initially
    """
    def __new__(cls, rate: float = 1.0, start_time: float = None) -> 'Clock':
        if rate == 0.0:
            return super().__new__(_WarpClock)
        else:
            return super().__new__(cls)

    def __init__(self, rate: float = 1.0, start_time: float = None) -> None:
        now = time.time()
        if start_time is None:
            start_time = now
        self._lock = threading.Lock()
        self._rate = rate
        # Ensure now / self._rate + self._bias == start_time
        self._bias = start_time - now / self._rate

    def time(self) -> float:
        """Get current time in seconds since UNIX epoch"""
        with self._lock:
            return time.time() / self._rate + self._bias

    def monotonic(self) -> float:
        """Equivalent to time.monotonic() for this clock"""
        with self._lock:
            return time.monotonic() / self._rate

    @property
    def rate(self) -> float:
        """Seconds of real time that pass per simulated second"""
        return self._rate

    def advance(self, delta: float) -> None:
        """Instantly increase the return value of :meth:`time` by `delta`.

        This may only be called if `rate` is zero.
        """
        raise TypeError('Cannot advance clock with non-zero rate')


class _WarpClock(Clock):
    """Implementation :class:`Clock` for zero rate.

    It is made into a separate class because most of the implementation
    details are somewhat different.
    """
    def __init__(self, rate: float = 0.0, start_time: float = None) -> None:
        if start_time is None:
            start_time = time.time()
        self._lock = threading.Lock()
        self._start_time = start_time
        self._advanced = 0.0

    def time(self) -> float:
        """Get current time in seconds since UNIX epoch"""
        with self._lock:
            return self._start_time + self._advanced

    def monotonic(self) -> float:
        """Equivalent to time.monotonic() for this clock"""
        with self._lock:
            return self._advanced

    @property
    def rate(self) -> float:
        """Seconds of real time that pass per simulated second"""
        return 0.0

    def advance(self, delta: float) -> None:
        """Instantly increase the return value of :meth:`time` by `delta`."""
        with self._lock:
            self._advanced += delta


class WarpSelector(BaseSelector):
    """Selector implementation that never sleeps, instead warping an internal clock.

    It wraps an existing selector so that it can still determine when events
    have occurred. If no selector is given, a default selector is created.
    """
    def __init__(self, clock: Clock, wrapped: BaseSelector = None) -> None:
        self.wrapped = wrapped if wrapped is not None else DefaultSelector()
        self.clock = clock

    def register(self, fileobj: _FileObject, events: int, data: Any = None) -> SelectorKey:
        return self.wrapped.register(fileobj, events, data)

    def unregister(self, fileobj: _FileObject) -> SelectorKey:
        return self.wrapped.unregister(fileobj)

    def modify(self, fileobj: _FileObject, events: int, data: Any = None) -> SelectorKey:
        return self.wrapped.modify(fileobj, events, data)

    def select(self, timeout: float = None) -> List[Tuple[SelectorKey, int]]:
        if timeout is None:
            raise ValueError('WarpSelector does not support infinite timeout')
        events = self.wrapped.select(timeout=timeout * self.clock.rate)
        if isinstance(self.clock, _WarpClock) and not events and timeout > 0:
            # If events is non-empty, there was a file handle already ready to
            # work on, so a "real" system would not sleep.
            self.clock.advance(timeout)
        return events

    def close(self) -> None:
        self.wrapped.close()

    def get_map(self) -> Mapping[_FileObject, SelectorKey]:
        return self.wrapped.get_map()


class WarpEventLoop(asyncio.unix_events.SelectorEventLoop):
    """Event loop that supports warping time when sleeping.

    Parameters
    ----------
    clock
        Clock used to construct the selector. It is also stored in the object
        for convenience.
    warp
        If true (default), construct a :class:`WarpSelector` for internal use.
    selector
        Provide a custom base selector. If not given, a default selector is
        created (and then wrapped if `warp` is true).
    """

    def __init__(self, clock: Clock, warp: bool = True, selector: BaseSelector = None):
        if warp:
            selector = WarpSelector(clock, selector)
        super().__init__(selector=selector)
        self.clock = clock

    def time(self) -> float:
        return self.clock.monotonic()


def get_clock() -> Clock:
    """Clock of the current event loop"""
    loop = asyncio.get_event_loop()
    assert isinstance(loop, WarpEventLoop)
    return loop.clock
