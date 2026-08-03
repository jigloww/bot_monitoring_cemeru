"""Thread-safe, synchronous event bus for browser infrastructure.

The event bus deliberately knows nothing about browsers, Playwright, or any
of the lifecycle components that publish events.  It only stores immutable
events and dispatches them to isolated listeners in a deterministic order.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
import time
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping


class BrowserEventType(str, Enum):
    BrowserCreated = "BrowserCreated"
    BrowserClosed = "BrowserClosed"
    BrowserDisconnected = "BrowserDisconnected"
    BrowserRestarted = "BrowserRestarted"
    ContextCreated = "ContextCreated"
    ContextClosed = "ContextClosed"
    PageCreated = "PageCreated"
    PageClosed = "PageClosed"
    NavigationStarted = "NavigationStarted"
    NavigationFinished = "NavigationFinished"
    NavigationFailed = "NavigationFailed"
    HealthChanged = "HealthChanged"
    Heartbeat = "Heartbeat"
    SessionAcquired = "SessionAcquired"
    SessionReleased = "SessionReleased"
    PoolCreated = "PoolCreated"
    PoolShutdown = "PoolShutdown"
    CrashDetected = "CrashDetected"
    Unknown = "Unknown"


class EventSeverity(str, Enum):
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# Short aliases keep integrations ergonomic while the explicit names remain
# the canonical public API.
EventType = BrowserEventType
Severity = EventSeverity


EventCallback = Callable[["BrowserEvent"], Any]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_type_value(value: BrowserEventType | str | None) -> tuple[str, str | None]:
    """Return a supported event type and an optional original value."""
    if isinstance(value, BrowserEventType):
        return value.value, None
    candidate = str(value or BrowserEventType.Unknown.value)
    supported = {item.value for item in BrowserEventType}
    if candidate in supported:
        return candidate, None
    return BrowserEventType.Unknown.value, candidate


def _severity_value(value: EventSeverity | str | None) -> str:
    if isinstance(value, EventSeverity):
        return value.value
    candidate = str(value or EventSeverity.INFO.value).upper()
    try:
        return EventSeverity(candidate).value
    except ValueError:
        return EventSeverity.INFO.value


def _freeze(value: Any) -> Any:
    """Recursively freeze common payload containers for immutable events."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class BrowserEvent:
    """An immutable event envelope published by infrastructure components."""

    event_id: str
    timestamp: str
    event_type: str
    source: str
    severity: str
    payload: Any
    sequence_number: int

    def __post_init__(self) -> None:
        normalized_type, _original = _event_type_value(self.event_type)
        object.__setattr__(self, "event_id", str(self.event_id))
        object.__setattr__(self, "timestamp", str(self.timestamp))
        object.__setattr__(self, "event_type", normalized_type)
        object.__setattr__(self, "source", str(self.source))
        object.__setattr__(self, "severity", _severity_value(self.severity))
        object.__setattr__(self, "sequence_number", int(self.sequence_number))
        object.__setattr__(self, "payload", _freeze(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "source": self.source,
            "severity": self.severity,
            "payload": _thaw(self.payload),
            "sequence_number": self.sequence_number,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


@dataclass(frozen=True)
class EventListener:
    """Immutable listener registration returned by :meth:`subscribe`."""

    listener_id: str
    callback: EventCallback = field(compare=False, repr=False)
    event_types: tuple[str, ...] = ()
    priority: int = 0
    registration_order: int = 0

    @property
    def id(self) -> str:
        return self.listener_id

    def accepts(self, event_type: str) -> bool:
        return not self.event_types or event_type in self.event_types

    def to_dict(self) -> dict[str, Any]:
        return {
            "listener_id": self.listener_id,
            "event_types": list(self.event_types),
            "priority": self.priority,
            "registration_order": self.registration_order,
        }


@dataclass(frozen=True)
class EventSnapshot:
    timestamp: str
    queue_size: int
    listener_count: int
    events_emitted: int
    events_processed: int
    events_failed: int
    events_dropped: int
    last_event: BrowserEvent | None
    uptime: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "queue_size": self.queue_size,
            "listener_count": self.listener_count,
            "events_emitted": self.events_emitted,
            "events_processed": self.events_processed,
            "events_failed": self.events_failed,
            "events_dropped": self.events_dropped,
            "last_event": self.last_event.to_dict() if self.last_event else None,
            "uptime": round(max(0.0, self.uptime), 6),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


@dataclass(frozen=True)
class EventStatistics:
    events_emitted: int
    events_processed: int
    events_failed: int
    events_dropped: int
    listeners_registered: int
    listener_errors: int
    average_dispatch_time: float
    peak_queue_size: int
    uptime: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "events_emitted": self.events_emitted,
            "events_processed": self.events_processed,
            "events_failed": self.events_failed,
            "events_dropped": self.events_dropped,
            "listeners_registered": self.listeners_registered,
            "listener_errors": self.listener_errors,
            "average_dispatch_time": round(max(0.0, self.average_dispatch_time), 9),
            "peak_queue_size": self.peak_queue_size,
            "uptime": round(max(0.0, self.uptime), 6),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


class BrowserEventBus:
    """Synchronous FIFO event bus with isolated, priority-ordered listeners."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        timestamp_factory: Callable[[], str] | None = None,
        max_queue_size: int | None = None,
    ) -> None:
        if max_queue_size is not None and max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive when provided")
        self._clock = clock or time.monotonic
        self._timestamp_factory = timestamp_factory or _iso_now
        self.max_queue_size = max_queue_size
        self._started_at = self._clock()
        self._queue: deque[BrowserEvent] = deque()
        self._listeners: dict[str, EventListener] = {}
        self._next_listener_number = 1
        self._next_sequence = 1
        self._events_emitted = 0
        self._events_processed = 0
        self._events_failed = 0
        self._events_dropped = 0
        self._listeners_registered = 0
        self._listener_errors = 0
        self._dispatch_time_total = 0.0
        self._peak_queue_size = 0
        self._last_event: BrowserEvent | None = None
        self._shutdown = False
        self._lock = RLock()

    def subscribe(
        self,
        listener: EventCallback | BrowserEventType | str,
        callback: EventCallback | None = None,
        *,
        event_types: Iterable[BrowserEventType | str] | BrowserEventType | str | None = None,
        priority: int = 0,
    ) -> EventListener:
        """Register a callback. Higher priorities run first; ties are FIFO."""
        # Also accept the common ``subscribe(event_type, callback)`` form.
        if callback is not None:
            if not isinstance(listener, (str, BrowserEventType)):
                raise TypeError("event type must be a string or BrowserEventType")
            event_types = (listener,)
            listener = callback
        if not callable(listener):
            raise TypeError("listener must be callable")
        if isinstance(event_types, (str, BrowserEventType)):
            event_types = (event_types,)
        normalized: list[str] = []
        for item in event_types or ():
            value, _original = _event_type_value(item)
            if value not in normalized:
                normalized.append(value)
        with self._lock:
            if self._shutdown:
                raise RuntimeError("event bus is shut down")
            number = self._next_listener_number
            self._next_listener_number += 1
            registration = EventListener(
                listener_id=f"listener-{number:06d}",
                callback=listener,
                event_types=tuple(normalized),
                priority=int(priority),
                registration_order=number,
            )
            self._listeners[registration.listener_id] = registration
            self._listeners_registered += 1
            return registration

    def unsubscribe(self, listener: EventListener | str | EventCallback) -> bool:
        """Remove a registration by object, token, ID, or callback."""
        with self._lock:
            target_id: str | None = None
            if isinstance(listener, EventListener):
                target_id = listener.listener_id
            elif isinstance(listener, str):
                target_id = listener
            else:
                for item in self._listeners.values():
                    if item.callback is listener:
                        target_id = item.listener_id
                        break
            if target_id is None or target_id not in self._listeners:
                return False
            del self._listeners[target_id]
            return True

    def emit(
        self,
        event_type: BrowserEventType | str | BrowserEvent,
        *,
        source: str = "unknown",
        severity: EventSeverity | str = EventSeverity.INFO,
        payload: Any = None,
    ) -> BrowserEvent | None:
        """Enqueue an event without invoking listeners."""
        with self._lock:
            if self._shutdown:
                self._events_dropped += 1
                return None
            if isinstance(event_type, BrowserEvent):
                event = event_type
                self._next_sequence = max(self._next_sequence, event.sequence_number + 1)
                if self.max_queue_size is not None and len(self._queue) >= self.max_queue_size:
                    self._queue.popleft()
                    self._events_dropped += 1
                self._queue.append(event)
                self._events_emitted += 1
                self._peak_queue_size = max(self._peak_queue_size, len(self._queue))
                return event
            normalized_type, original_type = _event_type_value(event_type)
            normalized_payload: Any = {} if payload is None else payload
            if original_type is not None:
                if isinstance(normalized_payload, Mapping):
                    normalized_payload = dict(normalized_payload)
                    normalized_payload.setdefault("original_event_type", original_type)
                else:
                    normalized_payload = {"value": normalized_payload, "original_event_type": original_type}
            sequence = self._next_sequence
            self._next_sequence += 1
            event = BrowserEvent(
                event_id=f"event-{sequence:08d}",
                timestamp=self._timestamp_factory(),
                event_type=normalized_type,
                source=str(source),
                severity=_severity_value(severity),
                payload=normalized_payload,
                sequence_number=sequence,
            )
            if self.max_queue_size is not None and len(self._queue) >= self.max_queue_size:
                self._queue.popleft()
                self._events_dropped += 1
            self._queue.append(event)
            self._events_emitted += 1
            self._peak_queue_size = max(self._peak_queue_size, len(self._queue))
            return event

    def dispatch(self, limit: int | None = None) -> int:
        """Dispatch queued events in FIFO order and return processed count."""
        if limit is not None and limit < 0:
            raise ValueError("limit cannot be negative")
        processed = 0
        while limit is None or processed < limit:
            with self._lock:
                if not self._queue:
                    break
                event = self._queue.popleft()
                listeners = tuple(
                    sorted(
                        (item for item in self._listeners.values() if item.accepts(event.event_type)),
                        key=lambda item: (-item.priority, item.registration_order),
                    )
                )
            started = self._clock()
            event_failed = False
            for registration in listeners:
                try:
                    registration.callback(event)
                except Exception:
                    event_failed = True
                    with self._lock:
                        self._listener_errors += 1
            elapsed = max(0.0, self._clock() - started)
            with self._lock:
                self._events_processed += 1
                if event_failed:
                    self._events_failed += 1
                self._dispatch_time_total += elapsed
                self._last_event = event
            processed += 1
        return processed

    def clear(self) -> int:
        """Drop all queued events and return the number removed."""
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            self._events_dropped += count
            return count

    def listeners(self) -> tuple[EventListener, ...]:
        with self._lock:
            return tuple(sorted(self._listeners.values(), key=lambda item: (-item.priority, item.registration_order)))

    def snapshot(self) -> EventSnapshot:
        with self._lock:
            return EventSnapshot(
                timestamp=self._timestamp_factory(),
                queue_size=len(self._queue),
                listener_count=len(self._listeners),
                events_emitted=self._events_emitted,
                events_processed=self._events_processed,
                events_failed=self._events_failed,
                events_dropped=self._events_dropped,
                last_event=self._last_event,
                uptime=max(0.0, self._clock() - self._started_at),
            )

    def statistics(self) -> EventStatistics:
        with self._lock:
            average = self._dispatch_time_total / self._events_processed if self._events_processed else 0.0
            return EventStatistics(
                events_emitted=self._events_emitted,
                events_processed=self._events_processed,
                events_failed=self._events_failed,
                events_dropped=self._events_dropped,
                listeners_registered=self._listeners_registered,
                listener_errors=self._listener_errors,
                average_dispatch_time=average,
                peak_queue_size=self._peak_queue_size,
                uptime=max(0.0, self._clock() - self._started_at),
            )

    def shutdown(self) -> None:
        """Make the bus inert; repeated calls are safe."""
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._events_dropped += len(self._queue)
            self._queue.clear()
            self._listeners.clear()

    def __enter__(self) -> "BrowserEventBus":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.shutdown()


__all__ = [
    "BrowserEvent",
    "BrowserEventBus",
    "BrowserEventType",
    "EventType",
    "EventListener",
    "EventSeverity",
    "Severity",
    "EventSnapshot",
    "EventStatistics",
]
