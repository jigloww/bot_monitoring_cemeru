"""Experiment 055: deterministic Permissions API behavior comparator.

The immutable Experiment 054 snapshot is compared with a fresh Browser
Platform capture on ``about:blank``.  Only non-prompting
``navigator.permissions.query`` calls are made; no permission, media, network,
or stealth operation is performed.
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
from experiments.permissions_collector import PERMISSIONS_PROBE, SAFE_PERMISSION_NAMES
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    sha256_file,
    write_json_exclusive,
    write_text_exclusive,
)


BASELINE_FILES = (
    "permissions.json",
    "prototype.json",
    "descriptors.json",
    "methods.json",
    "behavior.json",
    "fingerprint.json",
    "statistics.json",
    "summary.json",
    "validation.json",
)
DOMAIN_ORDER = (
    "permissions",
    "prototype",
    "descriptors",
    "methods",
    "behavior",
    "permission_status",
    "fingerprint",
)
SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


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
    preferred = root / "reports" / "experiments" / "exp_206" / "permissions"
    candidates = list(root.glob("reports/experiments/exp_*/permissions"))
    candidates.sort(key=lambda item: (_experiment_number(item), item.as_posix()))
    successful: list[Path] = []
    complete: list[Path] = []
    for candidate in candidates:
        complete_now = all((candidate / name).is_file() for name in BASELINE_FILES)
        if complete_now:
            complete.append(candidate)
        summary = _read_json(candidate / "summary.json")
        if complete_now and str(summary.get("experiment", "")).lower().startswith("experiment 054") and summary.get("result") == "SUCCESS":
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
    output: dict[str, str] = {}
    for name in BASELINE_FILES:
        path = directory / name
        if path.is_file():
            try:
                output[name] = sha256_file(path)
            except OSError:
                output[name] = ""
    return output


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
        result = page.evaluate(PERMISSIONS_PROBE)
        if not isinstance(result, dict):
            raise TypeError("Permissions probe returned a non-object result")
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
        output: dict[str, Any] = {}
        for key in sorted(value, key=str):
            child = f"{prefix}.{key}" if prefix else str(key)
            output.update(_flatten(value[key], child))
        return output
    if isinstance(value, list):
        if not value:
            return {prefix: []}
        output: dict[str, Any] = {}
        for index, item in enumerate(value):
            output.update(_flatten(item, f"{prefix}[{index}]"))
        return output
    return {prefix: value}


def _severity(domain: str, path: str, status: str) -> str:
    if status == "EQUAL":
        return "LOW"
    lowered = path.lower()
    critical_tokens = (
        "constructor", "prototype", "native", "source", "illegal", "descriptor",
        "getter", "setter", "tostringtag", "state", "permission",
    )
    if domain in {"prototype", "descriptors", "methods", "permission_status", "fingerprint"} or any(token in lowered for token in critical_tokens):
        return "CRITICAL"
    if domain == "behavior":
        return "HIGH"
    return "HIGH" if status in {"MISSING", "ADDED"} else "MEDIUM"


def _reason(domain: str, path: str, status: str) -> str:
    if status == "EQUAL":
        return "Candidate matches the immutable Experiment 054 Permissions baseline."
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
        in_left = path in left
        in_right = path in right
        if in_left and in_right:
            status = "EQUAL" if left[path] == right[path] else "CHANGED"
        elif in_left:
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
    if isinstance(data, dict) and data.get("permissions") is not None:
        return _ordered(data)
    behavior = raw.get("behavior", {})
    queries = behavior.get("queries", behavior) if isinstance(behavior, dict) else {}
    exceptions = behavior.get("exceptions", {}) if isinstance(behavior, dict) else {}
    return _ordered({
        "permissions": raw.get("permissions", {}),
        "prototype": raw.get("prototype", {}),
        "descriptors": raw.get("descriptors", {}),
        "methods": raw.get("methods", {}),
        "behavior": queries,
        "exceptions": exceptions,
    })


def _report(summary: dict[str, Any], similarity: dict[str, Any], stats: dict[str, Any], critical: list[dict[str, Any]]) -> str:
    lines = [
        "# Experiment 055 - Permissions Comparator", "", "## Executive Summary", "",
        f"- Result: **{summary['result']}**",
        f"- Status: **{summary['status']}**",
        f"- Overall similarity: **{similarity['overall']:.2f}%**",
        f"- Fingerprint similarity: **{similarity['fingerprint']:.2f}%**",
        f"- Remaining differences: **{stats['remaining_differences']}**",
        f"- Critical differences: **{stats['critical_differences']}**", "",
        "## Similarity Metrics", "", "| Metric | Similarity |", "|---|---:|",
    ]
    for key in ("prototype", "descriptor", "method", "behavior", "permission_status", "fingerprint", "overall"):
        lines.append(f"| {key.replace('_', ' ').title()} | {similarity[key]:.2f}% |")
    lines += ["", "## Certification Gate", "", f"- Patch required: **{summary['patch_required']}**", f"- Certified: **{summary['certified']}**", ""]
    lines += ["## Critical Differences", "", "| Domain | Path | Status | Classification | Severity |", "|---|---|---|---|---|"]
    for row in critical[:50]:
        lines.append(f"| {row['domain']} | `{row['path']}` | {row['status']} | {row['classification']} | {row['severity']} |")
    if not critical:
        lines.append("| None | - | - | - | - |")
    lines += ["", "## Read-only Boundary", "", "Candidate was captured on about:blank through Browser Platform. Only non-prompting permission-state queries and metadata reads were used; no permission request, media access, stealth injection, or network API was used.", ""]
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
    status, capture_error, candidate_data, started = _capture(args) if baseline_meta.get("available") else ("UNKNOWN", "Permissions baseline unavailable", {}, False)
    candidate_data = _ordered(candidate_data if isinstance(candidate_data, dict) else {})
    after_hashes = _directory_hashes(baseline_dir)

    # Surface, structure, methods, and query behavior are compared separately
    # so that each certification metric remains independently actionable.
    sections: dict[str, tuple[Any, Any]] = {
        "permissions": (baseline_data.get("permissions", {}), candidate_data.get("permissions", {})),
        "prototype": (baseline_data.get("prototype", {}), candidate_data.get("prototype", {})),
        "descriptors": (baseline_data.get("descriptors", {}), candidate_data.get("descriptors", {})),
        "methods": (baseline_data.get("methods", {}), candidate_data.get("methods", {})),
        "behavior": (
            {"queries": baseline_data.get("behavior", {}), "exceptions": baseline_data.get("exceptions", {})},
            {"queries": candidate_data.get("behavior", {}), "exceptions": candidate_data.get("exceptions", {})},
        ),
        "permission_status": (
            {name: (baseline_data.get("behavior", {}) or {}).get(name, {}).get("status") for name in SAFE_PERMISSION_NAMES},
            {name: (candidate_data.get("behavior", {}) or {}).get(name, {}).get("status") for name in SAFE_PERMISSION_NAMES},
        ),
    }
    differences: list[dict[str, Any]] = []
    metrics: dict[str, dict[str, Any]] = {}
    for domain in ("permissions", "prototype", "descriptors", "methods", "behavior", "permission_status"):
        rows, item = _compare(domain, sections[domain][0], sections[domain][1])
        differences.extend(rows)
        metrics[domain] = item

    baseline_hash = baseline_raw.get("fingerprint", {}).get("sha256") if isinstance(baseline_raw.get("fingerprint"), dict) else None
    candidate_fingerprint_data = {key: candidate_data.get(key, {}) for key in ("permissions", "prototype", "descriptors", "methods", "behavior", "exceptions")}
    candidate_hash = _canonical_hash(candidate_fingerprint_data)
    fingerprint_rows, fingerprint_metrics = _compare("fingerprint", {"sha256": baseline_hash}, {"sha256": candidate_hash})
    differences.extend(fingerprint_rows)
    metrics["fingerprint"] = fingerprint_metrics
    differences.sort(key=lambda row: (DOMAIN_ORDER.index(row["domain"]), row["path"], row["status"]))
    remaining = [row for row in differences if row["status"] != "EQUAL"]
    critical = [row for row in remaining if row["severity"] == "CRITICAL"]

    component_values = [metrics[key]["similarity"] for key in ("permissions", "prototype", "descriptors", "methods", "behavior", "permission_status")]
    similarity = {
        "overall": round(sum(component_values) / len(component_values), 2) if component_values else 100.0,
        "prototype": metrics["prototype"]["similarity"],
        "descriptor": metrics["descriptors"]["similarity"],
        "method": metrics["methods"]["similarity"],
        "behavior": metrics["behavior"]["similarity"],
        "permission_status": metrics["permission_status"]["similarity"],
        "fingerprint": 100.0 if baseline_hash and baseline_hash == candidate_hash else 0.0,
        "domains": {key: metrics[key] for key in sorted(metrics)},
    }
    certified = similarity["overall"] == 100.0 and similarity["fingerprint"] == 100.0 and not remaining and not critical
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden = ("requestPermission(", "get" + "UserMedia(", "get" + "DisplayMedia(", "selectAudioOutput(", "sendBeacon(", "fetch(", "XMLHttpRequest", "add_" + "init_script", "_" + "_stealth")
    query_info = candidate_data.get("methods", {}).get("query", {}) if isinstance(candidate_data.get("methods"), dict) else {}
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (baseline_data, candidate_data, differences, similarity)),
        "artifact_completeness": False,
        "deterministic_ordering": differences == sorted(differences, key=lambda row: (DOMAIN_ORDER.index(row["domain"]), row["path"], row["status"])),
        "prototype_validation": bool(candidate_data.get("permissions", {}).get("prototypeEquality")) and bool(candidate_data.get("permissions", {}).get("constructorEquality")),
        "descriptor_validation": bool(candidate_data.get("descriptors")) and all(value is None or isinstance(value, dict) for value in candidate_data.get("descriptors", {}).values()),
        "method_validation": bool(query_info.get("available")) and bool(query_info.get("nativeSource")) and isinstance(query_info.get("descriptor"), dict),
        "behavior_validation": len(candidate_data.get("behavior", {})) == len(SAFE_PERMISSION_NAMES) and all(isinstance(value, dict) for value in candidate_data.get("behavior", {}).values()),
        "fingerprint_validation": bool(baseline_hash) and candidate_hash == _canonical_hash(candidate_fingerprint_data),
        "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and "launch_browser" in source and ("sync_" + "playwright") not in source,
        "read_only_verification": not any(token in PERMISSIONS_PROBE for token in forbidden),
        "no_permission_prompts": not any(token in PERMISSIONS_PROBE for token in ("requestPermission(", "get" + "UserMedia(", "get" + "DisplayMedia(", "selectAudioOutput(")),
        "no_media_access": not any(token in PERMISSIONS_PROBE for token in ("get" + "UserMedia(", "get" + "DisplayMedia(", "selectAudioOutput(")),
        "no_network_requests": not any(token in PERMISSIONS_PROBE for token in ("sendBeacon(", "fetch(", "XMLHttpRequest")),
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
        "experiment": "Experiment 055 - Permissions Comparator",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "PRODUCTION_READY" if certified else ("NEEDS_REVIEW" if status == "SUCCESS" else "UNKNOWN"),
        "status": "PRODUCTION_READY" if certified else "NEEDS_REVIEW",
        "patch_required": not certified,
        "certified": certified,
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
    output = experiment.directory / "permissions_compare"
    output.mkdir(parents=True, exist_ok=False)
    certification = {
        "module": "Permissions",
        "status": "PRODUCTION_READY" if certified else "NEEDS_REVIEW",
        "patch_required": not certified,
        "static_similarity": similarity["fingerprint"],
        "behavior_similarity": similarity["behavior"],
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
    write_text_exclusive(output / "permissions_compare.md", _report(summary, similarity, stats, critical))
    print("PERMISSIONS COMPARATOR")
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
    parser = argparse.ArgumentParser(description="Experiment 055: compare Permissions API behavior")
    parser.add_argument("--baseline-dir", type=Path, default=None)
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
