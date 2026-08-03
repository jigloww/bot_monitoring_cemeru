"""Read-only health observation service for ``BrowserSessionManager``."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class ServiceHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class HealthRecommendation(str, Enum):
    NONE = "NONE"
    RESTART_BROWSER = "RESTART_BROWSER"
    CLOSE_UNUSED_PAGES = "CLOSE_UNUSED_PAGES"
    CREATE_NEW_CONTEXT = "CREATE_NEW_CONTEXT"
    CHECK_MEMORY = "CHECK_MEMORY"
    UNKNOWN = "UNKNOWN"


# Compatibility aliases for callers that import the service enums directly.
HealthStatus = ServiceHealthStatus
Recommendation = HealthRecommendation


@dataclass(frozen=True)
class HealthServiceSnapshot:
    """Immutable health snapshot returned by ``snapshot()`` and ``health()``."""

    timestamp: str
    browser_alive: bool
    context_alive: bool
    page_count: int
    uptime: float
    restart_count: int
    heartbeat_age: float | None
    status: ServiceHealthStatus
    recommendation: HealthRecommendation
    last_successful_navigation: str | None = None
    last_heartbeat: str | None = None
    memory_bytes: int | None = None
    cpu_percent: float | None = None
    crash_detected: bool = False
    hung_browser: bool = False
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "browser_alive": self.browser_alive,
            "context_alive": self.context_alive,
            "page_count": self.page_count,
            "uptime": round(max(0.0, self.uptime), 6),
            "restart_count": self.restart_count,
            "heartbeat_age": None if self.heartbeat_age is None else round(max(0.0, self.heartbeat_age), 6),
            "status": self.status.value,
            "recommendation": self.recommendation.value,
            "last_successful_navigation": self.last_successful_navigation,
            "last_heartbeat": self.last_heartbeat,
            "memory_bytes": self.memory_bytes,
            "cpu_percent": self.cpu_percent,
            "crash_detected": self.crash_detected,
            "hung_browser": self.hung_browser,
            "reason": self.reason,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


@dataclass(frozen=True)
class HealthServiceMetrics:
    total_checks: int
    healthy_checks: int
    warning_checks: int
    critical_checks: int
    failed_checks: int
    average_check_duration: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_checks": self.total_checks,
            "healthy_checks": self.healthy_checks,
            "warning_checks": self.warning_checks,
            "critical_checks": self.critical_checks,
            "failed_checks": self.failed_checks,
            "average_check_duration": round(max(0.0, self.average_check_duration), 6),
        }


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_process_metrics() -> tuple[int | None, float | None]:
    """Best-effort process metrics; absence of psutil is not a failure."""
    try:
        import psutil  # type: ignore[import-not-found]

        process = psutil.Process()
        memory = int(process.memory_info().rss)
        cpu = float(process.cpu_percent(interval=None))
        return memory, cpu
    except Exception:
        return None, None


class BrowserHealthService:
    """Observe a registered session without creating, closing, or restarting it."""

    def __init__(
        self,
        *,
        heartbeat_interval: float = 10.0,
        heartbeat_timeout: float | None = None,
        max_pages: int = 20,
        max_memory_bytes: int | None = None,
        process_metrics: Callable[[], tuple[int | None, float | None]] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be positive")
        if heartbeat_timeout is not None and heartbeat_timeout <= 0:
            raise ValueError("heartbeat_timeout must be positive")
        if max_pages < 0:
            raise ValueError("max_pages cannot be negative")
        self.heartbeat_interval = float(heartbeat_interval)
        self.heartbeat_timeout = float(heartbeat_timeout or heartbeat_interval * 3.0)
        self.max_pages = int(max_pages)
        self.max_memory_bytes = max_memory_bytes
        self._process_metrics = process_metrics or _optional_process_metrics
        self._clock = clock or time.monotonic
        self._session: Any = None
        self._running = False
        self._started_at: float | None = None
        self._last_heartbeat_monotonic: float | None = None
        self._last_heartbeat_iso: str | None = None
        self._snapshot: HealthServiceSnapshot | None = None
        self._total_checks = 0
        self._healthy_checks = 0
        self._warning_checks = 0
        self._critical_checks = 0
        self._failed_checks = 0
        self._duration_total = 0.0
        self._lock = threading.RLock()

    def register_session(self, session: Any) -> "BrowserHealthService":
        """Register an existing session for observation; no lifecycle action is run."""
        with self._lock:
            if session is not None and not callable(getattr(session, "health", None)):
                raise TypeError("session must expose health()")
            self._session = session
            self._snapshot = None
            self._last_heartbeat_monotonic = None
            self._last_heartbeat_iso = None
            return self

    def start(self) -> "BrowserHealthService":
        with self._lock:
            if self._running:
                return self
            self._running = True
            self._started_at = self._clock()
            if self._session is not None:
                self._tick_locked()
            else:
                self._snapshot = self._build_snapshot_locked(
                    ServiceHealthStatus.UNKNOWN,
                    HealthRecommendation.UNKNOWN,
                    reason="no session registered",
                )
            return self

    def stop(self) -> None:
        """Stop observation only; the registered browser session is untouched."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._snapshot is not None:
                current = self._snapshot.to_dict()
                current.update({
                    "status": ServiceHealthStatus.UNKNOWN,
                    "recommendation": HealthRecommendation.UNKNOWN,
                    "reason": "health service stopped",
                })
                self._snapshot = HealthServiceSnapshot(**current)

    def _read_session_locked(self) -> dict[str, Any]:
        if self._session is None:
            raise LookupError("no session registered")
        result = self._session.health()
        status = str(_field(result, "status", "UNKNOWN"))
        if "." in status:
            status = status.rsplit(".", 1)[-1]
        return {
            "status": status,
            "browser_alive": bool(_field(result, "browser_alive", False)),
            "context_alive": bool(_field(result, "context_alive", False)),
            "page_count": max(0, int(_number(_field(result, "page_count", 0), 0))),
            "uptime": max(0.0, _number(_field(result, "uptime", 0.0), 0.0)),
            "restart_count": max(0, int(_number(_field(result, "restart_count", 0), 0))),
            "last_successful_navigation": _field(result, "last_successful_navigation"),
        }

    def _build_snapshot_locked(
        self,
        status: ServiceHealthStatus,
        recommendation: HealthRecommendation,
        *,
        reason: str | None = None,
        browser_alive: bool = False,
        context_alive: bool = False,
        page_count: int = 0,
        uptime: float = 0.0,
        restart_count: int = 0,
        last_successful_navigation: str | None = None,
        memory_bytes: int | None = None,
        cpu_percent: float | None = None,
        crash_detected: bool = False,
        hung_browser: bool = False,
    ) -> HealthServiceSnapshot:
        now = self._clock()
        heartbeat_age = None
        if self._last_heartbeat_monotonic is not None:
            heartbeat_age = max(0.0, now - self._last_heartbeat_monotonic)
        return HealthServiceSnapshot(
            timestamp=_iso_now(),
            browser_alive=browser_alive,
            context_alive=context_alive,
            page_count=page_count,
            uptime=uptime,
            restart_count=restart_count,
            heartbeat_age=heartbeat_age,
            status=status,
            recommendation=recommendation,
            last_successful_navigation=last_successful_navigation,
            last_heartbeat=self._last_heartbeat_iso,
            memory_bytes=memory_bytes,
            cpu_percent=cpu_percent,
            crash_detected=crash_detected,
            hung_browser=hung_browser,
            reason=reason,
        )

    def _tick_locked(self) -> HealthServiceSnapshot:
        started = self._clock()
        self._last_heartbeat_monotonic = started
        self._last_heartbeat_iso = _iso_now()
        memory_bytes, cpu_percent = self._process_metrics()
        if self._session is None:
            snapshot = self._build_snapshot_locked(
                ServiceHealthStatus.UNKNOWN,
                HealthRecommendation.UNKNOWN,
                reason="no session registered",
                memory_bytes=memory_bytes,
                cpu_percent=cpu_percent,
            )
            self._snapshot = snapshot
            self._total_checks += 1
            self._duration_total += max(0.0, self._clock() - started)
            return snapshot
        try:
            values = self._read_session_locked()
        except Exception as exc:
            snapshot = self._build_snapshot_locked(
                ServiceHealthStatus.FAILED,
                HealthRecommendation.RESTART_BROWSER,
                reason=str(exc),
                memory_bytes=memory_bytes,
                cpu_percent=cpu_percent,
                crash_detected=True,
            )
        else:
            source_status = values["status"]
            browser_alive = values["browser_alive"]
            context_alive = values["context_alive"]
            page_count = values["page_count"]
            reason = None
            crash_detected = source_status in {"FAILED", "STOPPED"} or not browser_alive or not context_alive
            hung_browser = False
            status = ServiceHealthStatus.HEALTHY
            recommendation = HealthRecommendation.NONE
            if source_status in {"FAILED"}:
                status, recommendation, reason = ServiceHealthStatus.FAILED, HealthRecommendation.RESTART_BROWSER, "session reports FAILED"
            elif source_status == "STOPPED":
                status, recommendation, reason = ServiceHealthStatus.CRITICAL, HealthRecommendation.RESTART_BROWSER, "session reports STOPPED"
            elif not browser_alive:
                status, recommendation, reason = ServiceHealthStatus.CRITICAL, HealthRecommendation.RESTART_BROWSER, "browser is not alive"
            elif not context_alive:
                status, recommendation, reason = ServiceHealthStatus.CRITICAL, HealthRecommendation.CREATE_NEW_CONTEXT, "context is not alive"
            elif source_status in {"UNKNOWN", "STARTING", "RESTARTING"}:
                status, recommendation, reason = ServiceHealthStatus.UNKNOWN, HealthRecommendation.UNKNOWN, f"session status is {source_status}"
            elif page_count > self.max_pages:
                status, recommendation, reason = ServiceHealthStatus.WARNING, HealthRecommendation.CLOSE_UNUSED_PAGES, "page count exceeds configured limit"
            elif self.max_memory_bytes is not None and memory_bytes is not None and memory_bytes > self.max_memory_bytes:
                status, recommendation, reason = ServiceHealthStatus.WARNING, HealthRecommendation.CHECK_MEMORY, "process memory exceeds configured limit"
            snapshot = self._build_snapshot_locked(
                status,
                recommendation,
                reason=reason,
                browser_alive=browser_alive,
                context_alive=context_alive,
                page_count=page_count,
                uptime=values["uptime"],
                restart_count=values["restart_count"],
                last_successful_navigation=values["last_successful_navigation"],
                memory_bytes=memory_bytes,
                cpu_percent=cpu_percent,
                crash_detected=crash_detected,
                hung_browser=hung_browser,
            )
        self._snapshot = snapshot
        self._total_checks += 1
        if snapshot.status == ServiceHealthStatus.HEALTHY:
            self._healthy_checks += 1
        elif snapshot.status == ServiceHealthStatus.WARNING:
            self._warning_checks += 1
        elif snapshot.status == ServiceHealthStatus.CRITICAL:
            self._critical_checks += 1
        elif snapshot.status == ServiceHealthStatus.FAILED:
            self._failed_checks += 1
        self._duration_total += max(0.0, self._clock() - started)
        return snapshot

    def tick(self) -> HealthServiceSnapshot:
        with self._lock:
            if not self._running:
                return self._snapshot or self._build_snapshot_locked(
                    ServiceHealthStatus.UNKNOWN,
                    HealthRecommendation.UNKNOWN,
                    reason="health service is stopped",
                )
            return self._tick_locked()

    def _stale_snapshot_locked(self) -> HealthServiceSnapshot | None:
        if self._snapshot is None or self._last_heartbeat_monotonic is None:
            return self._snapshot
        age = max(0.0, self._clock() - self._last_heartbeat_monotonic)
        if age <= self.heartbeat_timeout or self._snapshot.status in {ServiceHealthStatus.FAILED, ServiceHealthStatus.CRITICAL}:
            return self._snapshot
        return HealthServiceSnapshot(
            **{
                **self._snapshot.to_dict(),
                "status": ServiceHealthStatus.CRITICAL,
                "recommendation": HealthRecommendation.RESTART_BROWSER,
                "heartbeat_age": age,
                "hung_browser": True,
                "reason": "heartbeat is stale",
            }
        )

    def snapshot(self) -> HealthServiceSnapshot:
        with self._lock:
            return self._stale_snapshot_locked() or self._build_snapshot_locked(ServiceHealthStatus.UNKNOWN, HealthRecommendation.UNKNOWN, reason="no health check yet")

    def health(self) -> HealthServiceSnapshot:
        return self.snapshot()

    def is_healthy(self) -> bool:
        return self.snapshot().status == ServiceHealthStatus.HEALTHY

    def metrics(self) -> HealthServiceMetrics:
        with self._lock:
            average = self._duration_total / self._total_checks if self._total_checks else 0.0
            return HealthServiceMetrics(
                total_checks=self._total_checks,
                healthy_checks=self._healthy_checks,
                warning_checks=self._warning_checks,
                critical_checks=self._critical_checks,
                failed_checks=self._failed_checks,
                average_check_duration=average,
            )
