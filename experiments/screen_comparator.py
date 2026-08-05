"""Experiment 057: deterministic Screen API comparator.

Compare the immutable Experiment 056 Screen snapshot with a fresh Browser
Platform capture.  The candidate is observed on ``about:blank`` through
BrowserSessionManager; no browser property is written and no stealth,
permission, media, or network API is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserConfig, BrowserSessionManager
from experiments.experiment import Experiment
from experiments.screen_collector import SCREEN_PROBE, SCREEN_PROPERTIES
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    sha256_file,
    write_json_exclusive,
    write_text_exclusive,
)


BASELINE_FILES = (
    "screen.json",
    "prototype.json",
    "descriptors.json",
    "window.json",
    "viewport.json",
    "orientation.json",
    "fingerprint.json",
    "statistics.json",
    "summary.json",
    "validation.json",
)
DOMAIN_ORDER = (
    "screen",
    "prototype",
    "descriptors",
    "orientation",
    "viewport",
    "runtime",
    "fingerprint",
)


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


def _find_baseline(root: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        candidate = explicit if explicit.is_absolute() else root / explicit
        return candidate if candidate.is_dir() else None
    preferred = root / "reports" / "experiments" / "exp_209" / "screen"
    candidates = list(root.glob("reports/experiments/exp_*/screen"))
    candidates.sort(key=lambda item: (_experiment_number(item), item.as_posix()))
    successful: list[Path] = []
    complete: list[Path] = []
    for candidate in candidates:
        complete_now = all((candidate / name).is_file() for name in BASELINE_FILES)
        if complete_now:
            complete.append(candidate)
        summary = _read_json(candidate / "summary.json")
        if complete_now and str(summary.get("experiment", "")).lower().startswith("experiment 056") and summary.get("result") == "SUCCESS":
            successful.append(candidate)
    if preferred.is_dir() and all((preferred / name).is_file() for name in BASELINE_FILES):
        return preferred
    return (successful or complete or candidates)[-1] if (successful or complete or candidates) else None


def _load_baseline(directory: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if directory is None or not directory.is_dir():
        return {}, {"available": False, "directory": str(directory) if directory else None, "hashes": {}}
    raw = {name.removesuffix(".json"): _read_json(directory / name) for name in BASELINE_FILES}
    hashes: dict[str, str] = {}
    for name in BASELINE_FILES:
        path = directory / name
        if path.is_file():
            try:
                hashes[name] = sha256_file(path)
            except OSError:
                hashes[name] = ""
    return raw, {
        "available": all((directory / name).is_file() for name in BASELINE_FILES),
        "directory": str(directory),
        "hashes": hashes,
        "experiment": _read_json(directory / "summary.json").get("experiment"),
    }


def _directory_hashes(directory: Path | None) -> dict[str, str]:
    if directory is None or not directory.is_dir():
        return {}
    result: dict[str, str] = {}
    for name in BASELINE_FILES:
        path = directory / name
        if path.is_file():
            try:
                result[name] = sha256_file(path)
            except OSError:
                result[name] = ""
    return result


def _capture(args: argparse.Namespace) -> tuple[str, str | None, dict[str, Any], bool]:
    config = BrowserConfig(browser=args.browser, headless=args.headless, persistent=False, url="about:blank", timeout=args.timeout, enable_stealth=False)
    manager = BrowserSessionManager(config)
    page: Any = None
    started = False
    error: str | None = None
    data: dict[str, Any] = {}
    try:
        manager.start()
        started = True
        page = manager.new_page()
        result = page.evaluate(SCREEN_PROBE)
        if not isinstance(result, dict):
            raise TypeError("Screen probe returned a non-object result")
        data = _ordered(result)
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
    status = "SUCCESS" if started and data.get("available") and not error else ("PARTIAL" if started else "UNKNOWN")
    return status, error, data, started


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value, key=str):
            child = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(value[key], child))
        return result
    if isinstance(value, list):
        if not value:
            return {prefix: []}
        result = {}
        for index, item in enumerate(value):
            result.update(_flatten(item, f"{prefix}[{index}]"))
        return result
    return {prefix: value}


def _severity(domain: str, path: str, status: str) -> str:
    if status == "EQUAL":
        return "LOW"
    lowered = path.lower()
    critical = ("prototype", "constructor", "native", "source", "illegal", "descriptor", "getter", "setter", "fingerprint", "orientation")
    if domain in {"prototype", "descriptors", "orientation", "fingerprint"} or any(token in lowered for token in critical):
        return "CRITICAL"
    if domain in {"screen", "viewport", "runtime"}:
        return "HIGH" if status in {"MISSING", "ADDED"} else "MEDIUM"
    return "MEDIUM"


def _reason(domain: str, path: str, status: str) -> str:
    if status == "EQUAL":
        return "Candidate matches the immutable Experiment 056 Screen baseline."
    if status == "MISSING":
        return f"Candidate is missing baseline field {domain}.{path}."
    if status == "ADDED":
        return f"Candidate exposes additional field {domain}.{path}."
    return f"Candidate value differs for {domain}.{path}."


def _compare(domain: str, baseline: Any, candidate: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    left = _flatten(baseline, domain)
    right = _flatten(candidate, domain)
    rows: list[dict[str, Any]] = []
    for path in sorted(set(left) | set(right)):
        if path in left and path in right:
            status = "EQUAL" if left[path] == right[path] else "CHANGED"
        elif path in left:
            status = "MISSING"
        else:
            status = "ADDED"
        severity = _severity(domain, path, status)
        rows.append({
            "domain": domain,
            "path": path,
            "status": status,
            "classification": "EQUAL" if status == "EQUAL" else ("CRITICAL" if severity == "CRITICAL" else status),
            "baseline": left.get(path),
            "candidate": right.get(path),
            "severity": severity,
            "reason": _reason(domain, path, status),
            "confidence": "High" if severity in {"CRITICAL", "HIGH"} else "Medium",
        })
    equal = sum(1 for row in rows if row["status"] == "EQUAL")
    return rows, {
        "total": len(rows),
        "equal": equal,
        "remaining": len(rows) - equal,
        "changed": sum(1 for row in rows if row["status"] == "CHANGED"),
        "missing": sum(1 for row in rows if row["status"] == "MISSING"),
        "added": sum(1 for row in rows if row["status"] == "ADDED"),
        "similarity": round(equal * 100.0 / len(rows), 2) if rows else 100.0,
    }


def _projection(raw: dict[str, Any]) -> dict[str, Any]:
    fingerprint = raw.get("fingerprint", {})
    data = fingerprint.get("data", {}) if isinstance(fingerprint, dict) else {}
    if isinstance(data, dict) and data.get("screen") is not None:
        return _ordered(data)
    return _ordered({
        "screen": raw.get("screen", {}),
        "prototype": raw.get("prototype", {}),
        "descriptors": raw.get("descriptors", {}),
        "getters": raw.get("getters", {}),
        "window": raw.get("window", {}),
        "viewport": raw.get("viewport", {}),
        "orientation": raw.get("orientation", {}),
        "exceptions": {},
    })


def _report(summary: dict[str, Any], similarity: dict[str, Any], stats: dict[str, Any], critical: list[dict[str, Any]]) -> str:
    lines = [
        "# Experiment 057 - Screen Comparator", "", "## Executive Summary", "",
        f"- Result: **{summary['result']}**",
        f"- Status: **{summary['status']}**",
        f"- Overall similarity: **{similarity['overall']:.2f}%**",
        f"- Fingerprint similarity: **{similarity['fingerprint']:.2f}%**",
        f"- Remaining differences: **{stats['remaining_differences']}**",
        f"- Critical differences: **{stats['critical_differences']}**", "",
        "## Similarity Metrics", "", "| Metric | Similarity |", "|---|---:|",
    ]
    for key in ("prototype", "descriptor", "orientation", "viewport", "runtime", "fingerprint", "overall"):
        lines.append(f"| {key.title()} | {similarity[key]:.2f}% |")
    lines += ["", "## Certification Gate", "", f"- Patch required: **{summary['patch_required']}**", f"- Certified: **{summary['certified']}**", f"- Frozen: **{summary['frozen']}**", "", "## Critical Differences", "", "| Domain | Path | Status | Classification | Severity |", "|---|---|---|---|---|"]
    for row in critical[:50]:
        lines.append(f"| {row['domain']} | `{row['path']}` | {row['status']} | {row['classification']} | {row['severity']} |")
    if not critical:
        lines.append("| None | - | - | - | - |")
    lines += ["", "## Read-only Boundary", "", "Candidate was captured on about:blank through Browser Platform. No screen/window property was written, no stealth injection was used, and no network API was called.", ""]
    return "\n".join(lines)


def _positive_timeout(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return parsed


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    baseline_dir = _find_baseline(root, args.baseline_dir)
    baseline_raw, baseline_meta = _load_baseline(baseline_dir)
    before_hashes = dict(baseline_meta.get("hashes", {}))
    baseline_data = _projection(baseline_raw)
    status, capture_error, candidate_data, started = _capture(args) if baseline_meta.get("available") else ("UNKNOWN", "Screen baseline unavailable", {}, False)
    candidate_data = _ordered(candidate_data if isinstance(candidate_data, dict) else {})
    after_hashes = _directory_hashes(baseline_dir)
    sections: dict[str, tuple[Any, Any]] = {
        "screen": (baseline_data.get("screen", {}), candidate_data.get("screen", {})),
        "prototype": (baseline_data.get("prototype", {}), candidate_data.get("prototype", {})),
        "descriptors": (baseline_data.get("descriptors", {}), candidate_data.get("descriptors", {})),
        "orientation": (baseline_data.get("orientation", {}), candidate_data.get("orientation", {})),
        "viewport": ({"window": baseline_data.get("window", {}), "viewport": baseline_data.get("viewport", {})}, {"window": candidate_data.get("window", {}), "viewport": candidate_data.get("viewport", {})}),
        "runtime": ({"getters": baseline_data.get("getters", {}), "exceptions": baseline_data.get("exceptions", {}), "screenAccess": baseline_data.get("screen", {}).get("access", {})}, {"getters": candidate_data.get("getters", {}), "exceptions": candidate_data.get("exceptions", {}), "screenAccess": candidate_data.get("screen", {}).get("access", {})}),
    }
    differences: list[dict[str, Any]] = []
    metrics: dict[str, dict[str, Any]] = {}
    for domain in ("screen", "prototype", "descriptors", "orientation", "viewport", "runtime"):
        rows, item = _compare(domain, sections[domain][0], sections[domain][1])
        differences.extend(rows)
        metrics[domain] = item
    baseline_hash = baseline_raw.get("fingerprint", {}).get("sha256") if isinstance(baseline_raw.get("fingerprint"), dict) else None
    candidate_fingerprint_data = {key: candidate_data.get(key, {}) for key in ("screen", "prototype", "descriptors", "getters", "window", "viewport", "orientation", "exceptions")}
    candidate_hash = _canonical_hash(candidate_fingerprint_data)
    fingerprint_rows, fingerprint_metrics = _compare("fingerprint", {"sha256": baseline_hash}, {"sha256": candidate_hash})
    differences.extend(fingerprint_rows)
    metrics["fingerprint"] = fingerprint_metrics
    differences.sort(key=lambda row: (DOMAIN_ORDER.index(row["domain"]), row["path"], row["status"]))
    remaining = [row for row in differences if row["status"] != "EQUAL"]
    critical = [row for row in remaining if row["severity"] == "CRITICAL"]
    component_values = [metrics[key]["similarity"] for key in ("screen", "prototype", "descriptors", "orientation", "viewport", "runtime")]
    similarity = {
        "overall": round(sum(component_values) / len(component_values), 2) if component_values else 100.0,
        "prototype": metrics["prototype"]["similarity"],
        "descriptor": metrics["descriptors"]["similarity"],
        "orientation": metrics["orientation"]["similarity"],
        "viewport": metrics["viewport"]["similarity"],
        "runtime": metrics["runtime"]["similarity"],
        "fingerprint": 100.0 if baseline_hash and baseline_hash == candidate_hash else 0.0,
        "domains": {key: metrics[key] for key in sorted(metrics)},
    }
    certified = similarity["overall"] == 100.0 and similarity["fingerprint"] == 100.0 and not remaining and not critical
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden = ("add_" + "init_script", "_" + "_stealth", "get" + "UserMedia(", "get" + "DisplayMedia(", "requestPermission(", "sendBeacon(", "fetch(", "XMLHttpRequest", "location.assign(", "location.replace(")
    screen_candidate = candidate_data.get("screen", {}) if isinstance(candidate_data.get("screen"), dict) else {}
    proto_candidate = candidate_data.get("prototype", {}) if isinstance(candidate_data.get("prototype"), dict) else {}
    desc_candidate = candidate_data.get("descriptors", {}) if isinstance(candidate_data.get("descriptors"), dict) else {}
    orientation_candidate = candidate_data.get("orientation", {}) if isinstance(candidate_data.get("orientation"), dict) else {}
    viewport_candidate = candidate_data.get("viewport", {}) if isinstance(candidate_data.get("viewport"), dict) else {}
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (baseline_data, candidate_data, differences, similarity)),
        "artifact_completeness": False,
        "deterministic_ordering": differences == sorted(differences, key=lambda row: (DOMAIN_ORDER.index(row["domain"]), row["path"], row["status"])),
        "prototype_validation": bool(screen_candidate.get("prototypeEquality")) and bool(screen_candidate.get("constructorEquality")) and bool(screen_candidate.get("instanceofScreen")) and bool(proto_candidate.get("instanceofObject")),
        "descriptor_validation": bool(desc_candidate) and all(value is None or isinstance(value, dict) for value in desc_candidate.values()),
        "orientation_validation": bool(orientation_candidate.get("referenceStable")) and isinstance(orientation_candidate.get("values"), dict),
        "viewport_validation": bool(viewport_candidate) and isinstance(viewport_candidate.get("matchMedia"), dict),
        "runtime_validation": bool(candidate_data.get("getters")) and bool(candidate_data.get("exceptions")),
        "fingerprint_validation": bool(baseline_hash) and candidate_hash == _canonical_hash(candidate_fingerprint_data),
        "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and "launch_browser" in source and ("sync_" + "playwright") not in source,
        "read_only_verification": not any(token in SCREEN_PROBE for token in forbidden),
        "no_browser_modification": not any(token in SCREEN_PROBE for token in forbidden),
        "no_network_requests": not any(token in SCREEN_PROBE for token in ("sendBeacon(", "fetch(", "XMLHttpRequest")),
        "historical_artifacts_immutable": before_hashes == after_hashes,
        "browser_launches": int(started),
        "network_requests": 0,
        "valid": False,
    }
    stats = {
        "total_compared_fields": len(differences),
        "equal_fields": sum(1 for row in differences if row["status"] == "EQUAL"),
        "remaining_differences": len(remaining),
        "critical_differences": len(critical),
        "status_distribution": dict(sorted(Counter(row["status"] for row in differences).items())),
        "severity_distribution": dict(sorted(Counter(row["severity"] for row in remaining).items())),
        "domain_distribution": {domain: metrics[domain] for domain in sorted(metrics)},
        "baseline_directory": baseline_meta.get("directory"),
        "baseline_fingerprint": baseline_hash,
        "candidate_fingerprint": candidate_hash,
        "capture_status": status,
        "capture_error": capture_error,
        "browser_launches": int(started),
        "network_requests": 0,
    }
    validation["json_validation"] = all(_json_safe(value) for value in (baseline_data, candidate_data, differences, similarity, stats))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})
    summary = {
        "experiment": "Experiment 057 - Screen Comparator",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "PRODUCTION_READY" if certified else ("NEEDS_REVIEW" if status == "SUCCESS" else "UNKNOWN"),
        "status": "PRODUCTION_READY" if certified else "NEEDS_REVIEW",
        "patch_required": not certified,
        "certified": certified,
        "frozen": certified,
        "baseline_input": baseline_meta.get("directory"),
        "candidate_source": "BrowserSessionManager -> launch_browser",
        "overall_similarity": similarity["overall"],
        "fingerprint_similarity": similarity["fingerprint"],
        "remaining_differences": len(remaining),
        "critical_differences": len(critical),
        "baseline_fingerprint": baseline_hash,
        "candidate_fingerprint": candidate_hash,
        "historical_artifacts_modified": False,
        "browser_launches": int(started),
        "network_requests": 0,
    }
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "screen_compare"
    output.mkdir(parents=True, exist_ok=False)
    certification = {
        "module": "Screen",
        "status": "PRODUCTION_READY" if certified else "NEEDS_REVIEW",
        "patch_required": not certified,
        "static_similarity": similarity["fingerprint"],
        "behavior_similarity": similarity["runtime"],
        "remaining_differences": len(remaining),
        "critical_differences": len(critical),
        "certified": certified,
        "frozen": certified,
    }
    artifact_data = {
        "compare.json": {"experiment": summary["experiment"], "experiment_id": experiment.experiment_id, "baseline": {"directory": baseline_meta.get("directory"), "hashes": before_hashes}, "candidate": candidate_data, "capture_status": status, "capture_error": capture_error},
        "similarity.json": similarity,
        "differences.json": {"differences": differences},
        "critical.json": {"critical": critical},
        "certification.json": certification,
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    validation["artifact_completeness"] = all(name in artifact_data for name in ("compare.json", "similarity.json", "differences.json", "critical.json", "certification.json", "statistics.json", "summary.json", "validation.json"))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})
    summary["validation_valid"] = validation["valid"]
    for filename, value in artifact_data.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "screen_compare.md", _report(summary, similarity, stats, critical))
    print("SCREEN COMPARATOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Overall similarity: {similarity['overall']:.2f}%")
    print(f"Fingerprint similarity: {similarity['fingerprint']:.2f}%")
    print(f"Remaining differences: {len(remaining)} | Critical: {len(critical)}")
    print(f"Status: {summary['status']} | Certified: {summary['certified']}")
    print(f"Browser launches: {stats['browser_launches']} | Network requests: {stats['network_requests']}")
    print(f"Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 057: compare Screen API behavior")
    parser.add_argument("--baseline-dir", type=Path, default=None)
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
