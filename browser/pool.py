"""Thread-safe orchestration pool for BrowserSessionManager instances."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from .config import BrowserConfig
from .manager import BrowserSessionManager


class PoolState(str, Enum):
    CREATING = "CREATING"
    READY = "READY"
    BUSY = "BUSY"
    IDLE = "IDLE"
    FAILED = "FAILED"
    REMOVED = "REMOVED"


@dataclass(frozen=True)
class PoolSessionSnapshot:
    session_id: int
    state: PoolState
    acquire_count: int
    age: float
    idle_for: float
    idle_timeout_exceeded: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "acquire_count": self.acquire_count,
            "age": round(max(0.0, self.age), 6),
            "idle_for": round(max(0.0, self.idle_for), 6),
            "idle_timeout_exceeded": self.idle_timeout_exceeded,
            "error": self.error,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


@dataclass(frozen=True)
class PoolStatistics:
    total_sessions_created: int
    active_sessions: int
    idle_sessions: int
    busy_sessions: int
    failed_sessions: int
    peak_sessions: int
    acquire_count: int
    release_count: int
    reuse_rate: float
    average_session_lifetime: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_sessions_created": self.total_sessions_created,
            "active_sessions": self.active_sessions,
            "idle_sessions": self.idle_sessions,
            "busy_sessions": self.busy_sessions,
            "failed_sessions": self.failed_sessions,
            "peak_sessions": self.peak_sessions,
            "acquire_count": self.acquire_count,
            "release_count": self.release_count,
            "reuse_rate": round(max(0.0, min(1.0, self.reuse_rate)), 6),
            "average_session_lifetime": round(max(0.0, self.average_session_lifetime), 6),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


@dataclass(frozen=True)
class PoolSnapshot:
    timestamp: str
    state: PoolState
    max_size: int
    idle_timeout: float
    sessions: tuple[PoolSessionSnapshot, ...]
    statistics: PoolStatistics
    shutdown: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "state": self.state.value,
            "max_size": self.max_size,
            "idle_timeout": self.idle_timeout,
            "sessions": [item.to_dict() for item in self.sessions],
            "statistics": self.statistics.to_dict(),
            "shutdown": self.shutdown,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


@dataclass
class _PoolEntry:
    session_id: int
    manager: Any
    state: PoolState
    created_at: float
    last_acquired: float | None = None
    last_released: float | None = None
    acquire_count: int = 0
    error: str | None = None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BrowserPool:
    """Manage reusable BrowserSessionManager instances without duplicating launch logic."""

    def __init__(
        self,
        *,
        max_size: int = 4,
        idle_timeout: float = 300.0,
        config: BrowserConfig | dict[str, Any] | None = None,
        session_factory: Callable[..., Any] | None = None,
        persistent: bool | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        if idle_timeout < 0:
            raise ValueError("idle_timeout cannot be negative")
        if config is None:
            config = BrowserConfig()
        elif isinstance(config, dict):
            config = BrowserConfig.from_dict(config)
        elif not isinstance(config, BrowserConfig):
            raise TypeError("config must be BrowserConfig, mapping, or None")
        if persistent is not None and bool(config.persistent) != bool(persistent):
            config = BrowserConfig.from_dict({**config.to_dict(), "persistent": bool(persistent)})
        self.max_size = int(max_size)
        self.idle_timeout = float(idle_timeout)
        self.config = config
        self.session_factory = session_factory
        self._clock = clock or time.monotonic
        self._entries: dict[int, _PoolEntry] = {}
        self._removed: list[PoolSessionSnapshot] = []
        self._total_created = 0
        self._failed_creations = 0
        self._next_session_id = 1
        self._peak_sessions = 0
        self._acquire_count = 0
        self._release_count = 0
        self._reused_acquires = 0
        self._lifetime_total = 0.0
        self._lifetime_count = 0
        self._shutdown = False
        self._lock = threading.RLock()

    def _new_manager(self) -> Any:
        if self.session_factory is None:
            return BrowserSessionManager(self.config)
        try:
            return self.session_factory(self.config)
        except TypeError:
            return self.session_factory()

    def _start_manager(self, manager: Any) -> None:
        start = getattr(manager, "start", None)
        if callable(start):
            start()

    def _session_available(self, manager: Any) -> bool:
        health = getattr(manager, "health", None)
        if callable(health):
            try:
                state = health()
                status = getattr(state, "status", state.get("status") if isinstance(state, dict) else None)
                if hasattr(status, "value"):
                    status = status.value
                return str(status) in {"RUNNING", "READY", "HEALTHY"}
            except Exception:
                return False
        running = getattr(manager, "is_running", None)
        if callable(running):
            try:
                return bool(running())
            except Exception:
                return False
        return True

    def _entry_snapshot(self, entry: _PoolEntry, now: float) -> PoolSessionSnapshot:
        idle_reference = entry.last_released or entry.created_at
        return PoolSessionSnapshot(
            session_id=entry.session_id,
            state=entry.state,
            acquire_count=entry.acquire_count,
            age=max(0.0, now - entry.created_at),
            idle_for=max(0.0, now - idle_reference) if entry.state in {PoolState.IDLE, PoolState.READY} else 0.0,
            idle_timeout_exceeded=(entry.state in {PoolState.IDLE, PoolState.READY} and self.idle_timeout > 0 and now - idle_reference >= self.idle_timeout),
            error=entry.error,
        )

    def _statistics_locked(self, now: float | None = None) -> PoolStatistics:
        now = self._clock() if now is None else now
        active = sum(1 for entry in self._entries.values() if entry.state != PoolState.FAILED)
        busy = sum(1 for entry in self._entries.values() if entry.state == PoolState.BUSY)
        idle = sum(1 for entry in self._entries.values() if entry.state in {PoolState.IDLE, PoolState.READY})
        failed = sum(1 for entry in self._entries.values() if entry.state == PoolState.FAILED)
        lifetimes = self._lifetime_total
        lifetime_count = self._lifetime_count
        for entry in self._entries.values():
            lifetimes += max(0.0, now - entry.created_at)
            lifetime_count += 1
        return PoolStatistics(
            total_sessions_created=self._total_created,
            active_sessions=active,
            idle_sessions=idle,
            busy_sessions=busy,
            failed_sessions=failed + self._failed_creations,
            peak_sessions=self._peak_sessions,
            acquire_count=self._acquire_count,
            release_count=self._release_count,
            reuse_rate=(self._reused_acquires / self._acquire_count) if self._acquire_count else 0.0,
            average_session_lifetime=(lifetimes / lifetime_count) if lifetime_count else 0.0,
        )

    def _pool_state_locked(self) -> PoolState:
        if self._shutdown:
            return PoolState.REMOVED
        if not self._entries:
            return PoolState.IDLE
        if all(entry.state == PoolState.FAILED for entry in self._entries.values()):
            return PoolState.FAILED
        if any(entry.state == PoolState.CREATING for entry in self._entries.values()):
            return PoolState.CREATING
        if any(entry.state == PoolState.BUSY for entry in self._entries.values()):
            return PoolState.BUSY
        if any(entry.state == PoolState.READY for entry in self._entries.values()):
            return PoolState.READY
        return PoolState.IDLE

    def create(self) -> Any:
        """Create and start one manager, or return a pool state when unavailable."""
        with self._lock:
            if self._shutdown:
                return PoolState.REMOVED
            if len(self._entries) >= self.max_size:
                return PoolState.BUSY
            try:
                manager = self._new_manager()
            except Exception:
                self._failed_creations += 1
                return PoolState.FAILED
            entry = _PoolEntry(session_id=self._next_session_id, manager=manager, state=PoolState.CREATING, created_at=self._clock())
            self._next_session_id += 1
            self._entries[id(manager)] = entry
            try:
                self._start_manager(manager)
            except Exception as exc:
                entry.state = PoolState.FAILED
                entry.error = str(exc)
                self._failed_creations += 1
                return PoolState.FAILED
            entry.state = PoolState.READY
            self._total_created += 1
            self._peak_sessions = max(self._peak_sessions, len(self._entries))
            return manager

    def acquire(self) -> Any:
        """Return an available manager; return ``PoolState.BUSY`` if capacity is full."""
        with self._lock:
            if self._shutdown:
                return PoolState.REMOVED
            now = self._clock()
            for entry in self._entries.values():
                if entry.state not in {PoolState.READY, PoolState.IDLE}:
                    continue
                if not self._session_available(entry.manager):
                    entry.state = PoolState.FAILED
                    entry.error = "session is not healthy"
                    continue
                if entry.state == PoolState.IDLE:
                    self._reused_acquires += 1
                entry.state = PoolState.BUSY
                entry.last_acquired = now
                entry.acquire_count += 1
                self._acquire_count += 1
                return entry.manager
            if len(self._entries) >= self.max_size:
                return PoolState.BUSY
            manager = self.create()
            if isinstance(manager, PoolState):
                return manager
            entry = self._entries[id(manager)]
            entry.state = PoolState.BUSY
            entry.last_acquired = now
            entry.acquire_count += 1
            self._acquire_count += 1
            return manager

    def release(self, manager: Any) -> bool:
        with self._lock:
            entry = self._entries.get(id(manager))
            if entry is None or entry.manager is not manager:
                return False
            if entry.state != PoolState.BUSY:
                return False
            entry.state = PoolState.IDLE
            entry.last_released = self._clock()
            self._release_count += 1
            return True

    def remove(self, manager: Any) -> bool:
        with self._lock:
            entry = self._entries.pop(id(manager), None)
            if entry is None or entry.manager is not manager:
                return False
            now = self._clock()
            self._lifetime_total += max(0.0, now - entry.created_at)
            self._lifetime_count += 1
            entry.state = PoolState.REMOVED
            self._removed.append(self._entry_snapshot(entry, now))
            shutdown = getattr(manager, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    pass
            return True

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            managers = [entry.manager for entry in self._entries.values()]
            for manager in managers:
                self.remove(manager)

    def snapshot(self) -> PoolSnapshot:
        with self._lock:
            now = self._clock()
            statistics = self._statistics_locked(now)
            # Session IDs are allocated monotonically and provide a stable
            # ordering for serialized snapshots.  Object identity is process
            # dependent and would make otherwise identical reports differ.
            sessions = tuple(
                self._entry_snapshot(entry, now)
                for entry in sorted(self._entries.values(), key=lambda item: item.session_id)
            )
            return PoolSnapshot(
                timestamp=_iso_now(),
                state=self._pool_state_locked(),
                max_size=self.max_size,
                idle_timeout=self.idle_timeout,
                sessions=sessions,
                statistics=statistics,
                shutdown=self._shutdown,
            )

    def statistics(self) -> PoolStatistics:
        with self._lock:
            return self._statistics_locked()

    def __enter__(self) -> "BrowserPool":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.shutdown()
