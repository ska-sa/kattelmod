import asyncio
import time
import threading
import socket
from selectors import DefaultSelector, BaseSelector, SelectorKey
from abc import ABCMeta, abstractmethod
from typing import Union, List, Tuple, Mapping, Any


_FileObject = Union[int, socket.socket]


class AbstractClock(metaclass=ABCMeta):
    """Clock that doesn't necessarily track wall clock time.

    Implementations must be thread-safe because the current time may be
    accessed by the logging system from other threads.
    """

    @abstractmethod
    def time(self) -> float:
        """Get current time in seconds since UNIX epoch"""
        raise NotImplementedError

    @abstractmethod
    def advance(self, delta: float) -> None:
        """Instantly increase the return value of :meth:`time` by `delta`."""
        raise NotImplementedError

    @abstractmethod
    def advanced(self) -> float:
        """Total of all values given to :meth:`advance`."""
        raise NotImplementedError


class RealClock(AbstractClock):
    """Clock that ticks at same rate as real time but possibly offset from it.

    Parameters
    ----------
    start_time : float, optional
        Initial time on the clock. If not specified, defaults to ``time.time()``
        i.e., the clock will report real time.
    """
    def __init__(self, start_time: float = None) -> None:
        self._offset = 0.0 if start_time is None else start_time - time.time()
        self._advanced = 0.0
        self._lock = threading.Lock()

    def time(self) -> float:
        with self._lock:
            return time.time() + self._offset

    def advance(self, delta: float) -> None:
        with self._lock:
            self._offset += delta
            self._advanced += delta

    def advanced(self) -> float:
        with self._lock:
            return self._advanced


class WarpClock:
    """Clock that only changes time when explicitly advanced

    Parameters
    ----------
    start_time : float, optional
        Initial time on the clock. If not specified, defaults to ``time.time()``.
    """
    def __init__(self, start_time: float = None) -> None:
        if start_time is None:
            start_time = time.time()
        self._now = start_time
        self._advanced = 0.0
        self._lock = threading.Lock()

    def time(self) -> float:
        with self._lock:
            return self._now

    def advance(self, delta: float) -> None:
        with self._lock:
            self._now += delta
            self._advanced += delta

    def advanced(self) -> float:
        with self._lock:
            return self._advanced


class WarpSelector(BaseSelector):
    """Selector implementation that never sleeps, instead warping an internal clock.

    It wraps an existing selector so that it can still determine when events
    have occurred. If no selector is given, a default selector is created.
    """
    def __init__(self, clock: AbstractClock, wrapped: BaseSelector = None) -> None:
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
        if timeout > 0:
            self.clock.advance(timeout)
        return self.wrapped.select(timeout=0)

    def close(self) -> None:
        self.wrapped.close()

    def get_map(self) -> Mapping[_FileObject, SelectorKey]:
        return self.wrapped.get_map()


class WarpEventLoop(asyncio.SelectorEventLoop):
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

    def __init__(self, clock: AbstractClock, warp: bool = True, selector: BaseSelector = None):
        if warp:
            selector = WarpSelector(clock, selector)
        super().__init__(selector=selector)
        self.clock = clock

    def time(self) -> float:
        return super().time() + self.clock.advanced()
