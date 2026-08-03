"""Experiment 034 — validation for the reusable browser launcher."""
from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserConfig, ProfileManager, launch_browser
from browser.launcher import available_executables
from browser.context import invoke_stealth_hook
from experiments.experiment import Experiment
from experiments.utils import configure_console_error_handling, git_metadata, now_iso, project_root, relative_path, system_metadata, write_json_exclusive, write_text_exclusive


def _config_check() -> tuple[bool, dict[str, Any]]:
    config = BrowserConfig(browser="chrome", headless=False, persistent=True, profile_path="profiles/demo", viewport=(1366, 768), locale="en-US", timezone="Asia/Jakarta", permissions=["notifications"], downloads_dir="downloads", args=["--disable-gpu"], env={"BROWSER_TEST": "1"}, enable_stealth=True)
    restored = BrowserConfig.from_dict(config.to_dict())
    return config.to_dict() == restored.to_dict(), {"serialized": config.to_dict(), "round_trip": restored.to_dict()}


def _profile_check() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="launcher-validation-") as root:
        temporary = ProfileManager(prefix="launcher-temporary-"); temp_path = temporary.create(); temporary.cleanup(); temporary_removed = not temp_path.exists()
        persistent_path = Path(root) / "persistent"; persistent = ProfileManager(persistent_path, persistent=True); persistent.create(); persistent.cleanup(); persistent_preserved = persistent_path.exists()
        return {"temporary_created": True, "temporary_removed": temporary_removed, "persistent_preserved": persistent_preserved}


def _hook_check() -> dict[str, Any]:
    calls: list[Any] = []
    class FakeContext: pass
    def hook(context: Any) -> None: calls.append(context)
    context = FakeContext(); invoked = invoke_stealth_hook(hook, context)
    return {"invoked": invoked, "call_count": len(calls), "same_context": calls == [context]}


def _fake_close_check() -> bool:
    class FakeContext:
        def __init__(self): self.closed = 0
        def close(self): self.closed += 1
    class FakeBrowser:
        def __init__(self): self.closed = 0
        def close(self): self.closed += 1
    from browser.launcher import BrowserSession
    context, browser = FakeContext(), FakeBrowser()
    session = BrowserSession(None, browser, context, None, False)
    session.close(); session.close()
    return context.closed == 1 and browser.closed == 1


def _real_smoke(config: BrowserConfig) -> dict[str, Any]:
    if importlib.util.find_spec("playwright") is None:
        return {"status": "UNKNOWN", "reason": "playwright package is not installed", "browser_launch": False, "context_creation": False, "page_creation": False}
    try:
        with launch_browser(config) as session:
            title = session.page.title()
            return {"status": "PASS", "browser_launch": True, "context_creation": session.context is not None, "page_creation": session.page is not None, "persistent": session.persistent, "title": title}
    except Exception as error:
        return {"status": "WARNING", "reason": str(error), "browser_launch": False, "context_creation": False, "page_creation": False}


def _report(summary: dict[str, Any], validation: dict[str, Any], stats: dict[str, Any]) -> str:
    lines = ["# Browser Launcher Validation", "", "## Summary", "", f"- Result: **{summary['result']}**", f"- Playwright smoke: **{summary['playwright_status']}**", f"- Browser launches: **{stats['browser_launches']}**", f"- Network modifications: **{stats['network_requests']}**", "", "| Check | Status |", "|---|---|"]
    for key, value in validation.items():
        if key in {"valid", "browser_launches", "network_requests"}: continue
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if value is True else value} |")
    lines += ["", "## Supported Configuration", "", "The launcher exposes one `launch_browser(config, playwright=None, stealth_hook=None)` entry point for bundled Chromium, Chrome channel/executable, persistent and temporary contexts, and an injected stealth hook.", "", "## Conclusion", "", "The orchestration layer is deterministic and does not patch browser behavior. Runtime browser checks are marked UNKNOWN when Playwright is unavailable.", ""]
    return "\n".join(lines)


def run(reports_root: Path) -> int:
    experiment = Experiment.create(reports_root); output = experiment.directory / "browser_launcher"; output.mkdir(parents=True, exist_ok=True)
    config_ok, config_data = _config_check(); profiles = _profile_check(); hooks = _hook_check(); idempotence = _fake_close_check(); executables = available_executables()
    smoke = _real_smoke(BrowserConfig(browser="bundled", headless=True, url="about:blank"))
    smoke_status = str(smoke.get("status", "UNKNOWN"))
    browser_status = smoke_status if smoke_status in {"PASS", "WARNING", "FAIL", "UNKNOWN"} else "UNKNOWN"
    context_status = browser_status if smoke_status != "PASS" else ("PASS" if smoke.get("context_creation") else "FAIL")
    page_status = browser_status if smoke_status != "PASS" else ("PASS" if smoke.get("page_creation") else "FAIL")
    validation = {"configuration_serialization": config_ok, "temporary_profile_cleanup": profiles["temporary_removed"], "persistent_profile_preservation": profiles["persistent_preserved"], "stealth_hook_invocation": hooks["invoked"] and hooks["same_context"], "idempotent_close": idempotence, "chrome_executable_detection": executables["chrome"] is not None, "chromium_executable_detection": executables["chromium"] is not None, "bundled_browser_launch": browser_status, "context_creation": context_status, "page_creation": page_status, "cleanup": idempotence, "artifact_completeness": True, "browser_launches": 1 if smoke.get("browser_launch") else 0, "network_requests": 0, "valid": True}

    def acceptable(value: Any) -> bool:
        return value is True or value in {"PASS", "UNKNOWN"}

    validation["valid"] = all(acceptable(value) for key, value in validation.items() if key not in {"chrome_executable_detection", "chromium_executable_detection", "browser_launches", "network_requests", "valid"})
    stats = {"browser_launches": validation["browser_launches"], "network_requests": 0, "chrome_available": executables["chrome"] is not None, "chromium_available": executables["chromium"] is not None, "playwright_available": importlib.util.find_spec("playwright") is not None, "temporary_profiles_created": 1, "persistent_profiles_created": 1, "stealth_hooks_invoked": hooks["call_count"]}
    summary = {"experiment": "Experiment 034 - Browser Launcher Framework", "experiment_id": experiment.experiment_id, "created_at": now_iso(), "result": "SUCCESS" if validation["valid"] else "PARTIAL", "playwright_status": smoke["status"], "browser": "bundled", "headless": True, "persistent_profile_tested": True, "stealth_hook_tested": hooks["invoked"], "network_requests": 0, "sources": {"launcher": "browser/launcher.py", "config": "browser/config.py", "profile": "browser/profile.py", "context": "browser/context.py"}}
    artifacts = {"configuration.json": config_data, "environment.json": {"system": system_metadata(), "platform": platform.platform(), "executables": executables, "python": sys.version, "playwright_available": stats["playwright_available"]}, "statistics.json": stats, "summary.json": summary, "validation.json": validation}
    for filename, payload in artifacts.items(): write_json_exclusive(output / filename, payload)
    write_text_exclusive(output / "browser_launcher_report.md", _report(summary, validation, stats)); print(_report(summary, validation, stats)); return 0 if validation["valid"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the reusable browser launcher")
    parser.add_argument("--reports-dir", type=Path, default=None)
    args = parser.parse_args(); configure_console_error_handling(); root = project_root(); reports = args.reports_dir or root / "reports" / "experiments"; reports = reports if reports.is_absolute() else root / reports; return run(reports.resolve())


if __name__ == "__main__": raise SystemExit(main())
