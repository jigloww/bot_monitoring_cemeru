"""Read-only browser metrics and telemetry derived from :mod:`event_bus`.

The service is intentionally a passive subscriber.  It never creates or
controls browser resources; callers publish lifecycle events and the service
turns those events into thread-safe counters, timers, rates, and immutable
snapshots.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from threading import RLock
import time
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from .event_bus import BrowserEvent, BrowserEventBus


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass
class MetricCounter:
    """A named integer counter with bounded, non-negative decrements."""

    name: str
    value: int = 0
    _lock: RLock = field(default_factory=RLock, init=False, repr=False, compare=False)

    def increment(self, amount: int = 1) -> int:
        with self._lock:
            self.value += int(amount)
            return self.value

    def decrement(self, amount: int = 1) -> int:
        with self._lock:
            self.value = max(0, self.value - int(amount))
            return self.value

    def set(self, value: int) -> int:
        with self._lock:
            self.value = int(value)
            return self.value

    def snapshot(self) -> int:
        with self._lock:
            return int(self.value)

    @property
    def count(self) -> int:
        return self.snapshot()

    def to_dict(self) -> dict[str, int]:
        return {self.name: self.snapshot()}


@dataclass
class MetricTimer:
    """Timer retaining enough bounded samples for summary statistics."""

    name: str
    max_samples: int = 4096
    _values: deque[float] = field(default_factory=deque, init=False, repr=False, compare=False)
    _total: float = field(default=0.0, init=False, repr=False, compare=False)
    _count: int = field(default=0, init=False, repr=False, compare=False)
    _successes: int = field(default=0, init=False, repr=False, compare=False)
    _failures: int = field(default=0, init=False, repr=False, compare=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.max_samples <= 0:
            raise ValueError("max_samples must be positive")
        self._values = deque(maxlen=int(self.max_samples))

    def record(self, duration: float, *, success: bool | None = None) -> float:
        value = max(0.0, float(duration))
        with self._lock:
            self._values.append(value)
            self._total += value
            self._count += 1
            if success is True:
                self._successes += 1
            elif success is False:
                self._failures += 1
            return value

    def statistics(self, moving_window: int = 20) -> dict[str, float | int]:
        if moving_window <= 0:
            raise ValueError("moving_window must be positive")
        with self._lock:
            values = list(self._values)
            count = self._count
            total = self._total
            successes = self._successes
            failures = self._failures
        moving = values[-moving_window:] if values else []
        return {
            "count": count,
            "average": total / count if count else 0.0,
            "median": float(median(values)) if values else 0.0,
            "minimum": min(values) if values else 0.0,
            "maximum": max(values) if values else 0.0,
            "success_rate": successes / (successes + failures) if successes + failures else 0.0,
            "failure_rate": failures / (successes + failures) if successes + failures else 0.0,
            "moving_average": sum(moving) / len(moving) if moving else 0.0,
        }

    def snapshot(self, moving_window: int = 20) -> dict[str, float | int]:
        return self.statistics(moving_window)

    @property
    def count(self) -> int:
        return int(self.statistics()["count"])

    @property
    def average(self) -> float:
        return float(self.statistics()["average"])

    @property
    def median(self) -> float:
        return float(self.statistics()["median"])

    @property
    def minimum(self) -> float:
        return float(self.statistics()["minimum"])

    @property
    def maximum(self) -> float:
        return float(self.statistics()["maximum"])

    @property
    def success_rate(self) -> float:
        return float(self.statistics()["success_rate"])

    @property
    def failure_rate(self) -> float:
        return float(self.statistics()["failure_rate"])

    @property
    def moving_average(self) -> float:
        return float(self.statistics()["moving_average"])

    def to_dict(self, moving_window: int = 20) -> dict[str, float | int]:
        return self.statistics(moving_window)


@dataclass(frozen=True)
class MetricsSnapshot:
    timestamp: str
    counters: Mapping[str, int]
    timers: Mapping[str, Mapping[str, float | int]]
    rates: Mapping[str, float]
    service_uptime: float
    last_update: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "counters": _thaw(self.counters),
            "timers": _thaw(self.timers),
            "rates": _thaw(self.rates),
            "service_uptime": round(max(0.0, self.service_uptime), 6),
            "last_update": self.last_update,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


@dataclass(frozen=True)
class MetricsStatistics:
    timestamp: str
    counters: Mapping[str, int]
    timers: Mapping[str, Mapping[str, float | int]]
    rates: Mapping[str, float]
    moving_averages: Mapping[str, float]
    service_uptime: float
    last_update: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "counters": _thaw(self.counters),
            "timers": _thaw(self.timers),
            "rates": _thaw(self.rates),
            "moving_averages": _thaw(self.moving_averages),
            "service_uptime": round(max(0.0, self.service_uptime), 6),
            "last_update": self.last_update,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


class BrowserMetricsService:
    """Passively aggregate events from one :class:`BrowserEventBus`."""

    _SUPPORTED_EVENTS = (
        "BrowserCreated",
        "BrowserClosed",
        "BrowserRestarted",
        "ContextCreated",
        "ContextClosed",
        "PageCreated",
        "PageClosed",
        "NavigationStarted",
        "NavigationFinished",
        "NavigationFailed",
        "HealthChanged",
        "SessionAcquired",
        "SessionReleased",
        "Heartbeat",
        "CrashDetected",
    )

    def __init__(
        self,
        event_bus: BrowserEventBus,
        *,
        moving_average_window: int = 20,
        max_timer_samples: int = 4096,
        clock: Callable[[], float] | None = None,
        timestamp_factory: Callable[[], str] | None = None,
        auto_start: bool = True,
    ) -> None:
        if not isinstance(event_bus, BrowserEventBus):
            raise TypeError("event_bus must be a BrowserEventBus")
        if moving_average_window <= 0:
            raise ValueError("moving_average_window must be positive")
        if max_timer_samples <= 0:
            raise ValueError("max_timer_samples must be positive")
        self.event_bus = event_bus
        self.moving_average_window = int(moving_average_window)
        self.max_timer_samples = int(max_timer_samples)
        self._clock = clock or time.monotonic
        self._timestamp_factory = timestamp_factory or _iso_now
        self._started_at = self._clock()
        self._last_update: str | None = None
        self._counters: dict[str, MetricCounter] = {}
        self._timers: dict[str, MetricTimer] = {}
        self._browser_starts: dict[str, float] = {}
        self._navigation_starts: dict[str, float] = {}
        self._session_starts: dict[str, float] = {}
        self._listener: Any = None
        self._running = False
        self._shutdown = False
        self._lock = RLock()
        self._ensure_metrics()
        if auto_start:
            self.start()

    def _ensure_metrics(self) -> None:
        counter_names = (
            "browser_count",
            "browser_restart_count",
            "browser_crash_count",
            "session_created",
            "session_released",
            "session_reused",
            "contexts_created",
            "contexts_closed",
            "pages_created",
            "pages_closed",
            "navigation_started",
            "navigation_finished",
            "navigation_failed",
            "healthy_events",
            "warning_events",
            "critical_events",
            "heartbeat_count",
            "pool_acquire",
            "pool_release",
            "events_received",
            "events_processed",
        )
        timer_names = (
            "browser_uptime",
            "session_lifetime",
            "navigation_time",
            "listener_latency",
            "dispatch_latency",
        )
        for name in counter_names:
            self._counters.setdefault(name, MetricCounter(name))
        for name in timer_names:
            self._timers.setdefault(name, MetricTimer(name, max_samples=self.max_timer_samples))

    def start(self) -> bool:
        """Subscribe once; repeated calls are harmless."""
        with self._lock:
            if self._shutdown:
                return False
            if self._running and self._listener is not None:
                return True
            try:
                self._listener = self.event_bus.subscribe(self._on_event, priority=0)
            except Exception:
                # A bus that is already shut down is a valid degraded state;
                # callers can inspect is_running() without construction
                # raising an unrelated infrastructure exception.
                self._listener = None
                self._running = False
                return False
            self._running = True
            return True

    def stop(self) -> bool:
        """Stop consuming events without changing accumulated metrics."""
        with self._lock:
            if not self._running:
                return False
            listener = self._listener
            self._listener = None
            self._running = False
        if listener is not None:
            self.event_bus.unsubscribe(listener)
        return True

    def shutdown(self) -> None:
        """Permanently stop collection; this method is idempotent."""
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
        self.stop()

    def is_running(self) -> bool:
        with self._lock:
            return self._running and not self._shutdown

    def _counter(self, name: str) -> MetricCounter:
        return self._counters[name]

    def _timer(self, name: str) -> MetricTimer:
        return self._timers[name]

    @staticmethod
    def _payload(event: BrowserEvent) -> Mapping[str, Any]:
        return event.payload if isinstance(event.payload, Mapping) else {}

    @staticmethod
    def _number(payload: Mapping[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _identifier(payload: Mapping[str, Any], default: str) -> str:
        for key in ("id", "browser_id", "session_id", "page_id", "request_id", "navigation_id"):
            value = payload.get(key)
            if value is not None:
                return str(value)
        return default

    def _duration(self, payload: Mapping[str, Any], *keys: str) -> float | None:
        value = self._number(payload, *keys, "duration_ms", "duration", "elapsed_ms", "elapsed", "latency_ms", "latency")
        return value if value is None else max(0.0, value)

    def _on_event(self, event: BrowserEvent) -> None:
        started = self._clock()
        with self._lock:
            if not self._running or self._shutdown:
                return
            self._counter("events_received").increment()
            try:
                self._process_event_locked(event)
            except Exception:
                # Telemetry must never break event dispatch when a publisher
                # sends an unexpected payload shape.
                self._counter("critical_events").increment()
            self._counter("events_processed").increment()
            self._last_update = self._timestamp_factory()
        elapsed_ms = max(0.0, (self._clock() - started) * 1000.0)
        with self._lock:
            self._timer("listener_latency").record(elapsed_ms)
            payload = self._payload(event)
            dispatch_ms = self._duration(payload, "dispatch_latency_ms", "dispatch_latency", "dispatch_time_ms", "dispatch_time")
            self._timer("dispatch_latency").record(dispatch_ms if dispatch_ms is not None else elapsed_ms)

    def _process_event_locked(self, event: BrowserEvent) -> None:
        event_type = event.event_type
        payload = self._payload(event)
        now = self._clock()
        identifier = self._identifier(payload, event.source)
        if event_type == "BrowserCreated":
            self._counter("browser_count").increment()
            self._browser_starts[identifier] = now
        elif event_type == "BrowserClosed":
            self._counter("browser_count").decrement()
            duration = self._duration(payload, "browser_uptime_ms", "uptime_ms")
            started_at = self._browser_starts.pop(identifier, None)
            if duration is None and started_at is not None:
                duration = max(0.0, (now - started_at) * 1000.0)
            if duration is not None:
                self._timer("browser_uptime").record(duration)
        elif event_type == "BrowserRestarted":
            self._counter("browser_restart_count").increment()
            self._browser_starts[identifier] = now
        elif event_type == "CrashDetected":
            self._counter("browser_crash_count").increment()
        elif event_type == "ContextCreated":
            self._counter("contexts_created").increment()
        elif event_type == "ContextClosed":
            self._counter("contexts_closed").increment()
        elif event_type == "PageCreated":
            self._counter("pages_created").increment()
        elif event_type == "PageClosed":
            self._counter("pages_closed").increment()
        elif event_type == "NavigationStarted":
            self._counter("navigation_started").increment()
            self._navigation_starts[identifier] = now
        elif event_type in {"NavigationFinished", "NavigationFailed"}:
            success = event_type == "NavigationFinished"
            self._counter("navigation_finished" if success else "navigation_failed").increment()
            duration = self._duration(payload, "navigation_time_ms", "load_time_ms")
            started_at = self._navigation_starts.pop(identifier, None)
            if duration is None and started_at is not None:
                duration = max(0.0, (now - started_at) * 1000.0)
            if duration is not None:
                self._timer("navigation_time").record(duration, success=success)
        elif event_type == "HealthChanged":
            status = str(payload.get("status", "")).upper()
            severity = str(event.severity).upper()
            if status in {"HEALTHY", "RUNNING", "READY"}:
                self._counter("healthy_events").increment()
            elif status in {"WARNING", "DEGRADED"} or severity == "WARNING":
                self._counter("warning_events").increment()
            elif status in {"CRITICAL", "FAILED"} or severity in {"ERROR", "CRITICAL"}:
                self._counter("critical_events").increment()
            elif severity in {"TRACE", "DEBUG", "INFO"}:
                self._counter("healthy_events").increment()
        elif event_type == "SessionAcquired":
            self._counter("pool_acquire").increment()
            self._counter("session_created").increment() if bool(payload.get("created")) else None
            if bool(payload.get("reused")):
                self._counter("session_reused").increment()
            self._session_starts[identifier] = now
        elif event_type == "SessionReleased":
            self._counter("pool_release").increment()
            self._counter("session_released").increment()
            duration = self._duration(payload, "session_lifetime_ms", "lifetime_ms")
            started_at = self._session_starts.pop(identifier, None)
            if duration is None and started_at is not None:
                duration = max(0.0, (now - started_at) * 1000.0)
            if duration is not None:
                self._timer("session_lifetime").record(duration)
        elif event_type == "Heartbeat":
            self._counter("heartbeat_count").increment()

    def _counter_values_locked(self) -> dict[str, int]:
        return {name: counter.snapshot() for name, counter in sorted(self._counters.items())}

    def _timer_values_locked(self) -> dict[str, dict[str, float | int]]:
        return {
            name: self._timers[name].statistics(self.moving_average_window)
            for name in sorted(self._timers)
        }

    def _rates_locked(self, counters: Mapping[str, int], timers: Mapping[str, Mapping[str, float | int]]) -> dict[str, float]:
        navigation_total = counters["navigation_finished"] + counters["navigation_failed"]
        pool_total = counters["pool_acquire"]
        return {
            "navigation_success_rate": counters["navigation_finished"] / navigation_total if navigation_total else 0.0,
            "navigation_failure_rate": counters["navigation_failed"] / navigation_total if navigation_total else 0.0,
            "pool_reuse_rate": counters["session_reused"] / pool_total if pool_total else 0.0,
            "average_navigation_time": float(timers["navigation_time"]["average"]),
            "service_uptime": max(0.0, self._clock() - self._started_at),
        }

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            counters = _freeze(self._counter_values_locked())
            timers = _freeze(self._timer_values_locked())
            rates = _freeze(self._rates_locked(_thaw(counters), _thaw(timers)))
            return MetricsSnapshot(
                timestamp=self._timestamp_factory(),
                counters=counters,
                timers=timers,
                rates=rates,
                service_uptime=float(rates["service_uptime"]),
                last_update=self._last_update,
            )

    def statistics(self) -> MetricsStatistics:
        with self._lock:
            counters_dict = self._counter_values_locked()
            timers_dict = self._timer_values_locked()
            rates_dict = self._rates_locked(counters_dict, timers_dict)
            moving = {
                name: float(values["moving_average"])
                for name, values in timers_dict.items()
            }
            return MetricsStatistics(
                timestamp=self._timestamp_factory(),
                counters=_freeze(counters_dict),
                timers=_freeze(timers_dict),
                rates=_freeze(rates_dict),
                moving_averages=_freeze(moving),
                service_uptime=float(rates_dict["service_uptime"]),
                last_update=self._last_update,
            )

    def counter(self, name: str) -> MetricCounter:
        with self._lock:
            if name not in self._counters:
                raise KeyError(name)
            return self._counters[name]

    def timer(self, name: str) -> MetricTimer:
        with self._lock:
            if name not in self._timers:
                raise KeyError(name)
            return self._timers[name]


__all__ = [
    "BrowserMetricsService",
    "MetricCounter",
    "MetricTimer",
    "MetricsSnapshot",
    "MetricsStatistics",
]
