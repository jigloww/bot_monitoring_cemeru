"""Health state and snapshots for managed browser sessions."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class HealthStatus(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    RESTARTING = "RESTARTING"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class HealthSnapshot:
    """Immutable point-in-time health data exposed by ``health()``."""

    status: HealthStatus
    uptime: float
    restart_count: int
    page_count: int
    context_alive: bool
    browser_alive: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "uptime": round(max(0.0, float(self.uptime)), 6),
            "restart_count": int(self.restart_count),
            "page_count": int(self.page_count),
            "context_alive": bool(self.context_alive),
            "browser_alive": bool(self.browser_alive),
            "reason": self.reason,
        }

    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-style access for integration callers."""
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

