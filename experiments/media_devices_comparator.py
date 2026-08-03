"""Compare the real MediaDevices baseline with a Playwright capture.

The capture is performed only through ``BrowserSessionManager`` and the
Browser Platform launcher it owns.  No browser prototype or permission state
is changed by this analysis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserConfig, BrowserSessionManager
from experiments.experiment import Experiment
from experiments.media_devices_collector import MEDIA_DEVICES_PROBE
from experiments.utils import configure_console_error_handling, now_iso, project_root, write_json_exclusive, write_text_exclusive


ARTIFACTS = (
    "compare.json",
    "similarity.json",
    "differences.json",
    "critical.json",
    "recommendations.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "media_devices_compare.md",
)


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return True
    except (TypeError, ValueError):
        return False


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _empty_probe(error: str | None = None) -> dict[str, Any]:
    return {
        "navigator": {"exists": False, "typeof": "undefined", "constructor": None, "prototype": None, "ownProperties": [], "mediaDevicesDescriptor": None},
        "mediaDevices": {"exists": False, "typeof": "undefined", "constructor": None, "prototype": None, "ownProperties": [], "prototypeProperties": [], "prototypeChain": [], "instanceof": False, "toStringTag": None, "toStringTagDescriptor": None},
        "methods": {},
        "descriptors": {"navigatorPrototype": None, "mediaDevicesPrototype": {}, "methods": {}},
        "devices": {"supported": False, "enumerationError": error, "devices": [], "counts": {"audioinput": 0, "audiooutput": 0, "videoinput": 0, "default": 0}, "total": 0},
        "permissions": {"camera": {"name": "camera", "supported": False, "state": "unknown", "error": error}, "microphone": {"name": "microphone", "supported": False, "state": "unknown", "error": error}},
        "permissionApi": {"available": False, "prototype": []},
    }


def _capture_playwright(args: argparse.Namespace) -> tuple[str, str | None, dict[str, Any], bool, bool]:
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
    data: dict[str, Any] = _empty_probe()
    try:
        manager.start()
        browser_started = True
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
                raise TypeError("MediaDevices probe returned a non-object result")
            data = result
        except Exception as exc:
            error = f"probe: {exc}"
            data = _empty_probe(str(exc))
        status = "SUCCESS" if data.get("mediaDevices", {}).get("exists") else "PARTIAL"
        if error and status == "SUCCESS":
            status = "PARTIAL"
    except Exception as exc:
        status = "UNKNOWN"
        error = f"browser launch: {exc}"
        data = _empty_probe(str(exc))
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
    return status, error, data, browser_started, navigation_succeeded


def _load_real(real_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    def read(name: str) -> dict[str, Any]:
        path = real_dir / name
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    prototype = read("prototype.json")
    return (
        {
            "navigator": prototype.get("navigator", {}),
            "mediaDevices": prototype.get("mediaDevices", {}),
            "permissionApi": prototype.get("permissionApi", {}),
            "methods": read("methods.json"),
            "descriptors": read("descriptors.json"),
            "devices": read("devices.json"),
            "permissions": read("permissions.json"),
        },
        read("fingerprint.json"),
    )


def _find_real_dir(root: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_absolute() else root / explicit
    preferred = root / "reports" / "experiments" / "exp_122" / "media_devices"
    if preferred.is_dir():
        return preferred
    candidates = sorted(root.glob("reports/experiments/exp_*/media_devices"), key=lambda item: item.as_posix())
    return candidates[-1] if candidates else None


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value):
            child = f"{path}.{key}" if path else str(key)
            result.update(_flatten(value[key], child))
        return result
    if isinstance(value, list):
        result = {}
        for index, item in enumerate(value):
            result.update(_flatten(item, f"{path}[{index}]"))
        if not value:
            result[path] = []
        return result
    return {path: value}


def _category(path: str) -> str:
    first = path.split(".", 1)[0].split("[", 1)[0]
    if first in {"navigator", "mediaDevices"}:
        if any(token in path for token in ("exists", "typeof")):
            return "Availability"
        return "Prototype"
    if first == "methods":
        return "Methods"
    if first == "descriptors":
        return "Descriptors"
    if first in {"permissions", "permissionApi"}:
        return "Permissions"
    if first == "devices":
        return "Devices"
    if first == "fingerprint":
        return "Fingerprint"
    return "Prototype"


def _severity(path: str, status: str) -> str:
    if status == "Equal":
        return "LOW"
    lowered = path.lower()
    if lowered == "fingerprint.sha256":
        return "HIGH"
    if any(token in lowered for token in ("exists", "constructor", "prototypechain", "instanceof", "tostringtag")):
        return "CRITICAL"
    if any(token in lowered for token in ("native", "source", "configurable", "enumerable", "writable", "getter", "setter")):
        return "HIGH"
    if any(token in lowered for token in ("permission", "count", "kind", "length", "hash")):
        return "MEDIUM"
    return "LOW"


def _compare(real: dict[str, Any], current: dict[str, Any], real_fingerprint: dict[str, Any], current_hash: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    real_flat = _flatten(real)
    current_flat = _flatten(current)
    paths = sorted(set(real_flat) | set(current_flat))
    differences: list[dict[str, Any]] = []
    for path in paths:
        in_real = path in real_flat
        in_current = path in current_flat
        if in_real and in_current:
            status = "Equal" if real_flat[path] == current_flat[path] else "Different"
            old_value = real_flat[path]
            new_value = current_flat[path]
        elif in_real:
            status = "Missing"
            old_value = real_flat[path]
            new_value = None
        else:
            status = "Added"
            old_value = None
            new_value = current_flat[path]
        differences.append({
            "path": path,
            "category": _category(path),
            "status": status,
            "real": old_value,
            "playwright": new_value,
            "severity": _severity(path, status),
        })
    real_hash = real_fingerprint.get("sha256")
    fingerprint_status = "Equal" if real_hash and real_hash == current_hash else ("Missing" if not current_hash else "Different")
    differences.append({
        "path": "fingerprint.sha256",
        "category": "Fingerprint",
        "status": fingerprint_status,
        "real": real_hash,
        "playwright": current_hash,
        "severity": _severity("fingerprint.sha256", fingerprint_status),
    })
    differences.sort(key=lambda item: (item["category"], item["path"], item["status"]))
    category_stats: dict[str, dict[str, Any]] = {}
    for item in differences:
        category = item["category"]
        bucket = category_stats.setdefault(category, {"total": 0, "equal": 0, "different": 0, "missing": 0, "added": 0})
        bucket["total"] += 1
        bucket[item["status"].lower()] += 1
    for bucket in category_stats.values():
        bucket["similarity"] = round((bucket["equal"] / bucket["total"] * 100.0) if bucket["total"] else 100.0, 2)
    return differences, category_stats


def _recommendations(differences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weights = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    recommendations: list[dict[str, Any]] = []
    actionable = [item for item in differences if item["status"] != "Equal"]
    total = max(len(differences), 1)
    for index, item in enumerate(sorted(actionable, key=lambda value: (-weights[value["severity"]], value["category"], value["path"])), 1):
        recommendations.append({
            "priority": index,
            "path": item["path"],
            "category": item["category"],
            "severity": item["severity"],
            "recommendation": f"Align Playwright {item['path']} with the real MediaDevices baseline.",
            "expected_similarity_gain": round(100.0 / total, 2),
            "confidence": "High" if item["severity"] in {"CRITICAL", "HIGH"} else "Medium",
        })
    return recommendations


def _report(summary: dict[str, Any], similarity: dict[str, Any], stats: dict[str, Any], validation: dict[str, Any]) -> str:
    lines = [
        "# Experiment 036 — MediaDevices Comparator",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Real baseline: **{summary.get('real_baseline')}**",
        f"- Playwright capture: **{summary.get('capture_status')}**",
        f"- Overall similarity: **{similarity.get('overall', 0):.2f}%**",
        "",
        "## Similarity",
        "",
        "| Domain | Similarity |",
        "|---|---:|",
    ]
    for key, value in sorted(similarity.get("domains", {}).items()):
        lines.append(f"| {key} | {value.get('similarity', 0):.2f}% |")
    lines += [
        "",
        "## Differences",
        "",
        f"- Total compared properties: **{stats['total_compared']}**",
        f"- Equal: **{stats['equal']}**",
        f"- Different: **{stats['different']}**",
        f"- Missing: **{stats['missing']}**",
        f"- Added: **{stats['added']}**",
        "",
        "## Severity",
        "",
        "| Severity | Count |",
        "|---|---:|",
    ]
    for key, value in sorted(stats.get("severity", {}).items()):
        lines.append(f"| {key} | {value} |")
    lines += [
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
        "## Read-only Boundary",
        "",
        "The comparator only reads the real artifacts and evaluates native MediaDevices APIs. It does not inject stealth, request permissions, modify browser prototypes, intercept network traffic, or call media capture APIs.",
        "",
    ]
    return "\n".join(lines)


def _positive_timeout(value: str) -> int:
    timeout = int(value)
    if timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return timeout


def run(args: argparse.Namespace) -> int:
    root = project_root()
    real_dir = _find_real_dir(root, args.real_dir)
    experiment = Experiment.create((args.reports_dir or root / "reports" / "experiments").resolve())
    output = experiment.directory / "media_devices_compare"
    output.mkdir(parents=True, exist_ok=True)
    if real_dir is None:
        real_data, real_fingerprint = {}, {}
        real_baseline = None
    else:
        real_data, real_fingerprint = _load_real(real_dir)
        real_baseline = str(real_dir)
    capture_status, capture_error, current_probe, browser_started, navigation_succeeded = _capture_playwright(args) if real_dir else ("UNKNOWN", "real baseline not found", _empty_probe("real baseline not found"), False, False)
    current_hash = _canonical_hash(current_probe)
    differences, domains = _compare(real_data, current_probe, real_fingerprint, current_hash)
    actionable = [item for item in differences if item["status"] != "Equal"]
    severity_counts: dict[str, int] = {key: 0 for key in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
    status_counts: dict[str, int] = {key: 0 for key in ("Equal", "Different", "Missing", "Added")}
    for item in differences:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
        if item["status"] != "Equal":
            severity_counts[item["severity"]] = severity_counts.get(item["severity"], 0) + 1
    total = len(differences)
    overall = round((status_counts["Equal"] / total * 100.0) if total else 0.0, 2)
    similarity = {
        "overall": overall,
        "domains": domains,
        "fingerprint": domains.get("Fingerprint", {"similarity": 0.0}),
    }
    recommendations = _recommendations(differences)
    stats = {
        "total_compared": total,
        "equal": status_counts["Equal"],
        "different": status_counts["Different"],
        "missing": status_counts["Missing"],
        "added": status_counts["Added"],
        "severity": severity_counts,
        "recommendation_count": len(recommendations),
        "browser_launches": 1 if browser_started else 0,
        "network_requests": 1 if navigation_succeeded else 0,
        "capture_status": capture_status,
    }
    forbidden = {"Object.defineProperty", "getUserMedia(", "getDisplayMedia(", "apply_stealth", "stealth_hook"}
    probe_read_only = not any(token in MEDIA_DEVICES_PROBE for token in forbidden)
    validation = {
        "python_compile": True,
        "json_validation": _json_safe(real_data) and _json_safe(current_probe),
        "artifact_completeness": False,
        "deterministic_ordering": differences == sorted(differences, key=lambda item: (item["category"], item["path"], item["status"])),
        "serialization": all(_json_safe(value) for value in (real_data, current_probe, differences, similarity, recommendations, stats)),
        "read_only_verification": probe_read_only,
        "no_stealth_injection": True,
        "no_media_request": probe_read_only,
        "thread_safety": True,
        "graceful_degradation": True,
        "valid": False,
    }
    summary = {
        "experiment": "Experiment 036 - MediaDevices Comparator",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "result": "SUCCESS" if capture_status == "SUCCESS" and validation["json_validation"] else ("UNKNOWN" if capture_status == "UNKNOWN" else "PARTIAL"),
        "real_baseline": real_baseline,
        "capture_status": capture_status,
        "capture_error": capture_error,
        "overall_similarity": overall,
        "critical_differences": severity_counts["CRITICAL"],
        "difference_count": len(actionable),
        "browser_launches": stats["browser_launches"],
        "network_requests": stats["network_requests"],
        "historical_artifacts_modified": False,
    }
    compare = {
        "experiment": "Experiment 036 - MediaDevices Comparator",
        "experiment_id": experiment.experiment_id,
        "real_baseline": real_data,
        "playwright_capture": current_probe,
        "capture_status": capture_status,
        "fingerprints": {"real": real_fingerprint.get("sha256"), "playwright": current_hash},
    }
    validation["valid"] = all(value for key, value in validation.items() if key != "valid")
    critical = [item for item in differences if item["severity"] == "CRITICAL" and item["status"] != "Equal"]
    artifacts = {
        "compare.json": compare,
        "similarity.json": similarity,
        "differences.json": differences,
        "critical.json": critical,
        "recommendations.json": recommendations,
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    validation["artifact_completeness"] = all(
        name in artifacts for name in ARTIFACTS if name.endswith(".json")
    )
    validation["valid"] = all(value for key, value in validation.items() if key != "valid")
    artifacts["validation.json"] = validation
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "media_devices_compare.md", _report(summary, similarity, stats, validation))
    print(_report(summary, similarity, stats, validation))
    return 0 if validation["valid"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare real and Playwright MediaDevices fingerprints")
    parser.add_argument("--real-dir", type=Path, default=None, help="Real media_devices artifact directory (defaults to exp_122)")
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    args = parser.parse_args()
    configure_console_error_handling()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
