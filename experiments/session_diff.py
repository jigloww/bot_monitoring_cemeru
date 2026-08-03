"""Experiment 021: deterministic, read-only browser session diff.

Two existing ``session_profile`` directories are compared without launching a
browser.  Source artifacts are never rewritten; only a new immutable
``session_diff`` allocation is created through the experiment framework.
"""
from __future__ import annotations

import argparse
import json
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    git_metadata,
    now_iso,
    project_root,
    relative_path,
    read_json,
    sha256_file,
    system_metadata,
    write_json_exclusive,
    write_text_exclusive,
)


DOMAINS = (
    "browser", "navigator", "window", "screen", "storage", "cookies", "permissions",
    "extensions", "webgl", "performance", "memory", "environment", "fingerprint",
)
DOMAIN_FILES = {domain: f"{domain}.json" for domain in DOMAINS}
EXTRA_FILES = {"profile": "profile.json", "summary": "summary.json"}
STATUS_VALUES = {"UNCHANGED", "CHANGED", "ADDED", "REMOVED", "UNKNOWN"}
SEVERITY_VALUES = {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
STATUS_ORDER = ("UNCHANGED", "CHANGED", "ADDED", "REMOVED", "UNKNOWN")
SEVERITY_ORDER = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
IGNORED_FIELDS = {"experiment_id", "created_at", "run_id"}
MISSING = object()


@dataclass(frozen=True)
class Session:
    label: str
    path: Path
    artifacts: dict[str, Any]
    missing: set[str]
    summary: dict[str, Any]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _flatten(value: Any, path: str = "$") -> dict[str, Any]:
    if isinstance(value, dict):
        if not value:
            return {path: {}}
        result: dict[str, Any] = {}
        for key in sorted(value, key=str):
            result.update(_flatten(value[key], f"{path}.{key}"))
        return result
    if isinstance(value, list):
        if not value:
            return {path: []}
        result = {}
        for index, item in enumerate(value):
            result.update(_flatten(item, f"{path}[{index}]"))
        return result
    return {path: value}


def _volatile(path: str) -> bool:
    return any(path.rsplit(".", 1)[-1] == field for field in IGNORED_FIELDS)


def _severity(path: str, status: str) -> str:
    lower = path.lower()
    if status == "UNKNOWN":
        return "CRITICAL" if path == "$" else "MEDIUM"
    if any(token in lower for token in ("useragent", "user_agent", "timezone", "webdriver", "platform", "vendor")):
        return "HIGH"
    if any(token in lower for token in ("fingerprint_hash", "profile_hash", "environment_hash", "hashes", "renderer", "webgl", "permission", "extension", "storage", "indexeddb", "cache")):
        return "MEDIUM"
    if any(token in lower for token in ("cookie_count", "cookie", "plugin", "mimetype", "fonts", "speech")):
        return "LOW"
    if any(token in lower for token in ("performance", "duration", "memory", "heap", "now", "timeorigin")):
        return "INFO"
    return "LOW" if status in {"ADDED", "REMOVED"} else "INFO"


def _reason(status: str, path: str, old: Any, new: Any) -> str:
    if status == "UNCHANGED":
        return "The snapshot values are equal."
    if status == "ADDED":
        return "The field is present only in session B."
    if status == "REMOVED":
        return "The field is present only in session A."
    if status == "UNKNOWN":
        return "The source artifact or field was unavailable; no behavioral conclusion is possible."
    if "timezone" in path.lower():
        return "Timezone changed between sessions and can affect locale-sensitive behavior."
    if "useragent" in path.lower() or "user_agent" in path.lower():
        return "User-agent metadata changed between sessions."
    if "cookie" in path.lower():
        return "Cookie metadata changed between sessions; values are not compared."
    if "performance" in path.lower() or "memory" in path.lower():
        return "Runtime timing or memory is expected to vary between sessions."
    return "The field value differs between the two snapshots."


def _confidence(status: str, old: Any, new: Any) -> str:
    if status == "UNKNOWN":
        return "Low"
    if isinstance(old, (dict, list)) or isinstance(new, (dict, list)):
        return "Medium"
    return "High"


def _record(path: str, old: Any, new: Any, status: str) -> dict[str, Any]:
    severity = _severity(path, status)
    return {"path": path, "old_value": None if old is MISSING else old, "new_value": None if new is MISSING else new,
        "status": status, "severity": severity, "reason": _reason(status, path, old, new), "confidence": _confidence(status, old, new)}


def _compare_values(domain: str, old: Any, new: Any) -> list[dict[str, Any]]:
    left = _flatten(old) if old is not MISSING else {}
    right = _flatten(new) if new is not MISSING else {}
    records = []
    for path in sorted(set(left) | set(right)):
        if _volatile(path):
            records.append(_record(f"{domain}{path}", left.get(path, MISSING), right.get(path, MISSING), "UNKNOWN"))
            records[-1]["severity"] = "INFO"
            records[-1]["reason"] = "Experiment metadata is intentionally excluded from similarity."
            records[-1]["confidence"] = "High"
            continue
        old_value, new_value = left.get(path, MISSING), right.get(path, MISSING)
        if old_value is MISSING:
            status = "ADDED"
        elif new_value is MISSING:
            status = "REMOVED"
        elif _canonical(old_value) == _canonical(new_value):
            status = "UNCHANGED"
        else:
            status = "CHANGED"
        records.append(_record(f"{domain}{path}", old_value, new_value, status))
    return records


def _stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {status.lower() + "_fields": sum(item.get("status") == status for item in records) for status in STATUS_ORDER}
    comparable = [item for item in records if item.get("status") != "UNKNOWN"]
    unchanged = sum(item.get("status") == "UNCHANGED" for item in comparable)
    similarity = round(unchanged / len(comparable) * 100, 2) if comparable else None
    severity = {name.lower() + "_changes": sum(item.get("severity") == name and item.get("status") != "UNCHANGED" for item in records) for name in ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")}
    return {"total_fields": len(records), "unchanged_fields": counts.get("unchanged_fields", 0), "changed_fields": counts.get("changed_fields", 0), "added_fields": counts.get("added_fields", 0), "removed_fields": counts.get("removed_fields", 0), "unknown_fields": counts.get("unknown_fields", 0), "comparable_fields": len(comparable), "similarity": similarity, **severity}


def _load_session(label: str, raw_path: str, root: Path) -> Session:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (root / path).resolve()
    artifacts: dict[str, Any] = {}
    missing: set[str] = set()
    for domain, filename in DOMAIN_FILES.items():
        artifact = path / filename
        try:
            artifacts[domain] = read_json(artifact)
        except (OSError, ValueError, TypeError):
            artifacts[domain] = MISSING
            missing.add(domain)
    for domain, filename in EXTRA_FILES.items():
        artifact = path / filename
        try:
            artifacts[domain] = read_json(artifact)
        except (OSError, ValueError, TypeError):
            artifacts[domain] = MISSING
            missing.add(domain)
    summary = artifacts.get("summary") if isinstance(artifacts.get("summary"), dict) else {}
    return Session(label=label, path=path, artifacts=artifacts, missing=missing, summary=summary)


def _domain_diff(domain: str, first: Session, second: Session) -> dict[str, Any]:
    old, new = first.artifacts.get(domain, MISSING), second.artifacts.get(domain, MISSING)
    records = _compare_values(domain, old, new)
    if old is MISSING or new is MISSING:
        records = [_record(domain + "$", old, new, "UNKNOWN")]
    return {"domain": domain, "session_a": str(first.path), "session_b": str(second.path), "changes": records, "statistics": _stats(records), "source_unknown": domain in first.missing or domain in second.missing}


def _fingerprint_diff(first: Session, second: Session) -> tuple[dict[str, Any], dict[str, Any]]:
    old = first.artifacts.get("fingerprint", MISSING)
    new = second.artifacts.get("fingerprint", MISSING)
    result = _domain_diff("fingerprint", first, second)
    old_hashes = old.get("hashes", {}) if isinstance(old, dict) else {}
    new_hashes = new.get("hashes", {}) if isinstance(new, dict) else {}
    keys = sorted(set(old_hashes) | set(new_hashes))
    module_records = []
    for key in keys:
        left, right = old_hashes.get(key, MISSING), new_hashes.get(key, MISSING)
        if left is MISSING:
            status = "ADDED"
        elif right is MISSING:
            status = "REMOVED"
        elif left == right:
            status = "UNCHANGED"
        else:
            status = "CHANGED"
        module_records.append(_record(f"fingerprint.hashes.{key}", left, right, status))
    comparable = [item for item in module_records if item["status"] != "UNKNOWN"]
    match = round(sum(item["status"] == "UNCHANGED" for item in comparable) / len(comparable) * 100, 2) if comparable else None
    result["module_hashes"] = module_records
    result["module_statistics"] = {"total_modules": len(module_records), "unchanged_modules": sum(item["status"] == "UNCHANGED" for item in module_records), "changed_modules": [item["path"].rsplit(".", 1)[-1] for item in module_records if item["status"] == "CHANGED"], "match_percentage": match}
    summary_hashes = []
    for key in ("fingerprint_hash", "profile_hash", "environment_hash"):
        left, right = first.summary.get(key, MISSING), second.summary.get(key, MISSING)
        if left is MISSING:
            status = "ADDED"
        elif right is MISSING:
            status = "REMOVED"
        elif left == right:
            status = "UNCHANGED"
        else:
            status = "CHANGED"
        summary_hashes.append(_record(f"fingerprint.summary.{key}", left, right, status))
    result["summary_hashes"] = summary_hashes
    result["statistics"]["fingerprint_match_percentage"] = match
    return result, {"old_hashes": old_hashes, "new_hashes": new_hashes, "module_records": module_records, "match_percentage": match}


def _major_findings(domain_results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    seen: set[tuple[Any, ...]] = set()
    for result in domain_results.values():
        for key in ("changes", "module_hashes", "summary_hashes"):
            for record in result.get(key, []):
                if record.get("status") == "UNCHANGED" or (record.get("status") == "UNKNOWN" and record.get("severity") == "INFO"):
                    continue
                normalized_path = str(record.get("path", "")).replace("fingerprint$.", "fingerprint.")
                identity = (normalized_path, record.get("status"), _canonical(record.get("old_value")), _canonical(record.get("new_value")))
                if identity not in seen:
                    normalized = dict(record)
                    normalized["path"] = normalized_path
                    records.append(normalized)
                    seen.add(identity)
    records.sort(key=lambda item: (SEVERITY_ORDER.get(item.get("severity", "INFO"), 0), item.get("path", "")), reverse=True)
    return records[:20]


def _overall_stats(domain_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    records = [record for result in domain_results.values() for record in result.get("changes", [])]
    return _stats(records)


def _report(summary: dict[str, Any], domain_results: dict[str, dict[str, Any]], fingerprint: dict[str, Any], output: Path) -> str:
    lines = ["# Experiment 021 — Session Diff Analyzer", "", "Analysis-only comparison. Source session artifacts were read but never changed.", "", "## Executive Summary", "", f"Result: **{summary['result']}**", f"Session A: `{summary['session_a']}`", f"Session B: `{summary['session_b']}`", f"Overall similarity: **{summary['overall_similarity']}%**", "", "## Overall Similarity", "", "| Metric | Similarity |", "|---|---:|", f"| Overall | {summary['overall_similarity']}% |", f"| Fingerprint | {summary['fingerprint_similarity']}% |", f"| Environment | {summary['environment_similarity']}% |", f"| Profile | {summary['profile_similarity']}% |", ""]
    for domain, title in (("browser", "Browser Comparison"), ("navigator", "Navigator Comparison"), ("storage", "Storage Comparison"), ("permissions", "Permissions Comparison"), ("environment", "Environment Comparison")):
        result = domain_results.get(domain, {})
        lines += [f"## {title}", "", f"Similarity: **{result.get('statistics', {}).get('similarity')}%**", "", "| Path | Status | Severity | Reason |", "|---|---|---|---|"]
        changes = [item for item in result.get("changes", []) if item.get("status") != "UNCHANGED"][:30]
        if not changes:
            lines.append("| — | UNCHANGED | INFO | No comparable difference observed. |")
        for item in changes:
            reason = str(item.get("reason", "")).replace("|", "\\|")
            lines.append(f"| `{item.get('path')}` | {item.get('status')} | {item.get('severity')} | {reason} |")
        lines.append("")
    lines += ["## Fingerprint Comparison", "", f"Module match: **{fingerprint.get('match_percentage')}%**", "", "| Module | Status |", "|---|---|"]
    for item in fingerprint.get("module_records", []):
        lines.append(f"| {item['path'].rsplit('.', 1)[-1]} | {item['status']} |")
    lines += ["", "## High Severity Changes", "", "| Path | Status | Severity | Old | New |", "|---|---|---|---|---|"]
    findings = summary.get("major_findings", [])
    high = [item for item in findings if item.get("severity") in {"CRITICAL", "HIGH"}]
    if not high:
        lines.append("| — | — | — | No high severity change | — |")
    for item in high:
        lines.append(f"| `{item.get('path')}` | {item.get('status')} | {item.get('severity')} | `{str(item.get('old_value'))[:120]}` | `{str(item.get('new_value'))[:120]}` |")
    lines += ["", "## Recommendations", ""]
    for recommendation in summary.get("recommendation", []):
        lines.append(f"- {recommendation}")
    lines += ["", "## Final Conclusion", "", f"Sessions are classified **{summary['result']}** based on comparable fields. Similarity is structural and does not prove browser equivalence or Cloudflare behavior.", "", f"Artifacts: `{output}`", ""]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment 021: compare two immutable browser session snapshots")
    parser.add_argument("--session-a", required=True)
    parser.add_argument("--session-b", required=True)
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def _validate(output: Path, summary: dict[str, Any], domain_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    required = ["diff.json", "browser_diff.json", "navigator_diff.json", "window_diff.json", "screen_diff.json", "storage_diff.json", "cookies_diff.json", "permissions_diff.json", "extensions_diff.json", "webgl_diff.json", "performance_diff.json", "memory_diff.json", "environment_diff.json", "statistics.json", "summary.json", "session_diff.md"]
    missing = [name for name in required if not (output / name).is_file()]
    similarities = [summary.get("overall_similarity"), summary.get("fingerprint_similarity"), summary.get("environment_similarity"), summary.get("profile_similarity")]
    similarity_valid = all(value is None or 0 <= value <= 100 for value in similarities)
    statuses_valid = all(item.get("status") in STATUS_VALUES and item.get("severity") in SEVERITY_VALUES for result in domain_results.values() for item in result.get("changes", []))
    report = (output / "session_diff.md").read_text(encoding="utf-8") if (output / "session_diff.md").is_file() else ""
    sections_valid = all(section in report for section in ("Executive Summary", "Overall Similarity", "Browser Comparison", "Navigator Comparison", "Storage Comparison", "Permissions Comparison", "Environment Comparison", "Fingerprint Comparison", "High Severity Changes", "Recommendations", "Final Conclusion"))
    return {"artifact_completeness": not missing, "missing_artifacts": missing, "similarity_calculation_valid": similarity_valid, "statuses_valid": statuses_valid, "markdown_valid": sections_valid, "deterministic_domain_count": len(domain_results) == len(DOMAINS)}


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    args = _parser().parse_args(argv)
    root = project_root()
    first = _load_session("session_a", args.session_a, root)
    second = _load_session("session_b", args.session_b, root)
    experiment = Experiment.create((args.reports_dir or root / "reports" / "experiments").resolve())
    output = experiment.directory / "session_diff"
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"experiment": "Experiment 021 — Session Diff Analyzer", "experiment_id": experiment.experiment_id, "created_at": experiment.started_at, "session_a": relative_path(first.path, root), "session_b": relative_path(second.path, root), "analysis_only": True, "browser_launches": 0, "source_artifacts_modified": False, "environment": system_metadata(), "git": git_metadata(root)}
    write_json_exclusive(output / "metadata.json", metadata)
    domain_results: dict[str, dict[str, Any]] = {}
    for domain in DOMAINS:
        if domain == "fingerprint":
            result, _ = _fingerprint_diff(first, second)
        else:
            result = _domain_diff(domain, first, second)
        domain_results[domain] = result
        write_json_exclusive(output / f"{domain}_diff.json", result)
    # ``profile.json`` contains context/profile metadata and is not one of
    # the browser-behavior domains, but its similarity is reported separately
    # because it is a required session-level signal.
    profile_result = _domain_diff("profile", first, second)
    overall = _overall_stats(domain_results)
    fingerprint = domain_results["fingerprint"].get("module_statistics", {})
    profile_similarity = profile_result.get("statistics", {}).get("similarity")
    environment_similarity = domain_results["environment"].get("statistics", {}).get("similarity")
    fingerprint_similarity = fingerprint.get("match_percentage")
    overall_similarity = overall.get("similarity")
    findings = _major_findings({**domain_results, "profile": profile_result})
    recommendation = []
    if any(item.get("severity") == "CRITICAL" for item in findings):
        recommendation.append("Investigate missing or unavailable session artifacts before drawing behavioral conclusions.")
    if any(item.get("severity") == "HIGH" for item in findings):
        recommendation.append("Review high-impact browser identity and timezone changes; keep profile configuration stable for controlled comparisons.")
    if not recommendation:
        recommendation.append("No high-impact difference was observed; repeat with a valid browser session when optional APIs are available.")
    source_unknown = bool(first.missing or second.missing or first.summary.get("result") == "UNKNOWN" or second.summary.get("result") == "UNKNOWN")
    if source_unknown:
        result = "UNKNOWN"
    elif overall_similarity == 100 and fingerprint_similarity in {100, None}:
        result = "IDENTICAL"
    elif overall_similarity is not None and overall_similarity >= 80:
        result = "SIMILAR"
    else:
        result = "DIFFERENT"
    summary = {"experiment": "Experiment 021 — Session Diff Analyzer", "experiment_id": experiment.experiment_id, "session_a": relative_path(first.path, root), "session_b": relative_path(second.path, root), "overall_similarity": overall_similarity, "fingerprint_similarity": fingerprint_similarity, "environment_similarity": environment_similarity, "profile_similarity": profile_similarity, "critical_changes": overall.get("critical_changes", 0), "major_findings": findings, "recommendation": recommendation, "result": result, "source_unknown": source_unknown, "statistics": {**overall, "fingerprint_similarity": fingerprint_similarity, "environment_similarity": environment_similarity, "profile_similarity": profile_similarity}, "created_at": now_iso()}
    write_json_exclusive(output / "diff.json", {"experiment_id": experiment.experiment_id, "domains": {**domain_results, "profile": profile_result}, "statistics": summary["statistics"]})
    write_json_exclusive(output / "statistics.json", summary["statistics"])
    write_json_exclusive(output / "summary.json", summary)
    write_text_exclusive(output / "session_diff.md", _report(summary, domain_results, {"module_records": domain_results["fingerprint"].get("module_hashes", []), "match_percentage": fingerprint_similarity}, output))
    validation = _validate(output, summary, domain_results)
    write_json_exclusive(output / "validation.json", validation)
    print("\nSESSION DIFF ANALYZER")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Result: {result}")
    print(f"Overall similarity: {overall_similarity}%")
    print(f"Fingerprint similarity: {fingerprint_similarity}%")
    print(f"Artifacts: {relative_path(output, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
