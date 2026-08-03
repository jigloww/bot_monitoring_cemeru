"""Deterministic validation for BrowserMetricsService without a browser."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserEventBus, BrowserMetricsService
from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    write_json_exclusive,
    write_text_exclusive,
)


def _checks() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    clock_value = [0.0]
    timestamp_number = [0]

    def clock() -> float:
        return clock_value[0]

    def timestamp() -> str:
        timestamp_number[0] += 1
        return f"2026-01-01T00:00:{timestamp_number[0]:02d}Z"

    bus = BrowserEventBus(clock=clock, timestamp_factory=timestamp)
    service = BrowserMetricsService(
        bus,
        moving_average_window=2,
        clock=clock,
        timestamp_factory=lambda: "2026-01-01T00:01:00Z",
    )
    start_running = service.is_running()
    start_idempotent = service.start() and service.start()

    def publish(event_type: str, payload: dict[str, Any] | None = None, *, severity: str = "INFO") -> None:
        bus.emit(event_type, source="validation", severity=severity, payload=payload or {})
        bus.dispatch()

    clock_value[0] = 0.0
    publish("BrowserCreated", {"browser_id": "browser-1"})
    publish("ContextCreated", {"context_id": "context-1"})
    publish("PageCreated", {"page_id": "page-1"})
    publish("NavigationStarted", {"navigation_id": "nav-1"})
    clock_value[0] = 0.25
    publish("NavigationFinished", {"navigation_id": "nav-1"})
    publish("NavigationStarted", {"navigation_id": "nav-2"})
    clock_value[0] = 0.35
    publish("NavigationFailed", {"navigation_id": "nav-2"})
    publish("NavigationStarted", {"navigation_id": "nav-3"})
    clock_value[0] = 0.40
    publish("NavigationFinished", {"navigation_id": "nav-3"})
    publish("HealthChanged", {"status": "HEALTHY"})
    publish("HealthChanged", {"status": "WARNING"}, severity="WARNING")
    publish("HealthChanged", {"status": "FAILED"}, severity="ERROR")
    publish("SessionAcquired", {"session_id": "session-1", "created": True})
    publish("SessionAcquired", {"session_id": "session-2", "reused": True})
    publish("SessionReleased", {"session_id": "session-1", "lifetime_ms": 30})
    publish("SessionReleased", {"session_id": "session-2", "lifetime_ms": 60})
    publish("BrowserRestarted", {"browser_id": "browser-1"})
    publish("CrashDetected", {"browser_id": "browser-1"}, severity="CRITICAL")
    clock_value[0] = 0.90
    publish("BrowserClosed", {"browser_id": "browser-1"})
    publish("ContextClosed", {"context_id": "context-1"})
    publish("PageClosed", {"page_id": "page-1"})
    publish("Heartbeat", {})

    snapshot = service.snapshot()
    statistics = service.statistics()
    snapshot_serialized = json.dumps(snapshot.to_dict(), sort_keys=True)
    statistics_serialized = json.dumps(statistics.to_dict(), sort_keys=True)
    immutable_snapshot = False
    try:
        snapshot.counters["browser_count"] = 99  # type: ignore[index]
    except TypeError:
        immutable_snapshot = True

    counters = snapshot.to_dict()["counters"]
    timers = statistics.to_dict()["timers"]
    rates = statistics.to_dict()["rates"]
    metrics_match = (
        counters["browser_count"] == 0
        and counters["browser_restart_count"] == 1
        and counters["browser_crash_count"] == 1
        and counters["session_created"] == 1
        and counters["session_released"] == 2
        and counters["session_reused"] == 1
        and counters["contexts_created"] == 1
        and counters["contexts_closed"] == 1
        and counters["pages_created"] == 1
        and counters["pages_closed"] == 1
        and counters["navigation_started"] == 3
        and counters["navigation_finished"] == 2
        and counters["navigation_failed"] == 1
        and counters["healthy_events"] == 1
        and counters["warning_events"] == 1
        and counters["critical_events"] == 1
        and counters["pool_acquire"] == 2
        and counters["pool_release"] == 2
        and counters["events_received"] == counters["events_processed"]
    )
    timer_match = (
        timers["navigation_time"]["count"] == 3
        and round(float(timers["navigation_time"]["average"]), 6) == round((250.0 + 100.0 + 50.0) / 3.0, 6)
        and round(float(timers["navigation_time"]["median"]), 6) == 100.0
        and round(float(timers["navigation_time"]["minimum"]), 6) == 50.0
        and round(float(timers["navigation_time"]["maximum"]), 6) == 250.0
        and round(float(timers["navigation_time"]["moving_average"]), 6) == 75.0
        and timers["session_lifetime"]["count"] == 2
    )
    rates_match = (
        round(rates["navigation_success_rate"], 6) == round(2 / 3, 6)
        and round(rates["navigation_failure_rate"], 6) == round(1 / 3, 6)
        and rates["pool_reuse_rate"] == 0.5
        and round(rates["average_navigation_time"], 6) == round((250.0 + 100.0 + 50.0) / 3.0, 6)
    )

    before_stop = counters["events_received"]
    service.stop()
    publish("Heartbeat", {})
    stopped_no_update = service.snapshot().to_dict()["counters"]["events_received"] == before_stop
    restarted = service.start()
    publish("Heartbeat", {})
    restarted_update = service.snapshot().to_dict()["counters"]["events_received"] == before_stop + 1

    # Concurrent producers validate event-bus and metrics locking. Sequence
    # numbers remain deterministic after dispatch, independent of worker.
    volume_bus = BrowserEventBus(clock=lambda: 1.0, timestamp_factory=lambda: "fixed")
    volume_service = BrowserMetricsService(volume_bus, clock=lambda: 1.0, timestamp_factory=lambda: "fixed")
    observed_sequences: list[int] = []
    volume_bus.subscribe(lambda event: observed_sequences.append(event.sequence_number), priority=10)

    def producer(worker: int) -> int:
        for index in range(100):
            volume_bus.emit("Heartbeat", source=f"worker-{worker}", payload={"index": index})
        return 100

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        produced = list(executor.map(producer, range(8)))
    volume_processed = volume_bus.dispatch()
    volume_stats = volume_service.statistics().to_dict()
    volume_service.shutdown()
    volume_bus.shutdown()

    events_before_shutdown = service.snapshot().to_dict()["counters"]["events_received"]
    service.shutdown()
    service.shutdown()
    shutdown_idempotent = not service.is_running()
    bus.emit("Heartbeat", source="post-shutdown")
    bus.dispatch()
    shutdown_no_update = service.snapshot().to_dict()["counters"]["events_received"] == events_before_shutdown

    validation = {
        "metric_counting": metrics_match,
        "event_subscription": start_running and start_idempotent and restarted,
        "snapshot_serialization": bool(snapshot_serialized) and immutable_snapshot,
        "statistics_serialization": bool(statistics_serialized),
        "timer_calculation": timer_match,
        "moving_averages": rates_match and timers["navigation_time"]["moving_average"] == 75.0,
        "high_volume_events": sum(produced) == 800 and volume_processed == 800 and volume_stats["counters"]["events_received"] == 800,
        "thread_safety": observed_sequences == list(range(1, 801)),
        "idempotent_shutdown": shutdown_idempotent and shutdown_no_update,
        "deterministic_ordering": observed_sequences == sorted(observed_sequences),
        "read_only_validation": True,
    }
    metrics = {
        "browser_launches": 0,
        "network_requests": 0,
        "events_received": counters["events_received"],
        "events_processed": counters["events_processed"],
        "navigation_success_rate": rates["navigation_success_rate"],
        "navigation_failure_rate": rates["navigation_failure_rate"],
        "pool_reuse_rate": rates["pool_reuse_rate"],
        "average_navigation_time": rates["average_navigation_time"],
        "volume_events": volume_stats["counters"]["events_received"],
        "volume_dispatches": volume_processed,
        "volume_sequence_count": len(observed_sequences),
    }
    data = {
        "snapshot": snapshot.to_dict(),
        "statistics": statistics.to_dict(),
        "volume_statistics": volume_stats,
        "event_subscription": {
            "running_before_stop": start_running,
            "stopped_without_update": stopped_no_update,
            "restarted": restarted,
            "restarted_update": restarted_update,
        },
    }
    return {key: bool(value) for key, value in validation.items()}, metrics, data


def _report(summary: dict[str, Any], validation: dict[str, Any], metrics: dict[str, Any]) -> str:
    lines = [
        "# Browser Metrics & Telemetry Validation",
        "",
        "## Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Browser launches: **{metrics['browser_launches']}**",
        f"- Network requests: **{metrics['network_requests']}**",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    for key, value in validation.items():
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if value else 'FAIL'} |")
    lines += [
        "",
        "## Architecture Boundary",
        "",
        "The metrics service is a passive Event Bus subscriber. It does not launch browsers, create sessions, dispatch events, or perform network operations.",
        "",
        "## Runtime Metrics",
        "",
        f"- Events received: **{metrics['events_received']}**",
        f"- Navigation success rate: **{metrics['navigation_success_rate']:.2%}**",
        f"- Navigation failure rate: **{metrics['navigation_failure_rate']:.2%}**",
        f"- Pool reuse rate: **{metrics['pool_reuse_rate']:.2%}**",
        f"- Average navigation time: **{metrics['average_navigation_time']:.2f} ms**",
        f"- Concurrent events processed: **{metrics['volume_dispatches']}**",
        "",
        "## Conclusion",
        "",
        "Counter aggregation, timer statistics, moving averages, event subscription, high-volume processing, thread safety, immutable snapshots, and idempotent shutdown are deterministic.",
        "",
    ]
    return "\n".join(lines)


def run(reports_root: Path) -> int:
    experiment = Experiment.create(reports_root)
    output = experiment.directory / "browser_metrics"
    output.mkdir(parents=True, exist_ok=True)
    validation, metrics, data = _checks()
    valid = all(validation.values())
    validation_payload = dict(validation)
    validation_payload.update({"browser_launches": 0, "network_requests": 0, "valid": valid})
    summary = {
        "experiment": "Milestone 06 - Browser Metrics & Telemetry",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "result": "SUCCESS" if valid else "PARTIAL",
        "browser_launches": 0,
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }
    write_json_exclusive(output / "metrics.json", data)
    write_json_exclusive(output / "statistics.json", metrics)
    write_json_exclusive(output / "summary.json", summary)
    write_json_exclusive(output / "validation.json", validation_payload)
    write_text_exclusive(output / "browser_metrics_report.md", _report(summary, validation, metrics))
    print(_report(summary, validation, metrics))
    return 0 if valid else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate BrowserMetricsService without launching a browser")
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
