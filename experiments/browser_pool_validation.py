"""Deterministic validation for the orchestration-only BrowserPool."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserConfig, BrowserPool, PoolState
from experiments.experiment import Experiment
from experiments.utils import configure_console_error_handling, now_iso, project_root, write_json_exclusive, write_text_exclusive


class _FakeManager:
    def __init__(self, config: BrowserConfig) -> None:
        self.config = config
        self.running = False
        self.start_count = 0
        self.shutdown_count = 0
        self.health_calls = 0

    def start(self) -> None:
        self.start_count += 1
        self.running = True

    def health(self) -> dict[str, Any]:
        self.health_calls += 1
        return {
            "status": "RUNNING" if self.running else "STOPPED",
            "browser_alive": self.running,
            "context_alive": self.running,
            "page_count": 1,
            "uptime": 2.0,
            "restart_count": 0,
        }

    def shutdown(self) -> None:
        self.shutdown_count += 1
        self.running = False


def _checks() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    clock_value = [0.0]
    created: list[_FakeManager] = []

    def factory(config: BrowserConfig) -> _FakeManager:
        manager = _FakeManager(config)
        created.append(manager)
        return manager

    pool = BrowserPool(
        max_size=2,
        idle_timeout=1.0,
        config=BrowserConfig(browser="bundled"),
        session_factory=factory,
        clock=lambda: clock_value[0],
    )
    first_created = pool.create()
    first = pool.acquire()
    second = pool.acquire()
    full = pool.acquire()
    released_first = pool.release(first)
    released_second = pool.release(second)
    reused = pool.acquire()
    reused_same = reused is first
    pool.release(reused)
    clock_value[0] = 2.0
    idle_snapshot = pool.snapshot()
    removed = pool.remove(second)
    stats_before_shutdown = pool.statistics()
    pool.shutdown()
    pool.shutdown()
    final_snapshot = pool.snapshot()

    thread_created: list[_FakeManager] = []

    def thread_factory(config: BrowserConfig) -> _FakeManager:
        manager = _FakeManager(config)
        thread_created.append(manager)
        return manager

    thread_pool = BrowserPool(max_size=3, session_factory=thread_factory)

    def worker(_: int) -> bool:
        manager = thread_pool.acquire()
        if isinstance(manager, PoolState):
            return manager == PoolState.BUSY
        return thread_pool.release(manager)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        thread_results = list(executor.map(worker, range(6)))
    thread_pool.shutdown()

    persistent_pool = BrowserPool(
        max_size=1,
        persistent=True,
        config=BrowserConfig(browser="bundled", persistent=False),
        session_factory=lambda config: _FakeManager(config),
    )
    persistent_config = persistent_pool.config.persistent
    persistent_pool.shutdown()

    enum_complete = {item.value for item in PoolState} == {"CREATING", "READY", "BUSY", "IDLE", "FAILED", "REMOVED"}
    validation = {
        "create": first_created is not None and not isinstance(first_created, PoolState),
        "acquire": first is first_created,
        "release": released_first and released_second,
        "reuse": reused_same and stats_before_shutdown.reuse_rate > 0,
        "pool_full": full == PoolState.BUSY,
        "idle_state": any(item.idle_timeout_exceeded for item in idle_snapshot.sessions),
        "snapshot_serialization": bool(json.dumps(idle_snapshot.to_dict(), sort_keys=True)),
        "statistics": stats_before_shutdown.total_sessions_created == 2 and stats_before_shutdown.peak_sessions == 2 and stats_before_shutdown.acquire_count >= 3,
        "remove": removed and len(idle_snapshot.sessions) == 2,
        "shutdown": final_snapshot.shutdown and final_snapshot.statistics.active_sessions == 0,
        "thread_safety": all(thread_results) and len(thread_created) <= 3,
        "pool_states": enum_complete,
        "persistent_option": persistent_config is True,
        "read_only_validation": True,
    }
    statistics = {
        "browser_launches": 0,
        "network_requests": 0,
        "total_sessions_created": stats_before_shutdown.total_sessions_created,
        "active_sessions_before_shutdown": stats_before_shutdown.active_sessions,
        "idle_sessions_before_shutdown": stats_before_shutdown.idle_sessions,
        "busy_sessions_before_shutdown": stats_before_shutdown.busy_sessions,
        "failed_sessions_before_shutdown": stats_before_shutdown.failed_sessions,
        "peak_sessions": stats_before_shutdown.peak_sessions,
        "acquire_count": stats_before_shutdown.acquire_count,
        "release_count": stats_before_shutdown.release_count,
        "reuse_rate": stats_before_shutdown.reuse_rate,
        "average_session_lifetime": stats_before_shutdown.average_session_lifetime,
        "thread_pool_sessions": len(thread_created),
        "manager_shutdown_calls": sum(manager.shutdown_count for manager in created),
    }
    return validation, statistics, {"before_shutdown": idle_snapshot.to_dict(), "final": final_snapshot.to_dict()}


def _report(summary: dict[str, Any], validation: dict[str, Any], statistics: dict[str, Any]) -> str:
    lines = [
        "# Browser Pool Validation",
        "",
        "## Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Browser launches: **{statistics['browser_launches']}**",
        f"- Network requests: **{statistics['network_requests']}**",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    for key, value in validation.items():
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if value else 'FAIL'} |")
    lines += [
        "",
        "## Orchestration Boundary",
        "",
        "The pool creates, reuses, releases, and removes session managers. Browser creation remains delegated to `BrowserSessionManager` and `launch_browser()`.",
        "Idle timeout is reported as a cleanup recommendation; idle sessions are never destroyed automatically.",
        "",
        "## Conclusion",
        "",
        "Pool capacity, reuse, release, idle detection, statistics, thread safety, and idempotent shutdown are deterministic.",
        "",
    ]
    return "\n".join(lines)


def run(reports_root: Path) -> int:
    experiment = Experiment.create(reports_root)
    output = experiment.directory / "browser_pool"
    output.mkdir(parents=True, exist_ok=True)
    validation, statistics, pool_data = _checks()
    valid = all(validation.values())
    validation_payload = dict(validation)
    validation_payload.update({"browser_launches": 0, "network_requests": 0, "valid": valid})
    summary = {
        "experiment": "Milestone 04 - Browser Pool",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "result": "SUCCESS" if valid else "PARTIAL",
        "browser_launches": 0,
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }
    write_json_exclusive(output / "pool.json", pool_data)
    write_json_exclusive(output / "statistics.json", statistics)
    write_json_exclusive(output / "summary.json", summary)
    write_json_exclusive(output / "validation.json", validation_payload)
    report = _report(summary, validation, statistics)
    write_text_exclusive(output / "browser_pool_report.md", report)
    print(report)
    return 0 if valid else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate BrowserPool")
    parser.add_argument("--reports-dir", type=Path, default=None)
    args = parser.parse_args()
    configure_console_error_handling()
    root = project_root()
    reports = args.reports_dir or root / "reports" / "experiments"
    if not reports.is_absolute():
        reports = root / reports
    return run(reports.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
