from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        pass


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock(Clock):
    """Injectable fake clock for time-travel and expiry testing."""

    def __init__(self, initial_time: datetime):
        self._current = initial_time if initial_time.tzinfo else initial_time.replace(tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._current

    def advance(self, delta: timedelta) -> None:
        self._current += delta

    def set_time(self, new_time: datetime) -> None:
        self._current = new_time if new_time.tzinfo else new_time.replace(tzinfo=timezone.utc)


_global_clock: Clock = SystemClock()


def get_clock() -> Clock:
    return _global_clock


def set_global_clock(clock: Clock) -> None:
    global _global_clock
    _global_clock = clock


def reset_global_clock() -> None:
    global _global_clock
    _global_clock = SystemClock()
