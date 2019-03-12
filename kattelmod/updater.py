import time
import logging
import asyncio


logger = logging.getLogger(__name__)


class PeriodicUpdater:
    """Task which periodically updates a group of components.

    After each update, it can also check conditions and signal futures if
    they are true.
    """
    def __init__(self, components, clock, period=0.1):
        self.components = components
        self.clock = clock
        # This is necessary to provide the correct timestamps for async sets
        for component in components:
            component._clock = clock
        self.period = period
        self._task = None
        self._active = False
        self._checks = set()

    async def __aenter__(self):
        """Enter context."""
        self.start()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        """Exit context and stop the system."""
        self.stop()
        await self.join()
        # Don't suppress exceptions
        return False

    def _check_and_wake(self):
        new_checks = set()
        for (condition, future) in self._checks:
            if not future.done():
                result = condition()
                if result:
                    future.set_result(result)
                else:
                    new_checks.add((condition, future))
        self._checks = new_checks

    async def _run(self):
        try:
            while self._active:
                timestamp = self.clock.time()
                for component in self.components:
                    # Force all sensor updates to happen at the same timestamp
                    component._update_time = timestamp
                    component._update(timestamp)
                    component._update_time = 0.0
                after_update = self.clock.time()
                update_time = after_update - timestamp
                remaining_time = self.period - update_time
                if remaining_time < 0:
                    logger.warn("Update thread is struggling: updates take "
                                "%g seconds but repeat every %g seconds" %
                                (update_time, self.period))
                self._check_and_wake()
                await asyncio.sleep(remaining_time)
        except Exception:
            logger.exception('Exception in updater')
            raise

    def start(self):
        if self._task is not None:
            return
        self._task = asyncio.get_event_loop().create_task(self._run())
        self._active = True

    def stop(self):
        self._active = False

    async def join(self):
        if self._task is not None:
            task = self._task
            self._task = None
            await task

    def add_condition(self, condition, future):
        self._checks.add((condition, future))

    def remove_condition(self, condition, future):
        self._checks.discard((condition, future))
