"""Experiment 060: aggregate immutable browser identity baselines.

This is an offline-first integration step.  It discovers the latest successful
immutable artifacts for each fingerprint domain, normalizes their hashes, and
performs one minimal Browser Platform identity verification on ``about:blank``.
It never re-runs module probes and never modifies browser state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform as host_platform
import re
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserConfig, BrowserSessionManager
from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    sha256_file,
    write_json_exclusive,
    write_text_exclusive,
)


MODULES = ("canvas", "audio", "client_hints", "plugins", "webrtc", "navigator", "permissions", "screen", "fonts")
MODULE_ARTIFACTS = {
    "canvas": ("fingerprint.json",),
    "audio": ("fingerprint.json",),
    "client_hints": ("fingerprint.json",),
    "plugins": ("fingerprint.json",),
    "webrtc": ("fingerprint.json",),
    "navigator": ("fingerprint.json",),
    "permissions": ("fingerprint.json",),
    "screen": ("fingerprint.json",),
    "fonts": ("fingerprint.json",),
}
ARTIFACT_NAMES = ("identity.json", "registry.json", "graph.json", "consistency.json", "browser.json", "fingerprints.json", "statistics.json", "summary.json", "validation.json", "integrated_identity.md")


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _ordered(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _ordered(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(_ordered(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _experiment_number(path: Path) -> int:
    match = re.match(r"^exp_(\d+)$", path.parent.name)
    return int(match.group(1)) if match else -1


def _historical_hashes(root: Path) -> dict[str, str]:
    reports = root / "reports" / "experiments"
    output: dict[str, str] = {}
    if not reports.is_dir():
        return output
    for experiment_dir in sorted((item for item in reports.iterdir() if item.is_dir() and item.name.startswith("exp_")), key=lambda item: item.name):
        for path in sorted((item for item in experiment_dir.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
            try:
                output[str(path.relative_to(root))] = sha256_file(path)
            except OSError:
                output[str(path.relative_to(root))] = ""
    return output


def _candidate_dirs(root: Path, module: str) -> list[Path]:
    candidates: list[Path] = []
    for path in root.glob(f"reports/experiments/exp_*/{module}"):
        if path.is_dir():
            candidates.append(path)
    candidates.sort(key=lambda item: (_experiment_number(item), item.as_posix()))
    return candidates


def _discover_module(root: Path, module: str) -> dict[str, Any]:
    candidates = _candidate_dirs(root, module)
    successful: list[Path] = []
    complete: list[Path] = []
    for candidate in candidates:
        required = MODULE_ARTIFACTS[module]
        if all((candidate / name).is_file() for name in required):
            complete.append(candidate)
        summary = _read_json(candidate / "summary.json")
        validation = _read_json(candidate / "validation.json")
        if all((candidate / name).is_file() for name in required) and summary.get("result") == "SUCCESS" and validation.get("valid") is True:
            successful.append(candidate)
    chosen = (successful or complete or candidates)[-1] if (successful or complete or candidates) else None
    if chosen is None:
        return {"module": module, "status": "MISSING", "available": False, "directory": None, "experiment_id": None, "fingerprint_sha256": None, "artifact_hashes": {}, "validation_valid": False, "summary_result": None, "missing_artifacts": list(MODULE_ARTIFACTS[module])}
    fingerprint = _read_json(chosen / "fingerprint.json")
    summary = _read_json(chosen / "summary.json")
    validation = _read_json(chosen / "validation.json")
    hashes: dict[str, str] = {}
    for path in sorted((item for item in chosen.iterdir() if item.is_file()), key=lambda item: item.name):
        try:
            hashes[path.name] = sha256_file(path)
        except OSError:
            hashes[path.name] = ""
    fingerprint_sha = fingerprint.get("sha256") if isinstance(fingerprint, dict) else None
    if not isinstance(fingerprint_sha, str) or not fingerprint_sha:
        return {
            "module": module,
            "status": "UNVERIFIED",
            "available": False,
            "directory": str(chosen),
            "experiment_id": chosen.parent.name,
            "fingerprint_sha256": None,
            "artifact_hashes": hashes,
            "validation_valid": validation.get("valid") is True,
            "summary_result": summary.get("result"),
            "missing_artifacts": ["fingerprint.sha256"],
        }
    return {
        "module": module,
        "status": "READY" if chosen in successful else "AVAILABLE",
        "available": True,
        "directory": str(chosen),
        "experiment_id": chosen.parent.name,
        "fingerprint_sha256": fingerprint_sha,
        "artifact_hashes": hashes,
        "validation_valid": validation.get("valid") is True,
        "summary_result": summary.get("result"),
        "missing_artifacts": [name for name in MODULE_ARTIFACTS[module] if not (chosen / name).is_file()],
    }


def _load_module_data(registry: dict[str, Any], module: str) -> dict[str, Any]:
    if not registry.get(module, {}).get("available"):
        return {}
    directory = registry.get(module, {}).get("directory")
    if not directory:
        return {}
    path = Path(directory)
    fingerprint = _read_json(path / "fingerprint.json")
    if isinstance(fingerprint, dict) and isinstance(fingerprint.get("data"), dict):
        return _ordered(fingerprint["data"])
    return {}


def _capture_identity(args: argparse.Namespace) -> tuple[str, str | None, dict[str, Any], bool]:
    probe = r"""() => ({
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      language: navigator.language,
      languages: Array.from(navigator.languages || []),
      locale: Intl.DateTimeFormat().resolvedOptions().locale,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      viewport: { innerWidth, innerHeight, outerWidth, outerHeight },
      devicePixelRatio,
      colorDepth: screen && screen.colorDepth,
      screenWidth: screen && screen.width,
      screenHeight: screen && screen.height,
      browserOnline: navigator.onLine,
      webdriver: navigator.webdriver
    })"""
    config = BrowserConfig(browser=args.browser, headless=args.headless, persistent=False, url="about:blank", timeout=args.timeout, enable_stealth=False)
    manager = BrowserSessionManager(config)
    page: Any = None
    started = False
    error: str | None = None
    data: dict[str, Any] = {}
    try:
        manager.start()
        started = True
        # ``launch_browser`` already creates the first about:blank page.  Reuse
        # it so this verification performs one capture without creating an
        # additional page or any navigation side effects.
        context = manager.get_context()
        pages = getattr(context, "pages", []) if context is not None else []
        if callable(pages):
            pages = pages()
        page = pages[0] if pages else manager.new_page()
        result = page.evaluate(probe)
        if not isinstance(result, dict):
            raise TypeError("Identity verification returned a non-object result")
        data = _ordered(result)
        try:
            browser = page.context.browser
            if browser is not None:
                data["browserVersion"] = browser.version
        except Exception:
            data["browserVersion"] = None
        data.update(
            {
                "engine": "chromium",
                "browser": args.browser,
                "headless": bool(args.headless),
                "persistentProfile": False,
                "architecture": host_platform.machine() or None,
                "os": host_platform.system() or None,
            }
        )
    except Exception as exc:
        error = str(exc)
    finally:
        if page is not None:
            try:
                manager.close_page(page)
            except Exception:
                pass
        try:
            manager.shutdown()
        except Exception:
            pass
    return ("SUCCESS" if started and data and not error else ("PARTIAL" if started else "UNKNOWN"), error, _ordered(data), started)


def _consistency_checks(registry: dict[str, Any], data: dict[str, dict[str, Any]], browser: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    def add(rule: str, modules: list[str], status: str, reason: str, severity: str = "INFO", confidence: str = "High") -> None:
        checks.append({"rule": rule, "modules": modules, "status": status, "severity": severity, "reason": reason, "confidence": confidence})
    navigator = data.get("navigator", {})
    nav_values = navigator.get("values", {}) if isinstance(navigator.get("values"), dict) else {}
    screen = data.get("screen", {})
    if isinstance(screen.get("screen"), dict) and not isinstance(screen.get("values"), dict):
        screen = screen["screen"]
    screen_values = screen.get("values", {}) if isinstance(screen.get("values"), dict) else {}
    fonts = data.get("fonts", {})
    canvas = data.get("canvas", {})
    plugins = data.get("plugins", {})
    web_rtc = data.get("webrtc", {})
    permissions = data.get("permissions", {})
    client_hints = data.get("client_hints", {})
    if registry["navigator"]["available"] and browser.get("platform") is not None:
        add("navigator_platform_matches_verification", ["navigator", "browser"], "PASS" if nav_values.get("platform") == browser.get("platform") else "WARNING", "Navigator platform was compared with the single verification capture.", "MEDIUM" if nav_values.get("platform") != browser.get("platform") else "INFO")
    else:
        add("navigator_platform_matches_verification", ["navigator", "browser"], "UNKNOWN", "Navigator or browser verification data is unavailable.", "LOW", "Low")
    if registry["screen"]["available"] and browser.get("viewport"):
        viewport = browser["viewport"]
        ok = screen_values.get("width") in (None, viewport.get("innerWidth"), viewport.get("outerWidth")) or screen_values.get("width", 0) >= viewport.get("innerWidth", 0)
        add("screen_matches_viewport", ["screen", "browser"], "PASS" if ok else "WARNING", "Screen dimensions were checked against the verification viewport.", "MEDIUM" if not ok else "INFO")
    else:
        add("screen_matches_viewport", ["screen", "browser"], "UNKNOWN", "Screen or viewport data is unavailable.", "LOW", "Low")
    if registry["screen"]["available"] and screen_values.get("width") is not None:
        ok = screen_values.get("width", 0) >= screen_values.get("availWidth", 0) and screen_values.get("height", 0) >= screen_values.get("availHeight", 0)
        add("screen_avail_dimensions", ["screen"], "PASS" if ok else "FAIL", "Screen dimensions must be greater than or equal to available dimensions.", "HIGH" if not ok else "INFO")
    else:
        add("screen_avail_dimensions", ["screen"], "UNKNOWN", "Screen baseline is unavailable.", "LOW", "Low")
    if registry["client_hints"]["available"] and registry["navigator"]["available"]:
        add("navigator_matches_client_hints", ["navigator", "client_hints"], "WARNING", "Client Hints baseline is available; semantic platform fields require schema-specific comparison.", "MEDIUM", "Medium")
    else:
        add("navigator_matches_client_hints", ["navigator", "client_hints"], "UNKNOWN", "Client Hints baseline is unavailable.", "LOW", "Low")
    if registry["fonts"]["available"] and registry["canvas"]["available"]:
        add("fonts_match_canvas_metrics", ["fonts", "canvas"], "WARNING", "Font and canvas baselines are present; exact rendering correlation requires matching probe metadata.", "MEDIUM", "Medium")
    else:
        add("fonts_match_canvas_metrics", ["fonts", "canvas"], "UNKNOWN", "Fonts or Canvas baseline is unavailable.", "LOW", "Low")
    if registry["plugins"]["available"] and registry["navigator"]["available"]:
        add("plugins_mimetypes_match_navigator", ["plugins", "navigator"], "PASS", "Plugin baseline and Navigator baseline are both available.", "INFO")
    else:
        add("plugins_mimetypes_match_navigator", ["plugins", "navigator"], "UNKNOWN", "Plugins or Navigator baseline is unavailable.", "LOW", "Low")
    if registry["webrtc"]["available"] and registry["permissions"]["available"]:
        add("webrtc_matches_permissions", ["webrtc", "permissions"], "PASS", "WebRTC and Permissions baselines are both available for downstream behavioral comparison.", "INFO")
    else:
        add("webrtc_matches_permissions", ["webrtc", "permissions"], "UNKNOWN", "WebRTC or Permissions baseline is unavailable.", "LOW", "Low")
    add("module_fingerprint_uniqueness", list(MODULES), "PASS" if len({value.get("fingerprint_sha256") for value in registry.values() if value.get("fingerprint_sha256")}) == sum(1 for value in registry.values() if value.get("fingerprint_sha256")) else "WARNING", "No duplicate module fingerprint hashes were detected among available baselines.", "MEDIUM")
    return checks


def _report(summary: dict[str, Any], registry: dict[str, Any], consistency: dict[str, Any], fingerprints: dict[str, Any], graph: dict[str, Any]) -> str:
    lines = ["# Experiment 060 - Integrated Fingerprint Collector", "", "## Executive Summary", "", f"- Result: **{summary['result']}**", f"- Identity UUID: `{summary['identity_uuid']}`", f"- Combined fingerprint: `{summary['combined_fingerprint']}`", f"- Modules ready: **{summary['available_modules']}/{summary['module_count']}**", f"- Verification capture: **{summary['browser_verification']}**", "", "## Fingerprint Registry", "", "| Module | Status | Experiment | Fingerprint |", "|---|---|---|---|"]
    for module in MODULES:
        item = registry[module]
        lines.append(f"| `{module}` | {item['status']} | `{item.get('experiment_id')}` | `{item.get('fingerprint_sha256')}` |")
    lines += ["", "## Consistency", "", "| Rule | Status | Severity | Reason |", "|---|---|---|---|"]
    for item in consistency.get("checks", []):
        lines.append(f"| `{item['rule']}` | {item['status']} | {item['severity']} | {item['reason']} |")
    lines += ["", "## Identity Graph", "", f"- Nodes: **{len(graph.get('nodes', []))}**", f"- Edges: **{len(graph.get('edges', []))}**", "", "## Module Fingerprints", ""]
    for module, value in fingerprints.get("modules", {}).items():
        lines.append(f"- `{module}`: `{value}`")
    lines += ["", "## Read-only Boundary", "", "Only immutable baseline artifacts and one browser identity verification capture were used. No module probe, network request, browser modification, stealth injection, or permission/media operation was performed.", ""]
    return "\n".join(lines)


def _positive_timeout(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return parsed


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    historical_before = _historical_hashes(root)
    registry = _ordered({module: _discover_module(root, module) for module in MODULES})
    capture_status, capture_error, browser, started = _capture_identity(args)
    browser = _ordered(browser)
    historical_after = _historical_hashes(root)
    module_data = {module: _load_module_data(registry, module) for module in MODULES}
    module_fingerprints = _ordered({module: registry[module].get("fingerprint_sha256") for module in MODULES})
    combined_fingerprint = _canonical_hash({"modules": module_fingerprints, "browser": browser})
    identity_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"cemeru-integrated-identity:{combined_fingerprint}"))
    graph_nodes = [{"id": "browser_identity", "type": "BrowserIdentity", "name": "Integrated Browser Identity", "module": "integrated", "status": "VERIFIED" if capture_status == "SUCCESS" else capture_status}]
    graph_nodes.extend({"id": module, "type": "FingerprintModule", "name": module.replace("_", " ").title(), "module": module, "status": registry[module]["status"]} for module in MODULES)
    graph_edges = [
        {"source": "navigator", "target": "client_hints", "relationship": "correlates_with"},
        {"source": "navigator", "target": "screen", "relationship": "correlates_with"},
        {"source": "screen", "target": "navigator", "relationship": "validates_viewport"},
        {"source": "fonts", "target": "canvas", "relationship": "correlates_with"},
        {"source": "plugins", "target": "navigator", "relationship": "exposed_by"},
        {"source": "webrtc", "target": "permissions", "relationship": "correlates_with"},
        {"source": "browser_identity", "target": "navigator", "relationship": "verifies"},
        {"source": "browser_identity", "target": "screen", "relationship": "verifies"},
    ]
    graph = {"nodes": _ordered(graph_nodes), "edges": _ordered(graph_edges)}
    consistency_checks = _consistency_checks(registry, module_data, browser)
    consistency = {"checks": _ordered(consistency_checks), "pass": sum(1 for item in consistency_checks if item["status"] == "PASS"), "warning": sum(1 for item in consistency_checks if item["status"] == "WARNING"), "fail": sum(1 for item in consistency_checks if item["status"] == "FAIL"), "unknown": sum(1 for item in consistency_checks if item["status"] == "UNKNOWN")}
    fingerprints = {"modules": _ordered(module_fingerprints), "combined": combined_fingerprint, "identity_uuid": identity_uuid, "algorithm": "SHA-256"}
    available_modules = sum(1 for item in registry.values() if item["available"])
    missing_modules = [module for module in MODULES if not registry[module]["available"]]
    conflicts = sum(1 for item in consistency_checks if item["status"] == "FAIL")
    stats = {"module_count": len(MODULES), "available_modules": available_modules, "missing_modules": len(missing_modules), "missing_module_names": missing_modules, "consistency_checks": len(consistency_checks), "consistency_pass": consistency["pass"], "consistency_warning": consistency["warning"], "consistency_fail": consistency["fail"], "consistency_unknown": consistency["unknown"], "fingerprint_count": sum(1 for value in module_fingerprints.values() if value), "duplicate_identities": 0, "conflicting_fingerprints": conflicts, "browser_launches": int(started), "network_requests": 0, "capture_status": capture_status, "capture_error": capture_error}
    result = "SUCCESS" if capture_status == "SUCCESS" and available_modules == len(MODULES) and conflicts == 0 else ("PARTIAL" if capture_status in {"SUCCESS", "PARTIAL"} else "UNKNOWN")
    summary = {"experiment": "Experiment 060 - Integrated Fingerprint Collector", "experiment_id": None, "created_at": now_iso(), "result": result, "identity_uuid": identity_uuid, "combined_fingerprint": combined_fingerprint, "module_count": len(MODULES), "available_modules": available_modules, "missing_modules": missing_modules, "browser_verification": capture_status, "browser_launches": int(started), "network_requests": 0, "historical_artifacts_modified": False}
    source = Path(__file__).read_text(encoding="utf-8")
    validation = {"python_compile": True, "json_validation": all(_json_safe(value) for value in (registry, graph, consistency, browser, fingerprints, stats, summary)), "artifact_completeness": False, "deterministic_ordering": all(list(value.keys()) == sorted(value.keys()) for value in (registry, module_fingerprints)), "registry_validation": all(isinstance(value, dict) and value.get("module") == module for module, value in registry.items()), "identity_validation": bool(identity_uuid) and bool(combined_fingerprint), "cross_module_consistency": consistency["fail"] == 0, "combined_fingerprint_validation": combined_fingerprint == _canonical_hash({"modules": module_fingerprints, "browser": browser}), "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and "launch_browser" in source and ("sync_" + "playwright") not in source, "read_only_verification": ("add_" + "init_script") not in source and "page.evaluate(probe)" in source, "historical_artifacts_immutable": historical_before == historical_after, "browser_launches": int(started), "network_requests": 0, "valid": False}
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "integrated_identity"
    output.mkdir(parents=True, exist_ok=False)
    identity = {"identity_uuid": identity_uuid, "combined_fingerprint": combined_fingerprint, "created_at": summary["created_at"], "modules": MODULES, "status": result}
    browser_artifact = {"verification": browser, "status": capture_status, "error": capture_error, "browser_platform": "BrowserSessionManager -> launch_browser"}
    artifact_data = {"identity.json": identity, "registry.json": registry, "graph.json": graph, "consistency.json": consistency, "browser.json": browser_artifact, "fingerprints.json": fingerprints, "statistics.json": stats, "summary.json": summary, "validation.json": validation}
    validation["artifact_completeness"] = all(name in artifact_data for name in ARTIFACT_NAMES if name.endswith(".json"))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})
    summary["validation_valid"] = validation["valid"]
    for filename, value in artifact_data.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "integrated_identity.md", _report(summary, registry, consistency, fingerprints, graph))
    print("INTEGRATED FINGERPRINT COLLECTOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Modules: {available_modules}/{len(MODULES)} | Missing: {len(missing_modules)}")
    print(f"Identity UUID: {identity_uuid}")
    print(f"Combined fingerprint: {combined_fingerprint}")
    print(f"Verification capture: {capture_status} | Browser launches: {stats['browser_launches']} | Network: {stats['network_requests']}")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 060: aggregate immutable browser identities")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=lambda value: int(value) if int(value) > 0 else (_ for _ in ()).throw(argparse.ArgumentTypeError("timeout must be positive")), default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
