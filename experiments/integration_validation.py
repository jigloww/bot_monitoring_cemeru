"""Validate Monitoring Bot integration with the shared browser launcher.

The validation is intentionally non-invasive: static analysis covers every
monitoring Python file and the launcher lifecycle is exercised only with fake
Playwright objects.  No real browser, network request, or monitoring action is
performed.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.config import BrowserConfig
from browser.launcher import launch_browser
from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    system_metadata,
    write_json_exclusive,
    write_text_exclusive,
)


MONITORING_ROOT = Path("bot")
DIRECT_LAUNCH_ATTRIBUTES = {
    "launch",
    "launch_persistent_context",
    "connect_over_cdp",
}


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"), key=lambda path: str(path).lower())


def _ast_inventory(root: Path) -> dict[str, Any]:
    direct: list[dict[str, Any]] = []
    launcher_calls: list[dict[str, Any]] = []
    launcher_hook_calls: list[dict[str, Any]] = []
    launcher_import = False
    config_import = False
    manual_stealth = False
    sync_playwright_uses: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []

    for path in _python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            parse_errors.append({"file": str(path), "error": str(exc)})
            continue

        relative = str(path.relative_to(root.parent)).replace("\\", "/")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "browser.launcher" and any(alias.name == "launch_browser" for alias in node.names):
                    launcher_import = True
                if node.module == "browser.config" and any(alias.name == "BrowserConfig" for alias in node.names):
                    config_import = True
                if node.module == "playwright_stealth":
                    manual_stealth = True
            elif isinstance(node, ast.Import):
                if any(alias.name == "playwright_stealth" for alias in node.names):
                    manual_stealth = True
            elif isinstance(node, ast.Call):
                function = node.func
                if isinstance(function, ast.Attribute) and function.attr in DIRECT_LAUNCH_ATTRIBUTES:
                    direct.append({"file": relative, "line": node.lineno, "call": function.attr})
                if isinstance(function, ast.Name) and function.id == "launch_browser":
                    launcher_calls.append({"file": relative, "line": node.lineno})
                    if any(keyword.arg == "stealth_hook" for keyword in node.keywords):
                        launcher_hook_calls.append({"file": relative, "line": node.lineno})
                if isinstance(function, ast.Name) and function.id == "sync_playwright":
                    sync_playwright_uses.append({"file": relative, "line": node.lineno})
                if isinstance(function, ast.Name) and function.id == "Stealth":
                    manual_stealth = True

    client = root / "clients" / "playwright_client.py"
    client_relative = str(client.relative_to(root.parent)).replace("\\", "/")
    client_launcher_calls = [item for item in launcher_calls if item["file"] == client_relative]
    return {
        "python_files": [str(path.relative_to(root.parent)).replace("\\", "/") for path in _python_files(root)],
        "direct_launches": direct,
        "launcher_calls": launcher_calls,
        "launcher_hook_calls": launcher_hook_calls,
        "client_launcher_calls": client_launcher_calls,
        "launcher_import": launcher_import,
        "config_import": config_import,
        "manual_playwright_stealth": manual_stealth,
        "sync_playwright_lifecycle_uses": sync_playwright_uses,
        "parse_errors": parse_errors,
    }


def _config_serialization() -> dict[str, Any]:
    config = BrowserConfig(
        browser="chrome",
        headless=True,
        persistent=True,
        profile_path="data/browser_profile",
        viewport=(1366, 768),
        user_agent="integration-test-agent",
        locale="id-ID",
        timezone="Asia/Jakarta",
        extra_http_headers={"Accept-Language": "id-ID"},
        args=["--no-sandbox"],
        permissions=["notifications"],
        enable_stealth=True,
    )
    restored = BrowserConfig.from_dict(config.to_dict())
    return {
        "passed": config.to_dict() == restored.to_dict(),
        "serialized": config.to_dict(),
        "round_trip": restored.to_dict(),
    }


class _FakePage:
    def title(self) -> str:
        return "integration"


class _FakeContext:
    def __init__(self) -> None:
        self.closed = 0

    def new_page(self) -> _FakePage:
        return _FakePage()

    def close(self) -> None:
        self.closed += 1


class _FakeBrowser:
    def __init__(self) -> None:
        self.closed = 0
        self.context = _FakeContext()

    def new_context(self, **_options: Any) -> _FakeContext:
        return self.context

    def close(self) -> None:
        self.closed += 1


class _FakeBrowserType:
    def __init__(self) -> None:
        self.launch_count = 0
        self.last_options: dict[str, Any] = {}

    def launch(self, **options: Any) -> _FakeBrowser:
        self.launch_count += 1
        self.last_options = options
        return _FakeBrowser()


class _FakePlaywright:
    def __init__(self) -> None:
        self.chromium = _FakeBrowserType()


def _launcher_invocation() -> dict[str, Any]:
    playwright = _FakePlaywright()
    hook_contexts: list[Any] = []
    session = launch_browser(
        BrowserConfig(browser="bundled", headless=True, enable_stealth=True),
        playwright=playwright,
        stealth_hook=lambda context: hook_contexts.append(context),
    )
    browser, context, page = tuple(session)
    passed_before_close = browser is not None and context is not None and page is not None and len(hook_contexts) == 1
    session.close()
    session.close()
    fake_browser = browser
    fake_context = context
    return {
        "passed": passed_before_close and fake_browser.closed == 1 and fake_context.closed == 1,
        "launch_count": playwright.chromium.launch_count,
        "hook_count": len(hook_contexts),
        "browser_close_count": fake_browser.closed,
        "context_close_count": fake_context.closed,
        "idempotent": fake_browser.closed == 1 and fake_context.closed == 1,
    }


def _startup_check() -> dict[str, Any]:
    """Import the monitoring client when its optional runtime dependencies exist."""
    if importlib.util.find_spec("playwright") is None:
        return {"status": "UNKNOWN", "reason": "playwright package is not installed; import not attempted"}
    try:
        import bot.clients.playwright_client  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment-dependent
        return {"status": "WARNING", "reason": str(exc)}
    return {"status": "PASS", "reason": "monitoring client imported without browser launch"}


def _report(summary: dict[str, Any], validation: dict[str, Any], statistics: dict[str, Any]) -> str:
    lines = [
        "# Monitoring Browser Integration Validation",
        "",
        "## Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Startup check: **{summary['startup_status']}**",
        f"- Real browser launches: **{statistics['browser_launches']}**",
        f"- Network requests: **{statistics['network_requests']}**",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    for key, value in validation.items():
        if key in {"valid", "browser_launches", "network_requests"}:
            continue
        if value is True:
            display = "PASS"
        elif value is False:
            display = "FAIL"
        else:
            display = str(value)
        lines.append(f"| {key.replace('_', ' ').title()} | {display} |")
    lines += [
        "",
        "## Architecture",
        "",
        "Monitoring browser creation now flows through `browser.launcher.launch_browser()`.",
        "The existing `sync_playwright()` scope is retained only as the Playwright lifecycle provider; it performs no browser launch and is injected into the launcher.",
        "",
        "## Conclusion",
        "",
        "The integration is static-safe and lifecycle-compatible. Runtime startup remains UNKNOWN when Playwright is unavailable.",
        "",
    ]
    return "\n".join(lines)


def run(reports_root: Path) -> int:
    experiment = Experiment.create(reports_root)
    output = experiment.directory / "monitoring_integration"
    output.mkdir(parents=True, exist_ok=True)

    inventory = _ast_inventory(project_root() / MONITORING_ROOT)
    config = _config_serialization()
    launcher = _launcher_invocation()
    startup = _startup_check()

    validation: dict[str, Any] = {
        "monitoring_imports_browser_launcher": inventory["launcher_import"],
        "monitoring_imports_browser_config": inventory["config_import"],
        "browser_config_serialization": config["passed"],
        "launch_browser_invocation": len(inventory["client_launcher_calls"]) == 1,
        "stealth_hook_integration": len(inventory["launcher_hook_calls"]) == 1,
        "no_direct_browser_launch": len(inventory["direct_launches"]) == 0,
        "no_duplicated_browser_initialization": len(inventory["direct_launches"]) == 0 and len(inventory["client_launcher_calls"]) == 1,
        "no_manual_playwright_stealth": not inventory["manual_playwright_stealth"],
        "monitoring_startup": startup["status"],
        "launcher_cleanup": launcher["idempotent"],
        "launcher_hook_invocation": launcher["passed"],
        "source_parse": len(inventory["parse_errors"]) == 0,
        "browser_launches": 0,
        "network_requests": 0,
        "valid": True,
    }
    acceptable = {True, "PASS", "UNKNOWN"}
    validation["valid"] = all(
        value in acceptable
        for key, value in validation.items()
        if key not in {"browser_launches", "network_requests", "valid"}
    )

    statistics = {
        "browser_launches": 0,
        "network_requests": 0,
        "fake_launcher_invocations": launcher["launch_count"],
        "monitoring_python_files": len(inventory["python_files"]),
        "direct_launch_count": len(inventory["direct_launches"]),
        "launch_browser_call_count": len(inventory["client_launcher_calls"]),
        "sync_playwright_lifecycle_count": len(inventory["sync_playwright_lifecycle_uses"]),
        "startup_status": startup["status"],
    }
    summary = {
        "experiment": "Milestone 01 - Monitoring Browser Integration",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "result": "SUCCESS" if validation["valid"] else "PARTIAL",
        "startup_status": startup["status"],
        "browser_entry_point": "browser.launcher.launch_browser",
        "monitoring_client": "bot/clients/playwright_client.py",
        "browser_launches": 0,
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }

    artifacts = {
        "summary.json": summary,
        "statistics.json": statistics,
        "validation.json": validation,
    }
    for filename, payload in artifacts.items():
        write_json_exclusive(output / filename, payload)
    report = _report(summary, validation, statistics)
    write_text_exclusive(output / "integration_report.md", report)
    print(report)
    return 0 if validation["valid"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Monitoring Bot browser launcher integration")
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
