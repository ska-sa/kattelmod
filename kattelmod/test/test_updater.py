import asyncio
import logging
from typing import Union, List      # noqa: F401

from kattelmod.clock import get_clock
from kattelmod.updater import PeriodicUpdater
from kattelmod.component import TelstateUpdatingComponent
from kattelmod.test.test_clock import WarpEventLoopTestCase


class DummyComponent(TelstateUpdatingComponent):
    def __init__(self, consume: float = 0.0) -> None:
        super().__init__()
        self._updates = []           # type: List[float]
        self._consume = consume

    def _update(self, timestamp: float) -> None:
        self._updates.append(timestamp)
        get_clock().advance(self._consume)


class TestPeriodicUpdater(WarpEventLoopTestCase):
    async def test_periodic(self) -> None:
        comp = DummyComponent()
        await comp._start()
        async with PeriodicUpdater([comp], period=2.0):
            await asyncio.sleep(7)
            self.assertEqual(comp._updates,
                             [1234567890.0, 1234567892.0, 1234567894.0, 1234567896.0])
        await comp._stop()

    def _condition(self) -> Union[float, bool]:
        now = self.loop.clock.time()
        if now >= 1234567895.0:
            return now
        else:
            return False

    async def test_condition(self) -> None:
        async with PeriodicUpdater([], period=2.0) as updater:
            future = self.loop.create_future()
            updater.add_condition(self._condition, future)
            await asyncio.sleep(2)
            self.assertFalse(future.done())
            await asyncio.sleep(100)
            self.assertTrue(future.done())
            self.assertEqual(await future, 1234567896.0)

    async def test_cancel_condition(self) -> None:
        async with PeriodicUpdater([], period=2.0) as updater:
            future = self.loop.create_future()
            updater.add_condition(self._condition, future)
            await asyncio.sleep(2)
            self.assertFalse(future.done())
            future.cancel()
            await asyncio.sleep(100)
            self.assertTrue(future.done())
            with self.assertRaises(asyncio.CancelledError):
                await future

    async def test_remove_condition(self) -> None:
        async with PeriodicUpdater([], period=2.0) as updater:
            future = self.loop.create_future()
            updater.add_condition(self._condition, future)
            updater.start()
            await asyncio.sleep(2)
            self.assertFalse(future.done())
            updater.remove_condition(self._condition, future)
            await asyncio.sleep(100)
            self.assertFalse(future.done())

    async def test_slow(self) -> None:
        comp1 = DummyComponent(1.0)
        comp2 = DummyComponent(1.0)
        with self.assertLogs('kattelmod.updater', logging.WARNING) as cm:
            async with PeriodicUpdater([comp1, comp2], period=1.5):
                await asyncio.sleep(6.5)
        self.assertRegex(cm.output[0], 'Update thread is struggling')
        expected = [1234567890.0, 1234567892.0, 1234567894.0, 1234567896.0]
        # The timestamp given for the update is unaffected by the time spent
        # inside the updates, so both components should see the same
        # timestamps.
        self.assertEqual(comp1._updates, expected)
        self.assertEqual(comp2._updates, expected)
