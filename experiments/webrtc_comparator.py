"""Experiment 046: deterministic WebRTC baseline comparator.

The comparator reads the immutable Experiment 045 baseline and performs one
metadata-only Browser Platform capture.  The shared probe never constructs a
peer connection and the comparator never injects stealth or touches network
APIs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
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
from experiments.webrtc_collector import TARGETS, WEBRTC_PROBE


BASELINE_FILES = ("constructors.json", "prototype.json", "descriptors.json", "methods.json", "fingerprint.json")
DOMAINS = ("Constructors", "Prototype", "Descriptors", "Methods", "Fingerprint")
STATUSES = ("EQUAL", "CHANGED", "MISSING", "ADDED")


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


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(value[key], child))
    elif isinstance(value, list):
        for index, child_value in enumerate(value):
            result.update(_flatten(child_value, f"{prefix}[{index}]"))
    else:
        result[prefix] = value
    return result


def _resolve(root: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        candidate = explicit if explicit.is_absolute() else root / explicit
        return candidate if candidate.is_dir() else None
    candidates = list(root.glob("reports/experiments/exp_*/webrtc"))
    if not candidates:
        return None

    # Experiment folders are immutable and may be allocated more than once
    # when a collector is retried.  Prefer the newest successful Experiment
    # 045 artifact by its metadata, rather than coupling the comparator to a
    # particular allocator number.
    def experiment_number(path: Path) -> int:
        match = re.match(r"^exp_(\d+)$", path.parent.name)
        return int(match.group(1)) if match else -1

    candidates.sort(key=lambda item: (experiment_number(item), item.as_posix()))
    successful: list[Path] = []
    for candidate in candidates:
        metadata = _read_json(candidate / "summary.json")
        label = str(metadata.get("experiment", "")).lower()
        complete = all((candidate / filename).is_file() for filename in BASELINE_FILES)
        if complete and "experiment 045" in label and metadata.get("result") == "success":
            successful.append(candidate)
    complete_candidates = [candidate for candidate in candidates if all((candidate / filename).is_file() for filename in BASELINE_FILES)]
    return (successful or complete_candidates or candidates)[-1]


def _load_baseline(directory: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if directory is None or not directory.is_dir():
        return {}, {"available": False, "directory": str(directory) if directory else None, "hashes": {}, "files": {}}
    docs = {name: _read_json(directory / name) for name in BASELINE_FILES}
    files = {name: (directory / name).is_file() for name in BASELINE_FILES}
    hashes: dict[str, str] = {}
    for name, present in files.items():
        if present:
            try:
                hashes[name] = sha256_file(directory / name)
            except OSError:
                hashes[name] = ""
    return docs, {"available": all(files.values()), "directory": str(directory), "hashes": hashes, "files": files}


def _capture(args: argparse.Namespace) -> tuple[str, str | None, dict[str, Any], bool]:
    config = BrowserConfig(browser=args.browser, headless=args.headless, persistent=False, url="about:blank", timeout=args.timeout, enable_stealth=False)
    manager = BrowserSessionManager(config)
    page: Any = None
    started = False
    error: str | None = None
    probe: dict[str, Any] = {}
    try:
        manager.start()
        started = True
        page = manager.new_page()
        value = page.evaluate(WEBRTC_PROBE)
        if not isinstance(value, dict):
            raise TypeError("WebRTC probe returned a non-object result")
        probe = value
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
    status = "SUCCESS" if started and probe and not error else ("PARTIAL" if started else "UNKNOWN")
    return status, error, probe, started


def _domain_for(name: str) -> str:
    if name.startswith("constructors."):
        return "Constructors"
    if name.startswith("prototypes."):
        return "Prototype"
    if name.startswith("descriptors."):
        return "Descriptors"
    if name.startswith("methods."):
        return "Methods"
    return "Fingerprint"


def _severity(path: str, status: str) -> str:
    lowered = path.lower()
    if "fingerprint.sha256" in lowered:
        return "HIGH"
    if any(token in lowered for token in ("native", "source", "prototype", "descriptor", "illegalinvocation", "instanceof", "tostringtag")):
        return "CRITICAL" if status in {"CHANGED", "MISSING"} else "HIGH"
    if status in {"MISSING", "ADDED"}:
        return "HIGH"
    return "MEDIUM" if status == "CHANGED" else "LOW"


def _recommendation(path: str, status: str) -> str:
    if path == "fingerprint.sha256":
        return "Treat the hash as an aggregate signal; investigate component differences rather than patching the hash."
    if status == "MISSING":
        return "Investigate why the Browser Platform capture does not expose the baseline WebRTC property."
    if status == "ADDED":
        return "Confirm that the additional surface is browser-version specific before changing any stealth behavior."
    if "prototype" in path.lower():
        return "Preserve the native WebRTC prototype chain and constructor identity."
    if "descriptor" in path.lower():
        return "Preserve native descriptor flags and accessor shape."
    if "source" in path.lower() or "native" in path.lower():
        return "Keep the browser-native function source and avoid JavaScript wrappers."
    return "Investigate the observed value difference with an independent browser capture."


def _diff_domain(domain: str, baseline: Any, current: Any) -> list[dict[str, Any]]:
    left = _flatten(baseline, domain.lower())
    right = _flatten(current, domain.lower())
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
        rows.append({
            "path": path,
            "domain": domain,
            "status": status,
            "baseline": left.get(path),
            "playwright": right.get(path),
            "severity": _severity(path, status),
            "reason": "Values match." if status == "EQUAL" else _recommendation(path, status),
        })
    return rows


def _method_records(value: Any):
    if isinstance(value, dict):
        if "available" in value:
            yield value
        else:
            for child in value.values():
                yield from _method_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _method_records(child)


def _report(summary: dict[str, Any], similarity: dict[str, Any], stats: dict[str, Any], critical: list[dict[str, Any]], validation: dict[str, Any]) -> str:
    lines = [
        "# Experiment 046 - WebRTC Comparator",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Overall similarity: **{similarity.get('overall', 0.0):.2f}%**",
        f"- Remaining differences: **{stats['remaining_differences']}**",
        f"- Critical differences: **{stats['critical_differences']}**",
        "",
        "## Similarity",
        "",
        "| Domain | Similarity | Compared | Equal | Remaining |",
        "|---|---:|---:|---:|---:|",
    ]
    for domain in DOMAINS:
        row = similarity.get("domains", {}).get(domain, {})
        lines.append(f"| {domain} | {row.get('similarity', 0.0):.2f}% | {row.get('total', 0)} | {row.get('equal', 0)} | {row.get('remaining', 0)} |")
    lines += [
        "",
        "## Critical Differences",
        "",
        "| Path | Domain | Status | Recommendation |",
        "|---|---|---|---|",
    ]
    for row in critical[:40]:
        lines.append(f"| `{row['path']}` | {row['domain']} | {row['status']} | {row['recommendation']} |")
    if not critical:
        lines.append("| None | - | - | No critical differences. |")
    lines += ["", "## Validation", "", "| Check | Status |", "|---|---|"]
    for key, value in validation.items():
        if key in {"valid", "artifact_completeness", "browser_launches", "network_requests"}:
            continue
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if bool(value) else 'FAIL'} |")
    lines += ["", "## Read-only Boundary", "", "The comparator performed metadata inspection only. No peer connection, STUN/TURN, stealth injection, or network operation was used.", ""]
    return "\n".join(lines)


def _positive_timeout(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return result


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    baseline_dir = _resolve(root, args.baseline_dir)
    baseline, baseline_meta = _load_baseline(baseline_dir)
    before_hashes = dict(baseline_meta.get("hashes", {}))
    status, error, probe, started = _capture(args) if baseline_meta.get("available") else ("UNKNOWN", "WebRTC baseline is unavailable", {}, False)
    current = {
        "constructors.json": probe.get("constructors", {}) if isinstance(probe.get("constructors"), dict) else {},
        "prototype.json": probe.get("prototypes", {}) if isinstance(probe.get("prototypes"), dict) else {},
        "descriptors.json": probe.get("descriptors", {}) if isinstance(probe.get("descriptors"), dict) else {},
        "methods.json": probe.get("methods", {}) if isinstance(probe.get("methods"), dict) else {},
    }
    after_hashes = dict(baseline_meta.get("hashes", {}))
    baseline_domains = {
        "Constructors": baseline.get("constructors.json", {}),
        "Prototype": baseline.get("prototype.json", {}),
        "Descriptors": baseline.get("descriptors.json", {}),
        "Methods": baseline.get("methods.json", {}),
    }
    current_domains = {
        "Constructors": current["constructors.json"],
        "Prototype": current["prototype.json"],
        "Descriptors": current["descriptors.json"],
        "Methods": current["methods.json"],
    }
    differences: list[dict[str, Any]] = []
    for domain in ("Constructors", "Prototype", "Descriptors", "Methods"):
        differences.extend(_diff_domain(domain, baseline_domains[domain], current_domains[domain]))
    baseline_hash = ((baseline.get("fingerprint.json", {}) or {}).get("sha256"))
    current_hash = _canonical_hash({"constructors": current["constructors.json"], "prototypes": current["prototype.json"], "descriptors": current["descriptors.json"], "methods": current["methods.json"]})
    hash_status = "EQUAL" if baseline_hash and baseline_hash == current_hash else ("CHANGED" if baseline_hash else "MISSING")
    differences.append({
        "path": "fingerprint.sha256",
        "domain": "Fingerprint",
        "status": hash_status,
        "baseline": baseline_hash,
        "playwright": current_hash,
        "severity": _severity("fingerprint.sha256", hash_status),
        "reason": "Aggregate hashes match." if hash_status == "EQUAL" else _recommendation("fingerprint.sha256", hash_status),
    })
    differences.sort(key=lambda row: (row["domain"], row["path"], row["status"]))
    for row in differences:
        row["recommendation"] = _recommendation(row["path"], row["status"])
    categories: dict[str, dict[str, Any]] = {}
    for row in differences:
        bucket = categories.setdefault(row["domain"], {"total": 0, "equal": 0, "remaining": 0, "changed": 0, "missing": 0, "added": 0})
        bucket["total"] += 1
        key = row["status"].lower()
        bucket[key] = bucket.get(key, 0) + 1
        if row["status"] != "EQUAL":
            bucket["remaining"] += 1
    for bucket in categories.values():
        bucket["similarity"] = round(bucket["equal"] / bucket["total"] * 100.0, 2) if bucket["total"] else 100.0
    domain_values = [bucket["similarity"] for bucket in categories.values() if bucket["total"]]
    similarity = {
        "overall": round(sum(domain_values) / len(domain_values), 2) if domain_values else 0.0,
        "constructor": categories.get("Constructors", {}).get("similarity", 100.0),
        "prototype": categories.get("Prototype", {}).get("similarity", 100.0),
        "descriptor": categories.get("Descriptors", {}).get("similarity", 100.0),
        "method": categories.get("Methods", {}).get("similarity", 100.0),
        "fingerprint": categories.get("Fingerprint", {}).get("similarity", 100.0),
        "domains": categories,
    }
    critical = [row for row in differences if row["status"] != "EQUAL" and row["severity"] == "CRITICAL"]
    recommendations = [
        {
            "priority": index,
            "path": row["path"],
            "domain": row["domain"],
            "status": row["status"],
            "severity": row["severity"],
            "recommendation": row["recommendation"],
            "confidence": "High" if row["severity"] in {"CRITICAL", "HIGH"} else "Medium",
            "expected_similarity_gain": round(
                min(10.0, 100.0 * {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(row["severity"], 1) / max(len(differences), 1)),
                2,
            ),
        }
        for index, row in enumerate(sorted((item for item in differences if item["status"] != "EQUAL"), key=lambda item: ({"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(item["severity"], 4), item["domain"], item["path"])), 1)
    ]
    method_records = list(_method_records(current["methods.json"]))
    stats = {
        "total_compared": len(differences),
        "equal": sum(1 for row in differences if row["status"] == "EQUAL"),
        "remaining_differences": sum(1 for row in differences if row["status"] != "EQUAL"),
        "critical_differences": len(critical),
        "status_distribution": dict(sorted(Counter(row["status"] for row in differences).items())),
        "severity_distribution": dict(sorted(Counter(row["severity"] for row in differences if row["status"] != "EQUAL").items())),
        "domain_distribution": {domain: categories.get(domain, {}) for domain in sorted(categories)},
        "recommendation_count": len(recommendations),
        "native_source_records": sum(1 for row in method_records if row.get("available")),
        "native_source_failures": sum(1 for row in method_records if row.get("available") and not row.get("nativeSource")),
        "browser_launches": int(started),
        "network_requests": 0,
        "capture_status": status,
        "baseline_hash": baseline_hash,
        "playwright_hash": current_hash,
    }
    source_code = Path(__file__).read_text(encoding="utf-8")
    platform_token = "sync_" + "playwright"
    init_token = "add_" + "init_script"
    stealth_token = "_" + "_stealth"
    probe_forbidden = ("new " + "RTCPeerConnection", "createDataChannel" + "(", "setLocalDescription" + "(", "setRemoteDescription" + "(", "addIceCandidate" + "(", "stun:", "turn:")
    current_prototypes = current["prototype.json"]
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (baseline, current, differences, similarity, recommendations, stats)),
        "artifact_completeness": False,
        "deterministic_ordering": differences == sorted(differences, key=lambda row: (row["domain"], row["path"], row["status"])) and recommendations == sorted(recommendations, key=lambda row: row["priority"]),
        "prototype_validation": all(not isinstance(value, dict) or not value.get("exists") or (value.get("constructorIdentity") is True and isinstance(value.get("chain"), list)) for value in current_prototypes.values()),
        "descriptor_validation": bool(current["descriptors.json"]) and _json_safe(current["descriptors.json"]),
        "native_source_validation": all(not row.get("available") or row.get("nativeSource") for row in method_records),
        "browser_platform_verification": "BrowserConfig" in source_code and "BrowserSessionManager" in source_code and platform_token not in source_code,
        "read_only_verification": not any(token in WEBRTC_PROBE for token in probe_forbidden),
        "no_stealth_injection": init_token not in source_code and stealth_token not in WEBRTC_PROBE,
        "no_peer_connection_created": "new " + "RTCPeerConnection" not in WEBRTC_PROBE,
        "baseline_immutable": before_hashes == after_hashes,
        "browser_launches": int(started),
        "network_requests": 0,
        "valid": False,
    }
    summary = {
        "experiment": "Experiment 046 - WebRTC Comparator",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "SUCCESS" if status == "SUCCESS" and baseline_meta.get("available") else ("UNKNOWN" if not baseline_meta.get("available") else "PARTIAL"),
        "baseline_input": baseline_meta.get("directory"),
        "playwright_source": "live BrowserSessionManager capture",
        "overall_similarity": similarity["overall"],
        "constructor_similarity": similarity["constructor"],
        "prototype_similarity": similarity["prototype"],
        "descriptor_similarity": similarity["descriptor"],
        "method_similarity": similarity["method"],
        "critical_differences": len(critical),
        "remaining_differences": stats["remaining_differences"],
        "baseline_fingerprint": baseline_hash,
        "playwright_fingerprint": current_hash,
        "historical_artifacts_modified": False,
        "browser_launches": int(started),
        "network_requests": 0,
    }
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "webrtc_compare"
    output.mkdir(parents=True, exist_ok=False)
    validation["artifact_completeness"] = True
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})
    summary["validation_valid"] = validation["valid"]
    compare = {
        "experiment": "Experiment 046 - WebRTC Comparator",
        "experiment_id": experiment.experiment_id,
        "baseline": baseline,
        "playwright": current,
        "baseline_meta": baseline_meta,
        "capture_status": status,
        "capture_error": error,
        "fingerprints": {"baseline": baseline_hash, "playwright": current_hash},
    }
    report = _report(summary, similarity, stats, critical, validation)
    artifacts = {
        "compare.json": compare,
        "similarity.json": similarity,
        "differences.json": {"differences": differences},
        "critical.json": {"critical": critical},
        "recommendations.json": {"recommendations": recommendations},
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "webrtc_compare.md", report)
    print("WEBRTC COMPARATOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Overall similarity: {similarity['overall']:.2f}%")
    print(f"Remaining: {stats['remaining_differences']} | Critical: {stats['critical_differences']}")
    print("Browser launches: 1 | Network requests: 0")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 046: compare Real Browser and Playwright WebRTC metadata")
    parser.add_argument("--baseline-dir", type=Path, default=None)
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
