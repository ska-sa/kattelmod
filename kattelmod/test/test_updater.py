import asyncio
import logging
from typing import Union

import asynctest

from kattelmod.clock import Clock, WarpEventLoop
from kattelmod.updater import PeriodicUpdater
from kattelmod.component import TelstateUpdatingComponent


class WarpEventLoopPolicy(asyncio.AbstractEventLoopPolicy):
    def __init__(self, original: asyncio.AbstractEventLoopPolicy) -> None:
        self.original = original

    def get_event_loop(self) -> asyncio.AbstractEventLoop:
        return self.original.get_event_loop()

    def set_event_loop(self, loop) -> None:
        self.original.set_event_loop(loop)

    def new_event_loop(self) -> asyncio.AbstractEventLoop:
        return WarpEventLoop(Clock(0.0, 123456789.0))


class DummyComponent(TelstateUpdatingComponent):
    def __init__(self, consume: float = 0.0) -> None:
        super().__init__()
        self._updates = []
        self._consume = consume

    def _update(self, timestamp: float) -> None:
        self._updates.append(timestamp)
        self._clock.advance(self._consume)


class TestPeriodicUpdater(asynctest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Make asynctest create a WarpEventLoop
        policy = WarpEventLoopPolicy(asyncio.get_event_loop_policy())
        asyncio.set_event_loop_policy(policy)

    @classmethod
    def tearDownClass(cls) -> None:
        policy = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(policy.original)

    async def test_periodic(self) -> None:
        comp = DummyComponent()
        await comp._start()
        async with PeriodicUpdater([comp], clock=self.loop.clock, period=2.0):
            await asyncio.sleep(7)
            self.assertEqual(comp._updates, [123456789.0, 123456791.0, 123456793.0, 123456795.0])
            self.assertEqual(comp._clock, self.loop.clock)
        await comp._stop()

    def _condition(self) -> Union[float, bool]:
        now = self.loop.clock.time()
        if now >= 123456794.0:
            return now
        else:
            return False

    async def test_condition(self) -> None:
        async with PeriodicUpdater([], clock=self.loop.clock, period=2.0) as updater:
            future = self.loop.create_future()
            updater.add_condition(self._condition, future)
            await asyncio.sleep(2)
            self.assertFalse(future.done())
            await asyncio.sleep(100)
            self.assertTrue(future.done())
            self.assertEqual(await future, 123456795.0)

    async def test_cancel_condition(self) -> None:
        async with PeriodicUpdater([], clock=self.loop.clock, period=2.0) as updater:
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
        async with PeriodicUpdater([], clock=self.loop.clock, period=2.0) as updater:
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
            async with PeriodicUpdater([comp1, comp2], clock=self.loop.clock, period=1.5):
                await asyncio.sleep(6.5)
        self.assertRegex(cm.output[0], 'Update thread is struggling')
        expected = [123456789.0, 123456791.0, 123456793.0, 123456795.0]
        # The timestamp given for the update is unaffected by the time spent
        # inside the updates, so both components should see the same
        # timestamps.
        self.assertEqual(comp1._updates, expected)
        self.assertEqual(comp2._updates, expected)
