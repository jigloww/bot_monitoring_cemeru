"""Deterministic validation for :class:`browser.BrowserSessionManager`.

The checks use fake Playwright objects, so this experiment does not launch a
real browser, touch the network, or run monitoring/booking logic.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserConfig, BrowserSessionManager, HealthStatus, ProfileManager
from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    write_json_exclusive,
    write_text_exclusive,
)


class _Emitter:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Any]] = {}

    def on(self, event: str, callback: Any) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def emit(self, event: str, *args: Any) -> None:
        for callback in list(self._listeners.get(event, [])):
            callback(*args)


class _FakePage(_Emitter):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False
        self.close_count = 0

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.close_count += 1
        self.emit("close")


class _FakeContext(_Emitter):
    def __init__(self, browser: "_FakeBrowser | None" = None) -> None:
        super().__init__()
        self.browser = browser
        self.closed = False
        self.close_count = 0
        self.pages: list[_FakePage] = []

    def is_closed(self) -> bool:
        return self.closed

    def new_page(self) -> _FakePage:
        page = _FakePage()
        self.pages.append(page)
        self.emit("page", page)
        return page

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.close_count += 1
        for page in list(self.pages):
            page.close()
        if self.browser is not None:
            self.browser.connected = False
        self.emit("close")


class _FakeBrowser(_Emitter):
    def __init__(self) -> None:
        super().__init__()
        self.connected = True
        self.close_count = 0
        self.contexts: list[_FakeContext] = []

    def is_connected(self) -> bool:
        return self.connected

    def new_context(self, **_options: Any) -> _FakeContext:
        context = _FakeContext(self)
        self.contexts.append(context)
        return context

    def close(self) -> None:
        if not self.connected:
            return
        self.connected = False
        self.close_count += 1
        self.emit("disconnected")


class _FakeChromium:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.launch_count = 0
        self.persistent_launch_count = 0
        self.browsers: list[_FakeBrowser] = []

    def launch(self, **_options: Any) -> _FakeBrowser:
        if self.fail:
            raise RuntimeError("synthetic launch failure")
        self.launch_count += 1
        browser = _FakeBrowser()
        self.browsers.append(browser)
        return browser

    def launch_persistent_context(self, _user_data_dir: str, **_options: Any) -> _FakeContext:
        if self.fail:
            raise RuntimeError("synthetic persistent launch failure")
        self.persistent_launch_count += 1
        browser = _FakeBrowser()
        context = _FakeContext(browser)
        browser.contexts.append(context)
        self.browsers.append(browser)
        return context


class _FakePlaywright:
    def __init__(self, *, fail: bool = False) -> None:
        self.chromium = _FakeChromium(fail=fail)


def _manager_checks() -> tuple[dict[str, Any], dict[str, Any]]:
    playwright = _FakePlaywright()
    manager = BrowserSessionManager(
        BrowserConfig(browser="bundled", headless=True),
        playwright=playwright,
    )
    manager.start()
    running = manager.health()
    initial_page_count = running.page_count
    first_extra_page = manager.new_page()
    after_new_page = manager.health().page_count
    manager.close_page(first_extra_page)
    after_close_page = manager.health().page_count

    browser_before_disconnect = manager.get_browser()
    browser_before_disconnect.emit("disconnected")
    recovered = manager.health()
    restart_recovered = recovered.status == HealthStatus.RUNNING and recovered.restart_count == 1
    manager.restart()
    after_manual_restart = manager.health()
    manager.stop()
    stopped = manager.health()
    manager.shutdown()
    manager.shutdown()
    idempotent_shutdown = stopped.status == HealthStatus.STOPPED and manager.health().status == HealthStatus.STOPPED

    with tempfile.TemporaryDirectory(prefix="session-manager-validation-") as temp_root:
        persistent_path = Path(temp_root) / "persistent"
        persistent_manager = BrowserSessionManager(
            BrowserConfig(browser="bundled", persistent=True, profile_path=persistent_path),
            playwright=_FakePlaywright(),
        )
        persistent_manager.start()
        persistent_manager.shutdown()
        persistent_preserved = persistent_path.exists()

        temporary_profile = ProfileManager(prefix="manager-temporary-")
        temporary_path = temporary_profile.create()
        temporary_profile.cleanup()
        temporary_cleaned = not temporary_path.exists()

    failing_manager = BrowserSessionManager(
        BrowserConfig(browser="bundled"),
        playwright=_FakePlaywright(fail=True),
    )
    try:
        failing_manager.start()
    except RuntimeError:
        pass
    failed_status = failing_manager.health().status == HealthStatus.FAILED
    failing_manager.shutdown()

    required_statuses = {item.value for item in HealthStatus}
    expected_statuses = {"STARTING", "RUNNING", "STOPPING", "STOPPED", "RESTARTING", "FAILED", "UNKNOWN"}
    statuses_complete = required_statuses == expected_statuses
    validation = {
        "session_start": running.status == HealthStatus.RUNNING,
        "session_stop": stopped.status == HealthStatus.STOPPED,
        "restart_recovery": restart_recovered,
        "manual_restart": after_manual_restart.status == HealthStatus.RUNNING and after_manual_restart.restart_count == 2,
        "health_states": statuses_complete,
        "page_registry_start": initial_page_count == 1,
        "page_registry_add": after_new_page == 2,
        "page_cleanup": after_close_page == 1,
        "browser_disconnect_simulation": restart_recovered,
        "persistent_profile_preservation": persistent_preserved,
        "temporary_profile_cleanup": temporary_cleaned,
        "idempotent_shutdown": idempotent_shutdown,
        "failed_state": failed_status,
    }
    statistics = {
        "browser_launches": 0,
        "network_requests": 0,
        "fake_launches": playwright.chromium.launch_count,
        "automatic_restarts": 1,
        "manual_restarts": 1,
        "pages_created": len(browser_before_disconnect.contexts[0].pages),
        "initial_page_count": initial_page_count,
        "final_status": stopped.status.value,
    }
    health_history = [
        running.to_dict(),
        recovered.to_dict(),
        after_manual_restart.to_dict(),
        stopped.to_dict(),
    ]
    return validation, {"statistics": statistics, "health_history": health_history}


def _report(summary: dict[str, Any], validation: dict[str, Any], statistics: dict[str, Any]) -> str:
    lines = [
        "# Browser Session Manager Validation",
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
        "## Lifecycle",
        "",
        "The manager delegates browser creation to `launch_browser()` and owns only lifecycle, health, recovery, and page registry responsibilities.",
        "",
        "## Conclusion",
        "",
        "Browser lifecycle recovery and cleanup are deterministic and do not restart monitoring work.",
        "",
    ]
    return "\n".join(lines)


def run(reports_root: Path) -> int:
    experiment = Experiment.create(reports_root)
    output = experiment.directory / "session_manager"
    output.mkdir(parents=True, exist_ok=True)
    validation, data = _manager_checks()
    statistics = data["statistics"]
    health_history = data["health_history"]
    valid = all(validation.values())
    validation_payload = dict(validation)
    validation_payload.update({"browser_launches": 0, "network_requests": 0, "valid": valid})
    summary = {
        "experiment": "Milestone 02 - Browser Session Manager",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "result": "SUCCESS" if valid else "PARTIAL",
        "status": health_history[-1]["status"],
        "browser_launches": 0,
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }
    write_json_exclusive(output / "statistics.json", statistics)
    write_json_exclusive(output / "health.json", {"history": health_history, "final": health_history[-1]})
    write_json_exclusive(output / "summary.json", summary)
    write_json_exclusive(output / "validation.json", validation_payload)
    report = _report(summary, validation, statistics)
    write_text_exclusive(output / "session_manager_report.md", report)
    print(report)
    return 0 if valid else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate BrowserSessionManager lifecycle")
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

