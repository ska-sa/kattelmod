import asyncio

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
    def __init__(self):
        super().__init__()
        self._updates = []

    def _update(self, timestamp):
        self._updates.append(timestamp)


class TestPeriodicUpdater(asynctest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Make asynctest create a WarpEventLoop
        policy = WarpEventLoopPolicy(asyncio.get_event_loop_policy())
        asyncio.set_event_loop_policy(policy)

    @classmethod
    def tearDownClass(cls):
        policy = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(policy.original)

    async def test_periodic(self):
        comp = DummyComponent()
        await comp._start()
        updater = PeriodicUpdater([comp], clock=self.loop.clock, period=2.0)
        updater.start()
        await asyncio.sleep(7)
        self.assertEqual(comp._updates, [123456789.0, 123456791.0, 123456793.0, 123456795.0])
        self.assertEqual(comp._clock, self.loop.clock)
        updater.stop()
        await updater.join()
        await comp._stop()

    def _condition(self):
        now = self.loop.clock.time()
        if now >= 123456794.0:
            return now
        else:
            return False

    async def test_condition(self):

        updater = PeriodicUpdater([], clock=self.loop.clock, period=2.0)
        future = self.loop.create_future()
        updater.add_condition(self._condition, future)
        updater.start()
        await asyncio.sleep(2)
        self.assertFalse(future.done())
        await asyncio.sleep(100)
        self.assertTrue(future.done())
        self.assertEqual(await future, 123456795.0)

    async def test_cancel_condition(self):
        updater = PeriodicUpdater([], clock=self.loop.clock, period=2.0)
        future = self.loop.create_future()
        updater.add_condition(self._condition, future)
        updater.start()
        await asyncio.sleep(2)
        self.assertFalse(future.done())
        future.cancel()
        await asyncio.sleep(100)
        self.assertTrue(future.done())
        with self.assertRaises(asyncio.CancelledError):
            await future

    async def test_remove_condition(self):
        updater = PeriodicUpdater([], clock=self.loop.clock, period=2.0)
        future = self.loop.create_future()
        updater.add_condition(self._condition, future)
        updater.start()
        await asyncio.sleep(2)
        self.assertFalse(future.done())
        updater.remove_condition(self._condition, future)
        await asyncio.sleep(100)
        self.assertFalse(future.done())
