import time
import threading

from katpoint import Timestamp


class RealClock(object):
    """Real time source, with support for a time offset."""
    def __init__(self, start_time=None):
        self.offset = 0.0 if start_time is None else \
                      Timestamp(start_time).secs - time.time()
    def time(self):
        return time.time() + self.offset
    def sleep(self, seconds):
        time.sleep(seconds)


class FakeClock(object):
    """Fake time source, mimicking the time module."""
    def __init__(self, start_time=None):
        self.timestamp = Timestamp(start_time).secs
    def time(self):
        return self.timestamp
    def sleep(self, seconds):
        self.timestamp += seconds


class Sleeper(object):
    """A point where one thread sleeps, to be awoken by another thread."""
    def __init__(self, seconds):
        self.awake = threading.Event()
        self.seconds_left = seconds

    def sleep(self):
        self.awake.wait(self.seconds_left)

    def wake_up(self):
        self.awake.set()


class Dormitory(object):
    """A collection of Sleepers."""
    def __init__(self):
        self.beds = []
        self.bed_lock = threading.Lock()

    def sleep(self, seconds):
        sleeper = Sleeper(seconds)
        with self.bed_lock:
            self.beds.append(sleeper)
        sleeper.sleep()

    def run(self, seconds):
        with self.bed_lock:
            for sleeper in self.beds:
                sleeper.seconds_left -= seconds
                if sleeper.seconds_left <= 0.0:
                    sleeper.wake_up()
            # Make the beds
            self.beds = [s for s in self.beds if not s.awake.isSet()]


class PeriodicUpdateThread(threading.Thread):
    """Thread which periodically updates a group of components."""
    def __init__(self, components, dry_run=False, start_time=None, period=0.1):
        threading.Thread.__init__(self)
        self.name = 'UpdateThread'
        self.components = components
        self.period = period
        self.clock = FakeClock(start_time) if dry_run else RealClock(start_time)
        self.last_update = None
        self.dorm = Dormitory()
        self._thread_active = True

    def run(self):
        while self._thread_active:
            timestamp = self.clock.time()
            for component in self.components:
                component.update(timestamp)
            self.last_update = timestamp
            remaining_time = self.period - (self.clock.time() - timestamp)
            # if remaining_time < 0:
            #     logger.warn("Update thread is struggling: updates take longer than a period")
            self.clock.sleep(remaining_time if remaining_time > 0 else 0)
            self.dorm.run(self.period)

    def stop(self):
        self._thread_active = False

    def time(self):
        """Current time in UTC seconds since Unix epoch."""
        return self.clock.time()

    def sleep(self, seconds):
        """Sleep for the requested duration in seconds."""
        self.dorm.sleep(seconds)