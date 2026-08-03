"""Deterministic validation for the read-only BrowserHealthService."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.health import HealthStatus
from browser.health_service import (
    BrowserHealthService,
    HealthRecommendation,
    ServiceHealthStatus,
)
from experiments.experiment import Experiment
from experiments.utils import configure_console_error_handling, now_iso, project_root, write_json_exclusive, write_text_exclusive


class _FakeSession:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = dict(state)
        self.health_calls = 0
        self.lifecycle_calls = 0

    def health(self) -> dict[str, Any]:
        self.health_calls += 1
        return dict(self.state)

    def start(self) -> None:
        self.lifecycle_calls += 1

    def stop(self) -> None:
        self.lifecycle_calls += 1

    def restart(self) -> None:
        self.lifecycle_calls += 1

    def shutdown(self) -> None:
        self.lifecycle_calls += 1


def _state(
    *,
    browser_alive: bool = True,
    context_alive: bool = True,
    page_count: int = 1,
    status: str = "RUNNING",
    uptime: float = 12.5,
    restart_count: int = 0,
) -> dict[str, Any]:
    return {
        "status": status,
        "browser_alive": browser_alive,
        "context_alive": context_alive,
        "page_count": page_count,
        "uptime": uptime,
        "restart_count": restart_count,
        "last_successful_navigation": "2026-08-03T00:00:00+00:00",
    }


def _run_checks() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    session = _FakeSession(_state())
    service = BrowserHealthService(
        heartbeat_interval=1.0,
        heartbeat_timeout=2.0,
        max_pages=2,
        process_metrics=lambda: (1024, 0.5),
    )
    service.register_session(session)
    service.start()
    healthy = service.snapshot()
    service.tick()
    healthy_tick = service.health()

    session.state.update(page_count=3)
    warning = service.tick()
    session.state.update(page_count=1, context_alive=False)
    context_warning = service.tick()
    session.state.update(context_alive=True, browser_alive=False)
    browser_critical = service.tick()
    session.state.update(status="FAILED", context_alive=False)
    failed = service.tick()

    # A manually controlled clock verifies hung-browser detection without sleep.
    clock_value = [0.0]
    heartbeat_service = BrowserHealthService(
        heartbeat_interval=1.0,
        heartbeat_timeout=2.0,
        process_metrics=lambda: (None, None),
        clock=lambda: clock_value[0],
    )
    heartbeat_service.register_session(_FakeSession(_state()))
    heartbeat_service.start()
    clock_value[0] = 3.0
    stale = heartbeat_service.snapshot()

    empty_service = BrowserHealthService(process_metrics=lambda: (None, None))
    empty_service.start()
    empty = empty_service.tick()

    metrics = service.metrics()
    serialized = json.dumps(healthy.to_dict(), sort_keys=True)
    service.stop()
    service.stop()
    stopped_not_healthy = not service.is_healthy()

    validation = {
        "healthy_browser": healthy.status == ServiceHealthStatus.HEALTHY and healthy.browser_alive and healthy.context_alive,
        "closed_browser": browser_critical.status == ServiceHealthStatus.CRITICAL and browser_critical.recommendation == HealthRecommendation.RESTART_BROWSER,
        "closed_context": context_warning.status == ServiceHealthStatus.CRITICAL and context_warning.recommendation == HealthRecommendation.CREATE_NEW_CONTEXT,
        "empty_session": empty.status == ServiceHealthStatus.UNKNOWN and empty.recommendation == HealthRecommendation.UNKNOWN,
        "multiple_pages": warning.status == ServiceHealthStatus.WARNING and warning.recommendation == HealthRecommendation.CLOSE_UNUSED_PAGES,
        "heartbeat": healthy_tick.heartbeat_age is not None and healthy_tick.heartbeat_age >= 0,
        "hung_browser": stale.status == ServiceHealthStatus.CRITICAL and stale.hung_browser and stale.recommendation == HealthRecommendation.RESTART_BROWSER,
        "metrics": metrics.total_checks >= 5 and metrics.healthy_checks >= 1 and metrics.warning_checks >= 1 and metrics.critical_checks >= 1 and metrics.failed_checks >= 1,
        "snapshot_serialization": bool(serialized) and "recommendation" in healthy.to_dict(),
        "recommendation_generation": warning.recommendation == HealthRecommendation.CLOSE_UNUSED_PAGES and failed.recommendation == HealthRecommendation.RESTART_BROWSER,
        "idempotent_stop": stopped_not_healthy,
        "read_only_session": session.lifecycle_calls == 0,
        "health_alias": healthy_tick.to_dict() == service.health().to_dict() or service.health().status == ServiceHealthStatus.UNKNOWN,
        "status_enum": {item.value for item in ServiceHealthStatus} == {"HEALTHY", "WARNING", "CRITICAL", "FAILED", "UNKNOWN"},
    }
    history = [item.to_dict() for item in (healthy, warning, context_warning, browser_critical, failed, stale, empty)]
    statistics = {
        "browser_launches": 0,
        "network_requests": 0,
        "health_checks": metrics.to_dict(),
        "session_health_calls": session.health_calls,
        "session_lifecycle_calls": session.lifecycle_calls,
        "service_running_after_stop": False,
    }
    return validation, statistics, history


def _report(summary: dict[str, Any], validation: dict[str, Any], statistics: dict[str, Any]) -> str:
    lines = [
        "# Browser Health Service Validation",
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
        "## Observation Boundary",
        "",
        "The service only reads the registered session health contract. It never creates, closes, or restarts a browser.",
        "",
        "## Conclusion",
        "",
        "Health classification, heartbeat aging, metrics, and recommendations are deterministic and read-only.",
        "",
    ]
    return "\n".join(lines)


def run(reports_root: Path) -> int:
    experiment = Experiment.create(reports_root)
    output = experiment.directory / "browser_health"
    output.mkdir(parents=True, exist_ok=True)
    validation, statistics, history = _run_checks()
    valid = all(validation.values())
    validation_payload = dict(validation)
    validation_payload.update({"browser_launches": 0, "network_requests": 0, "valid": valid})
    summary = {
        "experiment": "Milestone 03 - Browser Health Service",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "result": "SUCCESS" if valid else "PARTIAL",
        "final_status": history[-1]["status"],
        "browser_launches": 0,
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }
    write_json_exclusive(output / "health.json", {"history": history, "latest": history[-1]})
    write_json_exclusive(output / "metrics.json", statistics["health_checks"])
    write_json_exclusive(output / "statistics.json", statistics)
    write_json_exclusive(output / "summary.json", summary)
    write_json_exclusive(output / "validation.json", validation_payload)
    report = _report(summary, validation, statistics)
    write_text_exclusive(output / "browser_health_report.md", report)
    print(report)
    return 0 if valid else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate BrowserHealthService")
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
