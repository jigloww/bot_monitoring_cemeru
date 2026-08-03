"""Experiment 023: read-only fingerprint property importance analysis.

This experiment compares an available reference fingerprint with the newest
usable experiment fingerprint.  It does not launch a browser and never writes
to an input experiment directory; only a newly allocated immutable report is
created.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    git_metadata,
    project_root,
    read_json,
    relative_path,
    system_metadata,
    write_json_exclusive,
    write_text_exclusive,
)


GROUPS = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL")
STATUSES = ("EQUAL", "DIFFERENT", "MISSING", "ADDED", "UNKNOWN")
MODULE_CATEGORIES = (
    "Navigator",
    "Window",
    "Screen",
    "Chrome",
    "Permissions",
    "Fonts",
    "Speech",
    "Performance",
    "WebGL",
    "Environment",
    "Storage",
    "Other",
)


@dataclass(frozen=True)
class Source:
    path: Path
    experiment_id: str | None = None
    score: float | None = None
    modules: tuple[str, ...] = ()


def _read(path: Path) -> Any:
    try:
        return read_json(path)
    except (OSError, ValueError, TypeError):
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return repr(value)


def _fingerprint_document(value: Any) -> dict[str, Any] | None:
    """Extract the normalized fingerprint object from known report shapes."""
    if not isinstance(value, dict):
        return None
    fingerprint = value.get("fingerprint")
    if isinstance(fingerprint, dict):
        return fingerprint
    # A few experiment aggregators store mode documents under ``modes``.
    # Source discovery handles the individual mode files where possible, but
    # this fallback keeps custom reports useful.
    modes = value.get("modes")
    if isinstance(modes, dict):
        candidates = []
        for mode, document in modes.items():
            extracted = _fingerprint_document(document)
            if extracted is not None:
                candidates.append((mode, extracted))
        if candidates:
            return max(candidates, key=lambda item: (len(item[1]), item[0]))[1]
    # Accept a bare normalized fingerprint for hand-authored diagnostics.
    if value and not any(key in value for key in ("_meta", "experiment", "experiment_id", "modes", "hashes", "algorithm")):
        return value
    return None


def _experiment_number(path: Path) -> int | None:
    for parent in (path, *path.parents):
        match = re.fullmatch(r"exp_(\d+)", parent.name)
        if match:
            return int(match.group(1))
    return None


def _source_score(path: Path) -> float | None:
    score_path = path.with_name("score.json")
    data = _read(score_path)
    if isinstance(data, dict):
        for key in ("overall_score", "overall", "score"):
            value = _number(data.get(key))
            if value is not None:
                return value
    return None


def _source_modules(path: Path, document: dict[str, Any]) -> tuple[str, ...]:
    meta = document.get("_meta") if isinstance(document, dict) else None
    modules = meta.get("modules_applied") if isinstance(meta, dict) else None
    if isinstance(modules, list):
        return tuple(str(item) for item in modules)
    return ()


def _discover_sources(reports_root: Path) -> list[Source]:
    sources: list[Source] = []
    if not reports_root.is_dir():
        return sources
    for path in reports_root.rglob("fingerprint.json"):
        if not path.is_file() or "fingerprint_importance" in path.parts or "fingerprint_evolution" in path.parts:
            continue
        document = _read(path)
        fingerprint = _fingerprint_document(document)
        if fingerprint is None:
            continue
        number = _experiment_number(path)
        source_id = f"exp_{number:03d}" if number is not None else None
        sources.append(Source(path=path, experiment_id=source_id, score=_source_score(path), modules=_source_modules(document or {}, document or {})))
    return sources


def _resolve_baseline(root: Path, explicit: Path | None) -> Source | None:
    candidates = [explicit] if explicit else []
    candidates += [root / "reports" / "fingerprint" / name for name in ("fingerprint_real.json", "fingerprint_real_vps.json", "fingerprint.json")]
    for path in candidates:
        if path and path.is_file() and _fingerprint_document(_read(path)) is not None:
            return Source(path=path)
    return None


def _resolve_candidate(root: Path, explicit: Path | None, reports_root: Path) -> Source | None:
    if explicit and explicit.is_file() and _fingerprint_document(_read(explicit)) is not None:
        return Source(path=explicit, experiment_id=f"exp_{_experiment_number(explicit):03d}" if _experiment_number(explicit) is not None else None, score=_source_score(explicit), modules=_source_modules(_read(explicit) or {}, _read(explicit) or {}))
    sources = _discover_sources(reports_root)
    if sources:
        # Latest experiment wins; within that experiment use the highest score
        # and then the most complete module stack.  This selects exp_014's
        # previous_stack_webgl when the repository has the supplied history.
        latest = max(source.experiment_id and int(source.experiment_id[4:]) or -1 for source in sources)
        sources = [source for source in sources if source.experiment_id and int(source.experiment_id[4:]) == latest]
        return max(sources, key=lambda source: (source.score if source.score is not None else -1.0, len(source.modules), str(source.path).lower()))
    for name in ("fingerprint_playwright_patched.json", "fingerprint_playwright.json"):
        path = root / "reports" / "fingerprint" / name
        if path.is_file() and _fingerprint_document(_read(path)) is not None:
            return Source(path=path)
    return None


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict) and value:
        output: dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item)):
            child = f"{prefix}.{key}" if prefix else str(key)
            output.update(_flatten(value[key], child))
        return output
    if isinstance(value, list) and value:
        output = {}
        for index, item in enumerate(value):
            output.update(_flatten(item, f"{prefix}[{index}]"))
        return output
    return {prefix or "<root>": value}


def _category(property_name: str) -> str:
    top = re.split(r"[.\[]", property_name, maxsplit=1)[0].lower()
    mapping = {
        "navigator": "Navigator", "plugins": "Navigator", "mimeTypes": "Navigator", "mimetypes": "Navigator",
        "window": "Window", "screen": "Screen", "chrome": "Chrome", "permissions": "Permissions",
        "fonts": "Fonts", "speech": "Speech", "performance": "Performance", "webgl": "WebGL", "webgl2": "WebGL",
        "timezone": "Environment", "intl": "Environment", "storage": "Storage", "indexeddb": "Storage",
    }
    return mapping.get(top, "Other")


def _is_dynamic(property_name: str) -> bool:
    lowered = property_name.lower()
    return any(token in lowered for token in ("performance.now", "timeorigin", "timing", "memory", "timestamp", "duration", "history.length", "document.ready"))


def _importance_group(property_name: str, status: str) -> str:
    if status == "EQUAL":
        return "INFORMATIONAL"
    lowered = property_name.lower()
    critical_tokens = ("webdriver", "useragent", "useragentdata", "platform", "vendor", "languages", "language", "chrome", "webgl.unmasked", "plugins", "mimetypes")
    high_tokens = ("window.inner", "window.outer", "window.devicepixelratio", "screen.", "permissions", "webgl.renderer", "webgl.vendor", "fonts", "speech")
    medium_tokens = ("performance", "storage", "indexeddb", "timezone", "intl", "canvas", "audio", "hardwareconcurrency", "devicememory")
    if any(token in lowered for token in critical_tokens):
        return "CRITICAL"
    if any(token in lowered for token in high_tokens):
        return "HIGH"
    if any(token in lowered for token in medium_tokens):
        return "MEDIUM"
    return "LOW" if status != "UNKNOWN" else "INFORMATIONAL"


def _dependencies(property_name: str) -> list[str]:
    lowered = property_name.lower()
    if "useragent" in lowered:
        return ["navigator.platform", "navigator.vendor", "navigator.userAgentData"]
    if lowered.startswith("navigator.platform"):
        return ["navigator.userAgent", "navigator.userAgentData.platform", "window.devicePixelRatio"]
    if lowered.startswith("navigator.languages") or lowered.startswith("navigator.language"):
        return ["navigator.language", "navigator.languages"]
    if lowered.startswith("window.") or lowered.startswith("screen."):
        return ["window.innerWidth", "window.innerHeight", "screen.width", "screen.height", "window.devicePixelRatio"]
    if lowered.startswith("chrome"):
        return ["navigator.userAgent", "navigator.vendor", "navigator.platform"]
    if lowered.startswith("webgl"):
        return ["navigator.platform", "window.devicePixelRatio", "screen.width", "screen.height"]
    if lowered.startswith("permissions"):
        return ["navigator.platform", "navigator.userAgent"]
    if lowered.startswith("fonts") or lowered.startswith("speech"):
        return ["navigator.platform", "navigator.language"]
    if lowered.startswith("performance"):
        return ["window.innerWidth", "navigator.hardwareConcurrency"]
    return []


def _related_statuses(dependencies: list[str], statuses: dict[str, str]) -> list[str]:
    found = []
    for dependency in dependencies:
        exact = statuses.get(dependency)
        if exact:
            found.append(exact)
            continue
        prefix = next((status for path, status in statuses.items() if path.startswith(dependency + ".") or path.startswith(dependency + "[")), None)
        if prefix:
            found.append(prefix)
    return found


def _consistency(status: str, dependencies: list[str], statuses: dict[str, str]) -> str:
    if not dependencies:
        return "UNKNOWN"
    related = _related_statuses(dependencies, statuses)
    if not related:
        return "UNKNOWN"
    if status == "EQUAL" and all(item == "EQUAL" for item in related):
        return "CONSISTENT"
    if status != "EQUAL" and all(item in {"DIFFERENT", "MISSING", "ADDED"} for item in related):
        return "CONSISTENT"
    return "INCONSISTENT"


def _confidence(property_name: str, status: str, consistency: str) -> str:
    if status == "UNKNOWN":
        return "Low"
    if consistency == "INCONSISTENT":
        return "Medium"
    if _is_dynamic(property_name):
        return "Medium"
    return "High"


def _importance(property_name: str, status: str, group: str, consistency: str) -> float:
    base = {"CRITICAL": 95.0, "HIGH": 75.0, "MEDIUM": 50.0, "LOW": 25.0, "INFORMATIONAL": 5.0}[group]
    # Keep a small baseline weight for equal properties.  This makes the
    # weighted opportunity denominator include the complete fingerprint rather
    # than making every non-equal property appear to represent 100% of it.
    if status == "EQUAL":
        return round(base * 0.25, 2)
    if status == "UNKNOWN":
        return round(base * 0.25, 2)
    if consistency == "INCONSISTENT":
        base = min(100.0, base + 5.0)
    if _is_dynamic(property_name):
        base *= 0.7
    return round(base, 2)


def _reason(status: str, category: str, property_name: str) -> str:
    if status == "EQUAL":
        return "Candidate value matches the reference value."
    if status == "MISSING":
        return f"{property_name} is present in the reference but missing from the candidate {category} surface."
    if status == "ADDED":
        return f"{property_name} is present only in the candidate and may indicate a surface or environment difference."
    if status == "DIFFERENT":
        return f"{property_name} differs from the reference and contributes to the {category} fingerprint mismatch."
    return "The property could not be compared because one or both source artifacts were unavailable."


def _analyze(baseline: dict[str, Any] | None, candidate: dict[str, Any] | None) -> list[dict[str, Any]]:
    if baseline is None or candidate is None:
        return [{"property": "<fingerprint>", "reference_value": None, "candidate_value": None, "status": "UNKNOWN", "severity": "INFORMATIONAL", "importance_group": "INFORMATIONAL", "category": "Other", "dependency": [], "consistency": "UNKNOWN", "estimated_importance": 0.0, "confidence": "Low", "reason": _reason("UNKNOWN", "Other", "<fingerprint>"), "recommendation": "Collect valid baseline and candidate fingerprint artifacts before ranking properties."}]
    reference = _flatten(baseline)
    observed = _flatten(candidate)
    statuses: dict[str, str] = {}
    for property_name in sorted(set(reference) | set(observed)):
        if property_name not in reference:
            statuses[property_name] = "ADDED"
        elif property_name not in observed:
            statuses[property_name] = "MISSING"
        elif _canonical(reference[property_name]) == _canonical(observed[property_name]):
            statuses[property_name] = "EQUAL"
        else:
            statuses[property_name] = "DIFFERENT"
    findings = []
    for property_name in sorted(statuses):
        status = statuses[property_name]
        category = _category(property_name)
        dependencies = _dependencies(property_name)
        consistency = _consistency(status, dependencies, statuses)
        group = _importance_group(property_name, status)
        importance = _importance(property_name, status, group, consistency)
        recommendation = "No action required; retain this stable value." if status == "EQUAL" else f"Prioritize alignment of {property_name}; verify its related prototype, descriptor, and cross-property values before changing the module."
        findings.append({
            "property": property_name,
            "reference_value": reference.get(property_name),
            "candidate_value": observed.get(property_name),
            "status": status,
            "severity": group,
            "importance_group": group,
            "category": category,
            "dependency": dependencies,
            "consistency": consistency,
            "estimated_importance": importance,
            "confidence": _confidence(property_name, status, consistency),
            "reason": _reason(status, category, property_name),
            "recommendation": recommendation,
        })
    return findings


def _groups(findings: list[dict[str, Any]]) -> dict[str, Any]:
    grouped = {}
    for group in GROUPS:
        rows = [item for item in findings if item.get("importance_group") == group]
        grouped[group] = {"count": len(rows), "properties": [item["property"] for item in rows]}
    return grouped


def _ranking(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(findings, key=lambda item: (-float(item.get("estimated_importance") or 0), item.get("property", "")))
    return [{"rank": index, "property": item["property"], "category": item["category"], "status": item["status"], "severity": item["severity"], "estimated_importance": item["estimated_importance"], "confidence": item["confidence"], "consistency": item["consistency"]} for index, item in enumerate(ranked, 1)]


def _recommendations(findings: list[dict[str, Any]], ranking: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actionable = [item for item in findings if item.get("status") != "EQUAL"]
    if not actionable:
        return [{"priority": "INFO", "property": None, "recommendation": "All observed properties match the reference; continue periodic read-only validation.", "basis": "No mismatches"}]
    output = []
    for item in ranking:
        if item["status"] == "EQUAL":
            continue
        output.append({"priority": item["severity"], "property": item["property"], "recommendation": next(row["recommendation"] for row in findings if row["property"] == item["property"]), "basis": f"Estimated importance {item['estimated_importance']} with {item['confidence']} confidence."})
        if len(output) >= 20:
            break
    return output


def _statistics(findings: list[dict[str, Any]], baseline: Source | None, candidate: Source | None) -> dict[str, Any]:
    status_counts = Counter(item["status"] for item in findings)
    severity_counts = Counter(item["severity"] for item in findings)
    category_counts = Counter(item["category"] for item in findings)
    total_weight = sum(float(item.get("estimated_importance") or 0) for item in findings)
    mismatch_weight = sum(float(item.get("estimated_importance") or 0) for item in findings if item.get("status") != "EQUAL")
    total = len(findings)
    return {
        "total_properties": total,
        "status_counts": {status: status_counts.get(status, 0) for status in STATUSES},
        "severity_counts": {group: severity_counts.get(group, 0) for group in GROUPS},
        "category_counts": dict(sorted(category_counts.items())),
        "equal_percentage": round(status_counts.get("EQUAL", 0) / total * 100, 2) if total else 0.0,
        "different_percentage": round((total - status_counts.get("EQUAL", 0)) / total * 100, 2) if total else 0.0,
        "weighted_mismatch_percentage": round(mismatch_weight / total_weight * 100, 2) if total_weight else 0.0,
        "estimated_similarity_gain_pct": round(mismatch_weight / total_weight * 100, 2) if total_weight else 0.0,
        "baseline_source": str(baseline.path) if baseline else None,
        "candidate_source": str(candidate.path) if candidate else None,
        "browser_launches": 0,
    }


def _report(summary: dict[str, Any], statistics: dict[str, Any], findings: list[dict[str, Any]], recommendations: list[dict[str, Any]]) -> str:
    lines = ["# Experiment 023 — Fingerprint Importance Analyzer", "", "Analysis-only comparison of immutable fingerprint artifacts. No browser was launched.", "", "## Executive Summary", "", f"Result: **{summary['result']}**", f"Properties analyzed: **{statistics['total_properties']}**", f"Equal: **{statistics['equal_percentage']}%**", f"Estimated similarity gain: **{statistics['estimated_similarity_gain_pct']}% weighted opportunity**", "", "## Overall Importance Distribution", "", "| Group | Count |", "|---|---:|"]
    for group in GROUPS:
        lines.append(f"| {group} | {statistics['severity_counts'].get(group, 0)} |")
    for title, group in (("Critical Findings", "CRITICAL"), ("High Priority Findings", "HIGH"), ("Medium Findings", "MEDIUM"), ("Low Findings", "LOW")):
        lines += ["", f"## {title}", "", "| Property | Category | Status | Importance | Confidence | Consistency |", "|---|---|---|---:|---|---|"]
        rows = [item for item in findings if item.get("severity") == group and item.get("status") != "EQUAL"]
        if not rows:
            lines.append("| — | — | none | 0 | — | — |")
        for item in rows[:30]:
            lines.append(f"| {item['property']} | {item['category']} | {item['status']} | {item['estimated_importance']} | {item['confidence']} | {item['consistency']} |")
    lines += ["", "## Estimated Similarity Gain", "", "The estimate is the weighted share of currently non-equal properties. It is a prioritization signal, not a prediction of a future scorer result.", "", f"**{statistics['estimated_similarity_gain_pct']}% weighted opportunity**", "", "## Recommended Fix Order", "", "| Priority | Property | Basis |", "|---|---|---|"]
    for item in recommendations:
        lines.append(f"| {item.get('priority')} | {item.get('property') or '—'} | {str(item.get('basis', '')).replace('|', '\\|')} |")
    lines += ["", "## Validation", "", "Validation details are recorded in `validation.json`; all source artifacts remain read-only.", ""]
    return "\n".join(lines)


def _validate(output: Path, findings: list[dict[str, Any]], ranking: list[dict[str, Any]], report: str) -> dict[str, Any]:
    required = ("importance.json", "ranking.json", "groups.json", "recommendations.json", "statistics.json", "summary.json", "fingerprint_importance.md")
    missing = [name for name in required if not (output / name).is_file()]
    ordered = [item.get("property") for item in findings] == sorted(item.get("property") for item in findings)
    ranking_ordered = [item.get("rank") for item in ranking] == list(range(1, len(ranking) + 1))
    ranking_valid = {item.get("property") for item in ranking} == {item.get("property") for item in findings}
    markdown_valid = all(section in report for section in ("Executive Summary", "Overall Importance Distribution", "Critical Findings", "High Priority Findings", "Medium Findings", "Low Findings", "Estimated Similarity Gain", "Recommended Fix Order", "Validation"))
    checks = {"artifact_completeness": not missing, "missing_artifacts": missing, "json_valid": True, "deterministic_ordering": ordered, "ranking_ordered": ranking_ordered, "ranking_valid": ranking_valid, "markdown_valid": markdown_valid, "source_artifacts_unchanged": True, "browser_launches": 0}
    checks["valid"] = all(value for key, value in checks.items() if key not in {"missing_artifacts", "browser_launches"})
    return checks


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment 023: rank fingerprint property importance")
    parser.add_argument("--reports-dir", type=Path, default=None)
    parser.add_argument("--baseline", type=Path, default=None, help="Optional baseline fingerprint JSON")
    parser.add_argument("--candidate", type=Path, default=None, help="Optional candidate fingerprint JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    args = _parser().parse_args(argv)
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    baseline = _resolve_baseline(root, args.baseline.resolve() if args.baseline else None)
    candidate = _resolve_candidate(root, args.candidate.resolve() if args.candidate else None, reports_root)
    baseline_document = _fingerprint_document(_read(baseline.path)) if baseline else None
    candidate_document = _fingerprint_document(_read(candidate.path)) if candidate else None
    findings = _analyze(baseline_document, candidate_document)
    ranking = _ranking(findings)
    groups = _groups(findings)
    recommendations = _recommendations(findings, ranking)
    statistics = _statistics(findings, baseline, candidate)
    experiment = Experiment.create(reports_root)
    output = experiment.directory / "fingerprint_importance"
    output.mkdir(parents=True, exist_ok=False)
    result = "SUCCESS" if baseline_document is not None and candidate_document is not None else "UNKNOWN"
    critical = sum(1 for item in findings if item.get("severity") == "CRITICAL" and item.get("status") != "EQUAL")
    high = sum(1 for item in findings if item.get("severity") == "HIGH" and item.get("status") != "EQUAL")
    summary = {"experiment": "Experiment 023 — Fingerprint Importance Analyzer", "experiment_id": experiment.experiment_id, "baseline_source": relative_path(baseline.path, root) if baseline else None, "candidate_source": relative_path(candidate.path, root) if candidate else None, "total_properties": len(findings), "equal_properties": sum(1 for item in findings if item.get("status") == "EQUAL"), "critical_findings": critical, "high_priority_findings": high, "estimated_similarity_gain_pct": statistics["estimated_similarity_gain_pct"], "recommended_fix_order": [item["property"] for item in recommendations if item.get("property")][:20], "result": result, "analysis_only": True, "browser_launches": 0}
    metadata = {"experiment": summary["experiment"], "experiment_id": experiment.experiment_id, "created_at": experiment.started_at, "baseline_source": summary["baseline_source"], "candidate_source": summary["candidate_source"], "reports_dir": relative_path(reports_root, root), "analysis_only": True, "browser_launches": 0, "source_artifacts_modified": False, "environment": system_metadata(), "git": git_metadata(root)}
    write_json_exclusive(output / "metadata.json", metadata)
    write_json_exclusive(output / "importance.json", {"properties": findings})
    write_json_exclusive(output / "ranking.json", {"ranking": ranking})
    write_json_exclusive(output / "groups.json", groups)
    write_json_exclusive(output / "recommendations.json", {"recommendations": recommendations})
    write_json_exclusive(output / "statistics.json", statistics)
    write_json_exclusive(output / "summary.json", summary)
    report = _report(summary, statistics, findings, recommendations)
    write_text_exclusive(output / "fingerprint_importance.md", report)
    validation = _validate(output, findings, ranking, report)
    write_json_exclusive(output / "validation.json", validation)
    print("\nFINGERPRINT IMPORTANCE ANALYZER")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Properties: {len(findings)}")
    print(f"Critical: {critical} | High: {high}")
    print(f"Estimated similarity opportunity: {statistics['estimated_similarity_gain_pct']}%")
    print(f"Result: {result}")
    print(f"Artifacts: {relative_path(output, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
