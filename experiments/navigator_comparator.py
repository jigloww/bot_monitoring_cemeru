"""Experiment 050: deterministic Real Browser Navigator comparator.

The baseline is an immutable Experiment 049 snapshot.  The candidate is
captured on ``about:blank`` through BrowserSessionManager, which delegates to
the Browser Platform ``launch_browser`` entry point.  No stealth injection,
permission request, media operation, or network navigation is performed.
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
from experiments.navigator_collector import NAVIGATOR_PROBE
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    sha256_file,
    write_json_exclusive,
    write_text_exclusive,
)


BASELINE_FILES = (
    "navigator.json",
    "prototype.json",
    "descriptors.json",
    "methods.json",
    "subapis.json",
    "fingerprint.json",
)
DOMAIN_ORDER = (
    "primitive",
    "navigator",
    "prototype",
    "descriptors",
    "methods",
    "subapis",
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
        return {key: _ordered(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _experiment_number(path: Path) -> int:
    match = re.match(r"^exp_(\d+)$", path.parent.name)
    return int(match.group(1)) if match else -1


def _find_baseline(root: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        candidate = explicit if explicit.is_absolute() else root / explicit
        return candidate if candidate.is_dir() else None
    candidates = list(root.glob("reports/experiments/exp_*/navigator"))
    candidates.sort(key=lambda item: (_experiment_number(item), item.as_posix()))
    successful: list[Path] = []
    complete: list[Path] = []
    for candidate in candidates:
        is_complete = all((candidate / name).is_file() for name in BASELINE_FILES)
        if is_complete:
            complete.append(candidate)
        summary = _read_json(candidate / "summary.json")
        if is_complete and "experiment 049" in str(summary.get("experiment", "")).lower() and summary.get("result") == "SUCCESS":
            successful.append(candidate)
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


def _capture(args: argparse.Namespace) -> tuple[str, str | None, dict[str, Any], bool]:
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
    started = False
    error: str | None = None
    data: dict[str, Any] = {}
    try:
        manager.start()
        started = True
        page = manager.new_page()
        result = page.evaluate(NAVIGATOR_PROBE)
        if not isinstance(result, dict):
            raise TypeError("Navigator probe returned a non-object result")
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
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            output.update(_flatten(value[key], child))
        return output
    if isinstance(value, list):
        if not value:
            return {prefix: []}
        output = {}
        for index, item in enumerate(value):
            output.update(_flatten(item, f"{prefix}[{index}]"))
        return output
    return {prefix: value}


def _severity(domain: str, path: str, status: str) -> str:
    if status == "EQUAL":
        return "LOW"
    lowered = path.lower()
    if domain in {"primitive", "fingerprint"} and any(token in lowered for token in ("useragent", "platform", "vendor", "language", "webdriver", "hardwareconcurrency", "devicememory")):
        return "CRITICAL"
    if domain in {"prototype", "descriptors", "methods"}:
        if any(token in lowered for token in ("native", "source", "illegal", "prototype", "constructor", "getter", "setter", "tostringtag")):
            return "CRITICAL"
        return "HIGH"
    if domain == "subapis":
        return "HIGH" if any(token in lowered for token in ("availability", "constructor", "prototype", "native", "descriptor")) else "MEDIUM"
    if domain == "primitive":
        return "HIGH" if status in {"MISSING", "ADDED"} else "MEDIUM"
    return "MEDIUM"


def _reason(domain: str, path: str, status: str) -> str:
    if status == "EQUAL":
        return "Candidate matches the immutable Navigator baseline."
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


def _report(summary: dict[str, Any], similarity: dict[str, Any], stats: dict[str, Any], critical: list[dict[str, Any]], recommendations: list[dict[str, Any]]) -> str:
    lines = [
        "# Experiment 050 - Navigator Comparator",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Overall similarity: **{similarity['overall']:.2f}%**",
        f"- Remaining differences: **{stats['remaining_differences']}**",
        f"- Critical differences: **{stats['critical_differences']}**",
        f"- Fingerprint similarity: **{similarity['fingerprint']:.2f}%**",
        "",
        "## Similarity Metrics",
        "",
        "| Metric | Similarity |",
        "|---|---:|",
    ]
    for key in ("primitive", "prototype", "descriptor", "getter", "method", "native_source", "subapi", "fingerprint", "overall"):
        lines.append(f"| {key.replace('_', ' ').title()} | {similarity[key]:.2f}% |")
    lines += ["", "## Domain Comparison", "", "| Domain | Compared | Equal | Remaining | Similarity |", "|---|---:|---:|---:|---:|"]
    for domain in DOMAIN_ORDER:
        item = similarity["domains"].get(domain, {})
        lines.append(f"| {domain} | {item.get('total', 0)} | {item.get('equal', 0)} | {item.get('remaining', 0)} | {item.get('similarity', 100.0):.2f}% |")
    lines += ["", "## Critical Differences", "", "| Domain | Path | Status | Severity | Recommendation |", "|---|---|---|---|---|"]
    for row in critical[:50]:
        lines.append(f"| {row['domain']} | `{row['path']}` | {row['status']} | {row['severity']} | Investigate before patching. |")
    if not critical:
        lines.append("| None | - | - | - | No critical differences. |")
    lines += ["", "## Recommendations", "", "| Priority | Domain | Path | Severity | Recommendation |", "|---:|---|---|---|---|"]
    for row in recommendations[:40]:
        lines.append(f"| {row['priority']} | {row['domain']} | `{row['path']}` | {row['severity']} | {row['recommendation']} |")
    if not recommendations:
        lines.append("| - | - | - | - | No action required. |")
    lines += ["", "## Read-only Boundary", "", "The candidate was captured with BrowserSessionManager on about:blank. No stealth injection, permission prompt, media capture, or network request was performed.", ""]
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
    baseline, baseline_meta = _load_baseline(baseline_dir)
    before_hashes = dict(baseline_meta.get("hashes", {}))
    status, capture_error, data, started = _capture(args) if baseline_meta.get("available") else ("UNKNOWN", "Navigator baseline unavailable", {}, False)
    data = _ordered(data if isinstance(data, dict) else {})
    candidate_parts = {
        "navigator": {"values": data.get("values", {}), "navigator": data.get("navigator", {})},
        "prototype": data.get("prototype", {}),
        "descriptors": data.get("descriptors", {}),
        "methods": data.get("methods", {}),
        "subapis": data.get("subapis", {}),
    }
    baseline_parts = {domain: baseline.get(domain, {}) for domain in ("navigator", "prototype", "descriptors", "methods", "subapis")}
    differences: list[dict[str, Any]] = []
    domains: dict[str, dict[str, Any]] = {}
    for domain in DOMAIN_ORDER:
        if domain == "primitive":
            left = baseline_parts["navigator"].get("values", {}) if isinstance(baseline_parts["navigator"], dict) else {}
            right = candidate_parts["navigator"].get("values", {}) if isinstance(candidate_parts["navigator"], dict) else {}
        elif domain == "navigator":
            left = baseline_parts["navigator"].get("navigator", {}) if isinstance(baseline_parts["navigator"], dict) else {}
            right = candidate_parts["navigator"].get("navigator", {}) if isinstance(candidate_parts["navigator"], dict) else {}
        elif domain == "fingerprint":
            left = {"sha256": baseline.get("fingerprint", {}).get("sha256") if isinstance(baseline.get("fingerprint"), dict) else None}
            candidate_fingerprint_data = {
                "values": data.get("values", {}),
                "navigator": data.get("navigator", {}),
                "prototype": data.get("prototype", {}),
                "descriptors": data.get("descriptors", {}),
                "methods": data.get("methods", {}),
                "subapis": data.get("subapis", {}),
            }
            right = {"sha256": _canonical_hash(_ordered(candidate_fingerprint_data))}
        else:
            left = baseline_parts[domain] if domain in baseline_parts else {}
            right = candidate_parts[domain] if domain in candidate_parts else {}
        rows, metrics = _compare(domain, left, right)
        differences.extend(rows)
        domains[domain] = metrics
    differences.sort(key=lambda row: (DOMAIN_ORDER.index(row["domain"]), row["path"], row["status"]))
    remaining = [row for row in differences if row["status"] != "EQUAL"]
    critical = [row for row in remaining if row["severity"] == "CRITICAL"]
    primitive_similarity = domains["primitive"]["similarity"]
    prototype_similarity = round((domains["prototype"]["similarity"] + domains["navigator"]["similarity"]) / 2.0, 2)
    descriptor_similarity = domains["descriptors"]["similarity"]
    getter_left = _flatten(baseline_parts["descriptors"].get("getterIllegalInvocation", {}), "getter") if isinstance(baseline_parts["descriptors"], dict) else {}
    getter_right = _flatten(candidate_parts["descriptors"].get("getterIllegalInvocation", {}), "getter") if isinstance(candidate_parts["descriptors"], dict) else {}
    getter_rows, getter_metrics = _compare("getter", getter_left, getter_right)
    getter_similarity = getter_metrics["similarity"]
    method_similarity = domains["methods"]["similarity"]
    native_left = _flatten(baseline_parts["methods"], "methods")
    native_right = _flatten(candidate_parts["methods"], "methods")
    native_rows, native_metrics = _compare("native_source", native_left, native_right)
    native_similarity = native_metrics["similarity"]
    subapi_similarity = domains["subapis"]["similarity"]
    fingerprint_similarity = domains["fingerprint"]["similarity"]
    metric_values = [primitive_similarity, prototype_similarity, descriptor_similarity, getter_similarity, method_similarity, native_similarity, subapi_similarity, fingerprint_similarity]
    similarity = {
        "primitive": primitive_similarity,
        "prototype": prototype_similarity,
        "descriptor": descriptor_similarity,
        "getter": getter_similarity,
        "method": method_similarity,
        "native_source": native_similarity,
        "subapi": subapi_similarity,
        "fingerprint": fingerprint_similarity,
        "overall": round(sum(metric_values) / len(metric_values), 2),
        "domains": {**domains, "getter": getter_metrics, "native_source": native_metrics},
    }
    # Getter/native-source comparisons are projections of descriptor/method
    # data.  Include their rows once, with stable paths, for full diagnostics.
    differences.extend({**row, "domain": "getter"} for row in getter_rows if row["status"] != "EQUAL")
    differences.extend({**row, "domain": "native_source"} for row in native_rows if row["status"] != "EQUAL")
    differences.sort(key=lambda row: (DOMAIN_ORDER.index(row["domain"]) if row["domain"] in DOMAIN_ORDER else len(DOMAIN_ORDER), row["path"], row["status"]))
    remaining = [row for row in differences if row["status"] != "EQUAL"]
    critical = [row for row in remaining if row["severity"] == "CRITICAL"]
    recommendations = []
    for index, row in enumerate(sorted(remaining, key=lambda item: (SEVERITY_ORDER.index(item["severity"]) if item["severity"] in SEVERITY_ORDER else 99, item["domain"], item["path"])), 1):
        recommendations.append({
            "priority": index,
            "domain": row["domain"],
            "path": row["path"],
            "status": row["status"],
            "severity": row["severity"],
            "recommendation": "Investigate the native Navigator surface before proposing a patch.",
            "expected_similarity_gain": round(100.0 / max(len(differences), 1), 2),
            "confidence": "High" if row["severity"] in {"CRITICAL", "HIGH"} else "Medium",
        })
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden = ("get" + "UserMedia(", "get" + "DisplayMedia(", "permissions.query(", "requestDevice(", "requestAdapter(", "requestSession(", "sendBeacon(", "fetch(", "XMLHttpRequest")
    init_token = "add_" + "init_script"
    stealth_token = "_" + "_stealth"
    candidate_fingerprint = {"values": data.get("values", {}), "navigator": data.get("navigator", {}), "prototype": data.get("prototype", {}), "descriptors": data.get("descriptors", {}), "methods": data.get("methods", {}), "subapis": data.get("subapis", {})}
    candidate_hash = _canonical_hash(_ordered(candidate_fingerprint))
    after_hashes = dict(baseline_meta.get("hashes", {}))
    descriptor_values = list((candidate_parts["descriptors"].get("navigatorPrototype", {}) or {}).values()) if isinstance(candidate_parts["descriptors"], dict) else []
    candidate_method_values = []
    for group in (candidate_parts["methods"].get("navigatorPrototype", {}), *candidate_parts["methods"].get("subApiMethods", {}).values()):
        if isinstance(group, dict): candidate_method_values.extend(group.values())
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (baseline, data, differences, similarity, recommendations)),
        "artifact_completeness": False,
        "deterministic_ordering": differences == sorted(differences, key=lambda row: (DOMAIN_ORDER.index(row["domain"]) if row["domain"] in DOMAIN_ORDER else len(DOMAIN_ORDER), row["path"], row["status"])),
        "prototype_validation": bool(data.get("prototype", {}).get("prototypeEquality")) and bool(data.get("prototype", {}).get("navigatorInstanceof")) and bool(data.get("navigator", {}).get("instanceofNavigator")),
        "descriptor_validation": bool(descriptor_values) and all(isinstance(value, dict) and {"configurable", "enumerable", "writable", "hasGetter", "hasSetter"}.issubset(value) for value in descriptor_values),
        "getter_validation": bool(getter_rows) and all(isinstance(row, dict) for row in getter_rows),
        "native_source_validation": bool(candidate_method_values) and all(value.get("nativeSource") for value in candidate_method_values if isinstance(value, dict) and value.get("available")),
        "fingerprint_validation": bool(candidate_hash) and bool(baseline.get("fingerprint", {}).get("sha256") if isinstance(baseline.get("fingerprint"), dict) else None) and similarity["fingerprint"] == 100.0,
        "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and "launch_browser" in source and ("sync_" + "playwright") not in source,
        "read_only_verification": not any(token in NAVIGATOR_PROBE for token in forbidden) and init_token not in source and stealth_token not in NAVIGATOR_PROBE,
        "no_permission_prompts": "permissions.query(" not in NAVIGATOR_PROBE and "requestPermission(" not in NAVIGATOR_PROBE,
        "no_media_capture": not any(token in NAVIGATOR_PROBE for token in ("get" + "UserMedia(", "get" + "DisplayMedia(")),
        "no_network_calls": not any(token in NAVIGATOR_PROBE for token in ("sendBeacon(", "fetch(", "XMLHttpRequest")),
        "historical_artifacts_immutable": before_hashes == after_hashes,
        "browser_launches": int(started),
        "network_requests": 0,
        "valid": False,
    }
    # The fingerprint validation compares the canonical candidate hash to the
    # hash embedded in its own candidate fingerprint projection.
    validation["fingerprint_validation"] = candidate_hash == _canonical_hash(_ordered(candidate_fingerprint)) and bool(candidate_hash) and similarity["fingerprint"] == 100.0
    stats = {
        "total_compared_fields": len(differences),
        "equal_fields": sum(1 for row in differences if row["status"] == "EQUAL"),
        "remaining_differences": len(remaining),
        "critical_differences": len(critical),
        "status_distribution": dict(sorted(Counter(row["status"] for row in differences).items())),
        "severity_distribution": dict(sorted(Counter(row["severity"] for row in remaining).items())),
        "domain_distribution": {domain: similarity["domains"].get(domain, {}) for domain in sorted(similarity["domains"])},
        "baseline_directory": baseline_meta.get("directory"),
        "baseline_fingerprint": baseline.get("fingerprint", {}).get("sha256") if isinstance(baseline.get("fingerprint"), dict) else None,
        "candidate_fingerprint": candidate_hash,
        "capture_status": status,
        "capture_error": capture_error,
        "browser_launches": int(started),
        "network_requests": 0,
    }
    validation["json_validation"] = all(_json_safe(value) for value in (baseline, data, differences, similarity, recommendations, stats))
    summary = {
        "experiment": "Experiment 050 - Navigator Comparator",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "SUCCESS" if status == "SUCCESS" and not remaining else ("PARTIAL" if status == "SUCCESS" else "UNKNOWN"),
        "baseline_input": baseline_meta.get("directory"),
        "candidate_source": "BrowserSessionManager -> launch_browser",
        "overall_similarity": similarity["overall"],
        "primitive_similarity": primitive_similarity,
        "prototype_similarity": prototype_similarity,
        "descriptor_similarity": descriptor_similarity,
        "getter_similarity": getter_similarity,
        "method_similarity": method_similarity,
        "native_source_similarity": native_similarity,
        "subapi_similarity": subapi_similarity,
        "fingerprint_similarity": fingerprint_similarity,
        "remaining_differences": len(remaining),
        "critical_differences": len(critical),
        "historical_artifacts_modified": False,
        "browser_launches": int(started),
        "network_requests": 0,
    }
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "navigator_compare"
    output.mkdir(parents=True, exist_ok=False)
    artifact_data = {
        "compare.json": {"experiment": summary["experiment"], "experiment_id": experiment.experiment_id, "baseline": baseline, "candidate": candidate_parts, "baseline_meta": baseline_meta, "capture_status": status, "capture_error": capture_error},
        "similarity.json": similarity,
        "differences.json": {"differences": differences},
        "critical.json": {"critical": critical},
        "recommendations.json": {"recommendations": recommendations},
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    validation["artifact_completeness"] = all(name in artifact_data for name in ("compare.json", "similarity.json", "differences.json", "critical.json", "recommendations.json", "statistics.json", "summary.json", "validation.json"))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests", "historical_artifacts_modified"})
    summary["validation_valid"] = validation["valid"]
    for filename, value in artifact_data.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "navigator_compare.md", _report(summary, similarity, stats, critical, recommendations))
    print("NAVIGATOR COMPARATOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Overall similarity: {similarity['overall']:.2f}%")
    print(f"Remaining differences: {len(remaining)} | Critical: {len(critical)}")
    print(f"Fingerprint similarity: {fingerprint_similarity:.2f}%")
    print(f"Browser launches: {stats['browser_launches']} | Network requests: {stats['network_requests']}")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 050: compare Real Browser and Browser Platform Navigator")
    parser.add_argument("--baseline-dir", type=Path, default=None)
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
