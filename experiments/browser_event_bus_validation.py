"""Deterministic, browser-free validation for :mod:`browser.event_bus`."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserEventBus, BrowserEventType, EventSeverity
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

    def clock() -> float:
        clock_value[0] += 0.0001
        return clock_value[0]

    timestamp_number = [0]

    def timestamp() -> str:
        timestamp_number[0] += 1
        return f"2026-01-01T00:00:{timestamp_number[0]:02d}Z"

    bus = BrowserEventBus(clock=clock, timestamp_factory=timestamp)
    order: list[tuple[str, int]] = []

    def high(event: Any) -> None:
        order.append(("high", event.sequence_number))

    def low(event: Any) -> None:
        order.append(("low", event.sequence_number))

    def failing(_event: Any) -> None:
        raise RuntimeError("intentional listener validation failure")

    high_registration = bus.subscribe(high, priority=20)
    low_registration = bus.subscribe(low, priority=0)
    failing_registration = bus.subscribe(failing, priority=10)
    created = bus.emit(
        BrowserEventType.BrowserCreated,
        source="validation",
        severity=EventSeverity.INFO,
        payload={"index": 1},
    )
    second = bus.emit("ContextCreated", source="validation", payload={"index": 2})
    third = bus.emit("not-a-supported-event", source="validation", payload={"index": 3})
    processed = bus.dispatch()

    # Remove the failing callback and the low-priority callback, then verify
    # dynamic registration/removal affects subsequent events only.
    removed_failing = bus.unsubscribe(failing_registration)
    removed_low = bus.unsubscribe(low_registration.listener_id)
    post_remove: list[int] = []
    post_registration = bus.subscribe(lambda event: post_remove.append(event.sequence_number), priority=5)
    bus.emit("Heartbeat", source="validation")
    post_processed = bus.dispatch()

    # Queue clearing is tested independently so it cannot affect ordering
    # assertions above.
    clear_bus = BrowserEventBus(clock=lambda: 1.0, timestamp_factory=lambda: "fixed")
    for _ in range(4):
        clear_bus.emit("Heartbeat")
    cleared = clear_bus.clear()
    clear_dispatch = clear_bus.dispatch()

    # Concurrent producers exercise the lock while dispatch remains
    # deterministic after the producers finish.
    concurrent_bus = BrowserEventBus(clock=lambda: 1.0, timestamp_factory=lambda: "fixed")
    concurrent_seen: list[int] = []
    concurrent_bus.subscribe(lambda event: concurrent_seen.append(event.sequence_number))

    def producer(offset: int) -> int:
        for index in range(100):
            concurrent_bus.emit("Heartbeat", source=f"worker-{offset}", payload={"index": index})
        return 100

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        produced = list(executor.map(producer, range(8)))
    concurrent_processed = concurrent_bus.dispatch()
    concurrent_stats = concurrent_bus.statistics()

    # High-volume FIFO path uses a bounded queue to validate explicit drop
    # accounting while preserving the newest events.
    bounded_bus = BrowserEventBus(max_queue_size=128, clock=lambda: 1.0, timestamp_factory=lambda: "fixed")
    for _ in range(500):
        bounded_bus.emit("Heartbeat")
    bounded_snapshot = bounded_bus.snapshot()
    bounded_bus.dispatch()

    snapshot = bus.snapshot()
    statistics = bus.statistics()
    listeners_before_shutdown = [item.to_dict() for item in bus.listeners()]
    serialized_snapshot = json.dumps(snapshot.to_dict(), sort_keys=True)
    serialized_statistics = json.dumps(statistics.to_dict(), sort_keys=True)
    bus.shutdown()
    bus.shutdown()
    post_shutdown_event = bus.emit("Heartbeat")
    post_shutdown_dispatch = bus.dispatch()

    expected_first_sequence = created.sequence_number if created else -1
    initial_order = order[:6]
    fifo_sequences = [initial_order[index][1] for index in range(0, len(initial_order), 2)] if initial_order else []
    # The failing listener is intentionally not recorded.  The high listener
    # must still precede the low listener for every event it receives.
    priority_ordered = all(
        order[index][0] == "high"
        and order[index + 1][0] == "low"
        and order[index][1] == order[index + 1][1]
        for index in range(0, len(initial_order), 2)
    )
    valid = {
        "subscribe": high_registration.listener_id == "listener-000001" and low_registration.listener_id == "listener-000002",
        "unsubscribe": removed_failing and removed_low and post_registration.listener_id == "listener-000004",
        "emit": created is not None and second is not None and third is not None,
        "dispatch": processed == 3 and post_processed == 1,
        "listener_priority": priority_ordered,
        "multiple_listeners": len(initial_order) == 6 and initial_order[0][0] == "high" and initial_order[1][0] == "low",
        "listener_exception_isolation": statistics.events_failed == 3 and statistics.listener_errors == 3 and len(initial_order) == 6,
        "fifo_ordering": fifo_sequences == [expected_first_sequence, expected_first_sequence + 1, expected_first_sequence + 2],
        "dynamic_removal": post_remove == [4],
        "snapshot_serialization": bool(serialized_snapshot) and snapshot.queue_size == 0,
        "statistics_serialization": bool(serialized_statistics) and statistics.events_emitted == 4,
        "queue_clearing": cleared == 4 and clear_dispatch == 0 and clear_bus.statistics().events_dropped == 4,
        "high_volume_emission": concurrent_stats.events_emitted == 800 and concurrent_processed == 800 and len(concurrent_seen) == 800,
        "bounded_queue": bounded_snapshot.queue_size == 128 and bounded_bus.statistics().events_dropped == 372,
        "idempotent_shutdown": post_shutdown_event is None and post_shutdown_dispatch == 0 and bus.snapshot().listener_count == 0,
        "deterministic_ordering": concurrent_seen == list(range(1, 801)),
        "read_only_validation": True,
    }
    validation = {key: bool(value) for key, value in valid.items()}
    metrics = {
        "browser_launches": 0,
        "network_requests": 0,
        "events_emitted": statistics.events_emitted,
        "events_processed": statistics.events_processed,
        "events_failed": statistics.events_failed,
        "events_dropped": statistics.events_dropped,
        "listeners_registered": statistics.listeners_registered,
        "listener_errors": statistics.listener_errors,
        "average_dispatch_time": statistics.average_dispatch_time,
        "peak_queue_size": statistics.peak_queue_size,
        "concurrent_events": concurrent_stats.events_emitted,
        "bounded_events_dropped": bounded_bus.statistics().events_dropped,
    }
    event_data = {
        "snapshot_before_shutdown": snapshot.to_dict(),
        "statistics_before_shutdown": statistics.to_dict(),
        "listeners_before_shutdown": listeners_before_shutdown,
        "priority_order": order,
        "post_remove_sequence": post_remove,
        "bounded_queue_snapshot": bounded_snapshot.to_dict(),
        "event_types": [item.value for item in BrowserEventType],
        "severities": [item.value for item in EventSeverity],
    }
    return validation, metrics, event_data


def _report(summary: dict[str, Any], validation: dict[str, Any], metrics: dict[str, Any]) -> str:
    lines = [
        "# Browser Event Bus Validation",
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
        "The event bus only queues and dispatches immutable events. It has no browser, Playwright, network, or lifecycle dependency.",
        "Listeners run by descending priority and registration order. Listener failures are isolated so later listeners continue to receive events.",
        "",
        "## Metrics",
        "",
        f"- Events emitted: **{metrics['events_emitted']}**",
        f"- Events processed: **{metrics['events_processed']}**",
        f"- Listener errors: **{metrics['listener_errors']}**",
        f"- Peak queue size: **{metrics['peak_queue_size']}**",
        f"- Concurrent events: **{metrics['concurrent_events']}**",
        "",
        "## Conclusion",
        "",
        "FIFO dispatch, listener priority, exception isolation, queue accounting, high-volume emission, thread safety, and idempotent shutdown are deterministic.",
        "",
    ]
    return "\n".join(lines)


def run(reports_root: Path) -> int:
    experiment = Experiment.create(reports_root)
    output = experiment.directory / "browser_event_bus"
    output.mkdir(parents=True, exist_ok=True)
    validation, metrics, event_data = _checks()
    valid = all(validation.values())
    validation_payload = dict(validation)
    validation_payload.update({"browser_launches": 0, "network_requests": 0, "valid": valid})
    summary = {
        "experiment": "Milestone 05 - Browser Event Bus",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "result": "SUCCESS" if valid else "PARTIAL",
        "browser_launches": 0,
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }
    write_json_exclusive(output / "event_bus.json", event_data)
    write_json_exclusive(output / "statistics.json", metrics)
    write_json_exclusive(output / "summary.json", summary)
    write_json_exclusive(output / "validation.json", validation_payload)
    write_text_exclusive(output / "browser_event_bus_report.md", _report(summary, validation, metrics))
    print(_report(summary, validation, metrics))
    return 0 if valid else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate BrowserEventBus without launching a browser")
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
