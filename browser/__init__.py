"""Reusable browser-launching primitives for project consumers."""

from .config import BrowserConfig
from .launcher import BrowserSession, available_executables, launch_browser
from .health import HealthSnapshot, HealthStatus
from .health_service import BrowserHealthService, HealthRecommendation, ServiceHealthStatus
from .manager import BrowserSessionManager
from .pool import BrowserPool, PoolSessionSnapshot, PoolState, PoolStatistics, PoolSnapshot
from .event_bus import (
    BrowserEvent,
    BrowserEventBus,
    BrowserEventType,
    EventListener,
    EventSeverity,
    EventSnapshot,
    EventStatistics,
    EventType,
    Severity,
)
from .metrics import BrowserMetricsService, MetricCounter, MetricTimer, MetricsSnapshot, MetricsStatistics
from .profile import ProfileManager
from .context import invoke_stealth_hook, new_context, persistent_context
from .session import ManagedSession, PageRegistry

__all__ = [
    "BrowserConfig",
    "BrowserSession",
    "BrowserSessionManager",
    "BrowserHealthService",
    "BrowserPool",
    "BrowserEvent",
    "BrowserEventBus",
    "BrowserEventType",
    "BrowserMetricsService",
    "HealthRecommendation",
    "HealthSnapshot",
    "HealthStatus",
    "EventListener",
    "EventSeverity",
    "EventSnapshot",
    "EventStatistics",
    "EventType",
    "Severity",
    "MetricCounter",
    "MetricTimer",
    "MetricsSnapshot",
    "MetricsStatistics",
    "ManagedSession",
    "PageRegistry",
    "PoolSessionSnapshot",
    "PoolState",
    "PoolStatistics",
    "PoolSnapshot",
    "ServiceHealthStatus",
    "ProfileManager",
    "available_executables",
    "invoke_stealth_hook",
    "launch_browser",
    "new_context",
    "persistent_context",
]
