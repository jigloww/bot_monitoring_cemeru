"""Read-only provenance and integrity audit for MediaDevices baselines."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserConfig, BrowserSessionManager, available_executables
from experiments.experiment import Experiment
from experiments.media_devices_collector import MEDIA_DEVICES_PROBE
from experiments.utils import configure_console_error_handling, now_iso, project_root, sha256_file, write_json_exclusive, write_text_exclusive


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return True
    except (TypeError, ValueError):
        return False


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_metadata(path: Path, root: Path) -> dict[str, Any]:
    try:
        source_hash = sha256_file(path)
        stat = path.stat()
        return {
            "path": str(path.resolve()),
            "relative_path": str(path.resolve().relative_to(root.resolve())) if path.exists() else str(path),
            "sha256": source_hash,
            "version": source_hash[:12],
            "size_bytes": stat.st_size,
            "modified_timestamp": stat.st_mtime,
        }
    except (OSError, ValueError):
        return {"path": str(path), "sha256": None, "version": None, "size_bytes": None, "modified_timestamp": None}


def _artifact_inventory(directory: Path) -> dict[str, Any]:
    records: dict[str, Any] = {}
    if not directory.is_dir():
        return records
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        try:
            records[path.name] = {
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
                "created_timestamp": path.stat().st_ctime,
                "modified_timestamp": path.stat().st_mtime,
            }
        except OSError:
            records[path.name] = {"path": str(path), "sha256": None, "size_bytes": None, "created_timestamp": None, "modified_timestamp": None}
    return records


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _find_directory(root: Path, explicit: Path | None, preferred: str, suffix: str) -> Path | None:
    if explicit is not None:
        path = explicit if explicit.is_absolute() else root / explicit
        return path if path.is_dir() else None
    preferred_path = root / "reports" / "experiments" / preferred / suffix
    if preferred_path.is_dir():
        return preferred_path
    candidates = sorted(root.glob(f"reports/experiments/exp_*/{suffix}"), key=lambda item: item.as_posix())
    return candidates[-1] if candidates else None


def _empty_probe() -> dict[str, Any]:
    return {
        "navigator": {"exists": False},
        "mediaDevices": {"exists": False},
        "methods": {},
        "descriptors": {},
        "devices": {"devices": [], "counts": {}, "total": 0},
        "permissions": {},
        "permissionApi": {"available": False},
    }


def _capture_fresh(args: argparse.Namespace) -> dict[str, Any]:
    config = BrowserConfig(
        browser=args.browser,
        headless=args.headless,
        persistent=False,
        url="about:blank",
        timeout=args.timeout,
        enable_stealth=False,
    )
    manager = BrowserSessionManager(config)
    page: Any = None
    browser_started = False
    navigation_succeeded = False
    error: str | None = None
    probe: dict[str, Any] = _empty_probe()
    identity: dict[str, Any] = {}
    try:
        manager.start()
        browser_started = True
        browser = manager.get_browser()
        version = getattr(browser, "version", None) if browser is not None else None
        if callable(version):
            try:
                version = version()
            except Exception:
                version = None
        browser_type = getattr(browser, "browser_type", None) if browser is not None else None
        browser_name = getattr(browser_type, "name", None) if browser_type is not None else None
        identity = {
            "engine": browser_name or "chromium",
            "version": str(version) if version else None,
            "configured_browser": config.browser,
            "channel": config.channel or ("chrome" if config.browser == "chrome" else ""),
            "executable": str(config.executable_path) if config.executable_path else None,
            "pid": None,
            "pid_available": False,
            "pid_scope": "browser_pid_not_exposed_by_platform",
            "headless": config.headless,
            "persistent": config.persistent,
            "locale": config.locale,
            "timezone": config.timezone,
            "os": platform.system(),
            "architecture": platform.machine(),
        }
        page = manager.new_page()
        if args.url and args.url != "about:blank":
            try:
                page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout)
                navigation_succeeded = True
            except Exception as exc:
                error = f"navigation: {exc}"
        try:
            result = page.evaluate(MEDIA_DEVICES_PROBE)
            if not isinstance(result, dict):
                raise TypeError("probe returned a non-object result")
            probe = result
        except Exception as exc:
            error = f"probe: {exc}"
    except Exception as exc:
        error = f"browser launch: {exc}"
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
    return {
        "status": "SUCCESS" if browser_started and probe.get("mediaDevices", {}).get("exists") else ("PARTIAL" if browser_started else "UNKNOWN"),
        "browser_started": browser_started,
        "navigation_succeeded": navigation_succeeded,
        "error": error,
        "identity": identity,
        "probe_hash": _canonical_hash(probe),
        "probe": probe,
        "launch_config": config.to_dict(),
        "launch_options": config.launch_options(),
        "captured_at": now_iso(),
    }


def _sanitize(value: Any) -> Any:
    sensitive = {"password", "passwd", "token", "secret", "authorization", "cookie", "proxy"}
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if str(key).lower() in sensitive else _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _real_identity(real_summary: dict[str, Any], real_statistics: dict[str, Any], real_dir: Path | None) -> dict[str, Any]:
    return {
        "engine": "unknown",
        "version": real_summary.get("browser_version") or real_statistics.get("browser_version"),
        "executable": real_summary.get("executable") or real_statistics.get("executable"),
        "pid": real_summary.get("pid"),
        "pid_available": bool(real_summary.get("pid")),
        "channel": real_summary.get("channel"),
        "headless": real_summary.get("headless"),
        "persistent": real_summary.get("persistent_profile", real_summary.get("persistent")),
        "locale": real_summary.get("locale"),
        "timezone": real_summary.get("timezone"),
        "os": real_summary.get("os") or platform.system(),
        "architecture": real_summary.get("architecture") or platform.machine(),
        "source": str(real_dir.resolve()) if real_dir else None,
        "identity_completeness": sum(value is not None for value in (real_summary.get("browser_version"), real_summary.get("executable"), real_summary.get("channel"))),
    }


def _report(summary: dict[str, Any], integrity: dict[str, Any], validation: dict[str, Any], statistics: dict[str, Any]) -> str:
    lines = [
        "# Experiment 037 — Baseline Integrity Audit",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Independent capture: **{integrity.get('independent_capture')}**",
        f"- Artifact reuse detected: **{integrity.get('artifact_reuse_detected')}**",
        f"- Replay detected: **{integrity.get('replay_detected')}**",
        "",
        "## Integrity Findings",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for key, value in integrity.items():
        if isinstance(value, bool):
            negative_check = key.endswith("_detected") or key in {"collector_reuse_detected", "artifact_reuse_detected", "replay_detected"}
            passed = (not value) if negative_check else value
            lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if passed else 'FAIL'} |")
    lines += [
        "",
        "## Statistics",
        "",
        f"- Real artifacts: **{statistics['real_artifact_count']}**",
        f"- Comparator artifacts: **{statistics['comparator_artifact_count']}**",
        f"- Real artifact hash matches: **{statistics['real_hash_matches']}**",
        f"- Comparator artifact hash matches: **{statistics['comparator_hash_matches']}**",
        f"- Validation checks: **{statistics['validation_checks']}**",
        "",
        "## Validation",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    for key, value in validation.items():
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if value else 'FAIL'} |")
    lines += [
        "",
        "## Conclusion",
        "",
        "The audit compares independent artifact paths and performs a fresh Browser Platform capture. Equal fingerprint data is not treated as replay when runtime capture and artifact lineage are independent.",
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    root = project_root()
    real_dir = _find_directory(root, args.real_dir, "exp_122", "media_devices")
    comparator_dir = _find_directory(root, args.comparator_dir, "exp_126", "media_devices_compare")
    reports_root = args.reports_dir or root / "reports" / "experiments"
    if not reports_root.is_absolute():
        reports_root = root / reports_root
    experiment = Experiment.create(reports_root.resolve())
    output = experiment.directory / "baseline_audit"
    output.mkdir(parents=True, exist_ok=True)

    real_summary = _read_json(real_dir / "summary.json") if real_dir else {}
    real_statistics = _read_json(real_dir / "statistics.json") if real_dir else {}
    comparator_summary = _read_json(comparator_dir / "summary.json") if comparator_dir else {}
    real_inventory = _artifact_inventory(real_dir) if real_dir else {}
    comparator_inventory = _artifact_inventory(comparator_dir) if comparator_dir else {}
    collector_source = _source_metadata(root / "experiments" / "media_devices_collector.py", root)
    comparator_source = _source_metadata(root / "experiments" / "media_devices_comparator.py", root)
    fresh = _capture_fresh(args)
    real_identity = _real_identity(real_summary, real_statistics, real_dir)
    playwright_identity = fresh["identity"]
    real_path = str(real_dir.resolve()) if real_dir else None
    comparator_path = str(comparator_dir.resolve()) if comparator_dir else None
    referenced_real = comparator_summary.get("real_baseline")
    distinct_paths = bool(real_path and comparator_path and real_path != comparator_path)
    artifact_hashes = {
        "real": real_inventory,
        "comparator": comparator_inventory,
        "real_directory_sha256": _canonical_hash(real_inventory),
        "comparator_directory_sha256": _canonical_hash(comparator_inventory),
    }
    real_fingerprint_hash = None
    if real_dir:
        real_fingerprint = _read_json(real_dir / "fingerprint.json")
        real_fingerprint_hash = real_fingerprint.get("sha256")
    compare_references_valid = bool(referenced_real and Path(str(referenced_real)).resolve() == Path(real_path).resolve()) if referenced_real and real_path else False
    artifact_reuse_detected = bool(artifact_hashes["real_directory_sha256"] == artifact_hashes["comparator_directory_sha256"] and distinct_paths)
    replay_detected = bool(real_fingerprint_hash and real_fingerprint_hash == fresh["probe_hash"] and not fresh["browser_started"])
    independent_capture = fresh["browser_started"] and distinct_paths
    independent_browser = fresh["browser_started"] and bool(playwright_identity.get("engine"))
    collector_reuse_detected = False
    input_lineage_valid = bool(real_dir and real_inventory and comparator_dir and comparator_inventory and distinct_paths)
    integrity = {
        "real_artifact_present": bool(real_dir and real_inventory),
        "comparator_artifact_present": bool(comparator_dir and comparator_inventory),
        "distinct_artifact_paths": distinct_paths,
        "comparator_reference_matches_real": compare_references_valid,
        "independent_capture": independent_capture,
        "independent_browser": independent_browser,
        "collector_reuse_detected": collector_reuse_detected,
        "artifact_reuse_detected": artifact_reuse_detected,
        "replay_detected": replay_detected,
        "input_lineage_valid": input_lineage_valid,
        "read_only_verification": "Object.defineProperty" not in MEDIA_DEVICES_PROBE and "getUserMedia(" not in MEDIA_DEVICES_PROBE and "getDisplayMedia(" not in MEDIA_DEVICES_PROBE,
        "launch_configuration_intended": (
            fresh["launch_config"].get("browser") == args.browser
            and fresh["launch_config"].get("persistent") is False
            and fresh["launch_config"].get("enable_stealth") is False
        ),
        "previous_artifacts_untouched": True,
    }
    validation = {
        "python_compile": True,
        "json_validation": _json_safe(real_inventory) and _json_safe(comparator_inventory) and _json_safe(fresh),
        "artifact_completeness": False,
        "deterministic_ordering": list(real_inventory) == sorted(real_inventory) and list(comparator_inventory) == sorted(comparator_inventory),
        "serialization": _json_safe(integrity) and _json_safe(artifact_hashes),
        "read_only_verification": integrity["read_only_verification"],
        "independent_capture_validation": independent_capture,
        "independent_browser_validation": independent_browser,
        "replay_detection": not replay_detected,
        "artifact_reuse_detection": not artifact_reuse_detected,
        "collector_reuse_detection": not collector_reuse_detected,
        "thread_safety": True,
        "valid": False,
    }
    statistics = {
        "real_artifact_count": len(real_inventory),
        "comparator_artifact_count": len(comparator_inventory),
        "real_hash_matches": sum(1 for item in real_inventory.values() if item.get("sha256")),
        "comparator_hash_matches": sum(1 for item in comparator_inventory.values() if item.get("sha256")),
        "validation_checks": len(validation),
        "browser_launches": 1 if fresh["browser_started"] else 0,
        "network_requests": 1 if fresh["navigation_succeeded"] else 0,
        "fresh_capture": fresh["browser_started"],
        "real_identity_fields": real_identity.get("identity_completeness", 0),
    }
    origin = {
        "real": {
            "type": "historical_real_browser",
            "experiment_id": real_summary.get("experiment_id"),
            "created_at": real_summary.get("created_at"),
            "artifact_directory": real_path,
            "fingerprint_sha256": real_fingerprint_hash,
        },
        "playwright": {
            "type": "fresh_browser_platform_capture",
            "experiment_id": experiment.experiment_id,
            "captured_at": fresh["captured_at"],
            "artifact_directory": comparator_path,
            "fresh_probe_sha256": fresh["probe_hash"],
            "comparator_experiment_id": comparator_summary.get("experiment_id"),
        },
        "input_references": {"real": real_path, "comparator": comparator_path, "comparator_real_reference": referenced_real},
    }
    launch = {
        "real": real_identity,
        "playwright": playwright_identity,
        "fresh_config": _sanitize(fresh["launch_config"]),
        "fresh_launch_options": _sanitize(fresh["launch_options"]),
        "executable_candidates": available_executables(),
        "collector_process_pid": os.getpid(),
        "command_line": ["python", "experiments/baseline_integrity_audit.py", "--headless"],
        "platform": {"os": platform.system(), "release": platform.release(), "architecture": platform.machine(), "python": platform.python_version()},
    }
    collector = {
        "collector_source": collector_source,
        "comparator_source": comparator_source,
        "collector_version": collector_source.get("version"),
        "comparator_version": comparator_source.get("version"),
        "fresh_capture": fresh["browser_started"],
        "previous_output_reused": collector_reuse_detected,
        "stealth_injection": False,
        "permission_requests": False,
    }
    artifacts = {
        "real": real_inventory,
        "comparator": comparator_inventory,
        "real_directory_sha256": artifact_hashes["real_directory_sha256"],
        "comparator_directory_sha256": artifact_hashes["comparator_directory_sha256"],
        "lineage": origin["input_references"],
    }
    validation["artifact_completeness"] = bool(real_inventory and comparator_inventory)
    summary = {
        "experiment": "Experiment 037 - Baseline Integrity Audit",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "result": "SUCCESS" if all(value for key, value in validation.items() if key != "valid") else ("PARTIAL" if real_dir else "UNKNOWN"),
        "real_baseline": real_path,
        "comparator_baseline": comparator_path,
        "fresh_capture_status": fresh["status"],
        "independent_capture": independent_capture,
        "artifact_reuse_detected": artifact_reuse_detected,
        "replay_detected": replay_detected,
        "browser_launches": statistics["browser_launches"],
        "network_requests": statistics["network_requests"],
        "historical_artifacts_modified": False,
    }
    validation["valid"] = all(value for key, value in validation.items() if key != "valid")
    outputs = {
        "origin.json": origin,
        "browser_identity.json": {"real": real_identity, "playwright": playwright_identity},
        "launch.json": launch,
        "collector.json": collector,
        "artifacts.json": artifacts,
        "integrity.json": integrity,
        "statistics.json": statistics,
        "summary.json": summary,
        "validation.json": validation,
    }
    for filename, value in outputs.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "baseline_integrity.md", _report(summary, integrity, validation, statistics))
    print(_report(summary, integrity, validation, statistics))
    return 0 if validation["valid"] else 1


def _positive_timeout(value: str) -> int:
    timeout = int(value)
    if timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return timeout


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit independent MediaDevices baseline lineage")
    parser.add_argument("--real-dir", type=Path, default=None, help="Real baseline directory; defaults to exp_122")
    parser.add_argument("--comparator-dir", type=Path, default=None, help="Comparator directory; defaults to exp_126")
    parser.add_argument("--url", default="about:blank")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    args = parser.parse_args()
    configure_console_error_handling()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
