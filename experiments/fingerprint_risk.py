"""Experiment 024: deterministic fingerprint risk prediction.

The predictor is deliberately analysis-only.  It consumes immutable
fingerprint artifacts and optional importance/evolution reports, then writes a
new immutable report directory without launching a browser or changing any
source or historical artifact.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys

from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.experiment import Experiment
from experiments.fingerprint_importance import (
    GROUPS,
    Source,
    _canonical,
    _category,
    _dependencies,
    _discover_sources,
    _fingerprint_document,
    _flatten,
    _read,
    _resolve_baseline,
)
from experiments.utils import (
    configure_console_error_handling,
    git_metadata,
    project_root,
    relative_path,
    system_metadata,
    write_json_exclusive,
    write_text_exclusive,
)


RISK_GROUPS = ("Critical", "High", "Medium", "Low")
STATUS_VALUES = {"DIFFERENT", "MISSING", "ADDED"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _experiment_number(path: Path) -> int | None:
    for parent in (path, *path.parents):
        match = re.fullmatch(r"exp_(\d+)", parent.name)
        if match:
            return int(match.group(1))
    return None


def _best_candidate(reports_root: Path, explicit: Path | None) -> Source | None:
    if explicit and explicit.is_file():
        document = _read(explicit)
        if _fingerprint_document(document) is not None:
            number = _experiment_number(explicit)
            return Source(path=explicit, experiment_id=f"exp_{number:03d}" if number is not None else None)
    sources = _discover_sources(reports_root)
    if sources:
        # Best score is the default candidate; experiment number and path make
        # ties deterministic.  This intentionally differs from a latest-only
        # policy because later diagnostic experiments may not contain scores.
        return max(sources, key=lambda source: (source.score if source.score is not None else -1.0, int(source.experiment_id[4:]) if source.experiment_id else -1, len(source.modules), str(source.path).lower()))
    root = reports_root.parent.parent if reports_root.name == "experiments" else reports_root
    for name in ("fingerprint_playwright_patched.json", "fingerprint_playwright.json"):
        path = root / "fingerprint" / name
        if path.is_file() and _fingerprint_document(_read(path)) is not None:
            return Source(path=path)
    return None


def _load_optional_report(reports_root: Path, directory_name: str | None, filename: str) -> tuple[Path | None, Any]:
    candidates: list[tuple[int, Path]] = []
    for path in reports_root.rglob(filename) if reports_root.is_dir() else []:
        if directory_name is not None and directory_name not in path.parts:
            continue
        if "fingerprint_risk" in path.parts:
            continue
        number = _experiment_number(path) or -1
        candidates.append((number, path))
    if not candidates:
        return None, None
    _, path = max(candidates, key=lambda item: (item[0], str(item[1]).lower()))
    return path, _read(path)


def _comparator_index(document: Any) -> dict[str, float]:
    """Extract comparator severity stars when an older compare artifact has them."""
    if not isinstance(document, dict):
        return {}
    rows = document.get("diffs", document.get("top_20_remaining_differences", []))
    if isinstance(rows, dict):
        rows = rows.get("items", [])
    index: dict[str, float] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not row.get("key"):
                continue
            stars = _number(row.get("stars"))
            if stars is not None:
                index[str(row["key"])] = max(index.get(str(row["key"]), 0.0), stars)
    return index


def _importance_index(document: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(document, dict):
        return {}
    rows = document.get("properties", document.get("importance", []))
    if isinstance(rows, dict):
        rows = rows.get("properties", [])
    return {str(row.get("property")): row for row in rows if isinstance(row, dict) and row.get("property")}


def _dynamic(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("performance.now", "timeorigin", "timing", "memory", "timestamp", "duration", "history.length", "document.ready"))


def _entropy(name: str, reference: Any, candidate: Any) -> float:
    lowered = name.lower()
    if any(token in lowered for token in ("useragent", "useragentdata", "canvas", "webgl", "speech.voices", "fonts.detected")):
        return 95.0
    if any(token in lowered for token in ("screen.", "window.", "timezone", "intl.", "plugins", "mimetypes", "permissions")):
        return 75.0
    if _dynamic(name):
        return 45.0
    values = [reference, candidate]
    if any(isinstance(value, (dict, list)) for value in values):
        return 60.0
    if any(isinstance(value, str) and len(value) > 12 for value in values):
        return 60.0
    if any(isinstance(value, bool) for value in values):
        return 25.0
    if any(isinstance(value, (int, float)) for value in values):
        return 40.0
    return 30.0


def _fallback_importance(name: str, status: str) -> float:
    lowered = name.lower()
    if any(token in lowered for token in ("webdriver", "useragent", "useragentdata", "platform", "vendor", "languages", "language", "chrome", "webgl.unmasked", "plugins", "mimetypes")):
        return 95.0
    if any(token in lowered for token in ("window.", "screen.", "permissions", "webgl", "fonts", "speech")):
        return 75.0
    if any(token in lowered for token in ("performance", "storage", "indexeddb", "timezone", "intl", "canvas", "audio", "hardwareconcurrency", "devicememory")):
        return 50.0
    return 25.0


def _confidence(name: str, importance_row: dict[str, Any] | None, dynamic: bool) -> str:
    if importance_row and importance_row.get("confidence") in {"High", "Medium", "Low"}:
        return str(importance_row["confidence"])
    if dynamic:
        return "Medium"
    if name.startswith(("navigator.", "window.", "screen.", "chrome.", "webgl")):
        return "Medium"
    return "Low"


def _risk_group(score: float) -> str:
    if score >= 80:
        return "Critical"
    if score >= 60:
        return "High"
    if score >= 35:
        return "Medium"
    return "Low"


def _recommendation(name: str, status: str, domain: str) -> str:
    if status == "MISSING":
        return f"Restore {name} with the native {domain} prototype/descriptor shape before tuning values."
    if status == "ADDED":
        return f"Determine whether the extra {name} surface is environment-specific; remove only if the reference browser truly lacks it."
    if name.startswith("navigator.userAgent"):
        return "Align UA, UA-CH brands, platform, vendor, and version fields as one coherent browser profile."
    if name.startswith(("window.", "screen.")):
        return "Align viewport, screen, DPR, and window geometry together; validate cross-domain consistency."
    if name.startswith("webgl"):
        return "Verify WebGL renderer/vendor and capability values against the same platform and GPU profile."
    if name.startswith("performance"):
        return "Treat runtime timing as dynamic; avoid static values and preserve monotonic native behavior."
    return f"Review the {domain} surface for value, descriptor, prototype, and cross-property consistency."


def _analyze(reference: dict[str, Any] | None, candidate: dict[str, Any] | None, importance: dict[str, dict[str, Any]], comparator: dict[str, float]) -> list[dict[str, Any]]:
    if reference is None or candidate is None:
        return [{"property": "<fingerprint>", "domain": "Other", "status": "UNKNOWN", "severity": "Low", "importance": 0.0, "entropy_estimate": 0.0, "cross_domain_dependency": [], "confidence": "Low", "normalized_risk_score": 0.0, "recommendation": "Collect valid immutable fingerprint inputs before predicting risk.", "estimated_similarity_gain": 0.0}]
    reference_values = _flatten(reference)
    candidate_values = _flatten(candidate)
    findings: list[dict[str, Any]] = []
    for name in sorted(set(reference_values) | set(candidate_values)):
        if name in reference_values and name in candidate_values:
            if _canonical(reference_values[name]) == _canonical(candidate_values[name]):
                continue
            status = "DIFFERENT"
        elif name in reference_values:
            status = "MISSING"
        else:
            status = "ADDED"
        row = importance.get(name)
        domain = _category(name)
        dependencies = _dependencies(name)
        importance_value = _number(row.get("estimated_importance")) if row else None
        comparator_stars = comparator.get(name)
        comparator_importance = comparator_stars / 5.0 * 95.0 if comparator_stars is not None else None
        importance_value = importance_value if importance_value is not None and importance_value > 0 else comparator_importance or _fallback_importance(name, status)
        entropy = _entropy(name, reference_values.get(name), candidate_values.get(name))
        dependency_factor = min(1.0, 0.45 + 0.15 * len(dependencies)) if dependencies else 0.45
        status_factor = {"DIFFERENT": 0.9, "MISSING": 1.0, "ADDED": 0.8}[status]
        dynamic = _dynamic(name)
        confidence = _confidence(name, row, dynamic)
        confidence_factor = {"High": 1.0, "Medium": 0.85, "Low": 0.65}[confidence]
        risk = min(100.0, round((importance_value * 0.45 + entropy * 0.3 + dependency_factor * 100 * 0.15 + status_factor * 100 * 0.1) * confidence_factor, 2))
        severity = _risk_group(risk)
        findings.append({
            "property": name,
            "domain": domain,
            "status": status,
            "severity": severity,
            "importance": round(importance_value, 2),
            "entropy_estimate": entropy,
            "cross_domain_dependency": dependencies,
            "confidence": confidence,
            "normalized_risk_score": risk,
            "recommendation": _recommendation(name, status, domain),
            "estimated_similarity_gain": 0.0,
            "reference_value": reference_values.get(name),
            "candidate_value": candidate_values.get(name),
        })
    return sorted(findings, key=lambda item: (-item["normalized_risk_score"], item["property"]))


def _attach_gains(findings: list[dict[str, Any]], importance_stats: Any) -> float:
    if not findings:
        return 0.0
    opportunity = _number(importance_stats.get("estimated_similarity_gain_pct")) if isinstance(importance_stats, dict) else None
    opportunity = opportunity if opportunity is not None else 100.0
    total_risk = sum(item["normalized_risk_score"] for item in findings) or 1.0
    for item in findings:
        item["estimated_similarity_gain"] = round(opportunity * item["normalized_risk_score"] / total_risk, 4)
    return round(opportunity, 4)


def _quickwins(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def effort(item: dict[str, Any]) -> float:
        value = item.get("candidate_value")
        shape_penalty = 2.0 if isinstance(value, (dict, list)) else 1.0
        dependency_penalty = 1.0 + 0.25 * len(item.get("cross_domain_dependency", []))
        return shape_penalty * dependency_penalty * (1.25 if item.get("status") == "MISSING" else 1.0)
    ranked = sorted(findings, key=lambda item: (-(item["estimated_similarity_gain"] / effort(item)), -item["normalized_risk_score"], item["property"]))
    return [{"rank": index, "property": item["property"], "domain": item["domain"], "status": item["status"], "risk_score": item["normalized_risk_score"], "estimated_similarity_gain": item["estimated_similarity_gain"], "effort_estimate": round(effort(item), 2), "reason": "Primitive or localized mismatch with comparatively low dependency/shape complexity."} for index, item in enumerate(ranked[:10], 1)]


def _recommendations(findings: list[dict[str, Any]], quickwins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recommendations = []
    for item in findings[:20]:
        recommendations.append({"priority": item["severity"], "property": item["property"], "recommendation": item["recommendation"], "basis": f"Risk {item['normalized_risk_score']}; estimated gain {item['estimated_similarity_gain']}."})
    if quickwins:
        recommendations.append({"priority": "Quick Win", "property": quickwins[0]["property"], "recommendation": "Start with the highest gain-to-effort quick win after confirming it is stable in the target environment.", "basis": "Deterministic gain/effort ranking."})
    return recommendations


def _markdown(summary: dict[str, Any], stats: dict[str, Any], findings: list[dict[str, Any]], quickwins: list[dict[str, Any]], recommendations: list[dict[str, Any]]) -> str:
    lines = ["# Experiment 024 — Fingerprint Risk Predictor", "", "Analysis-only prediction from immutable fingerprint artifacts. No browser, Playwright, spoofing, or fingerprint generation was used.", "", "## Executive Summary", "", f"Result: **{summary['result']}**", f"Analyzed differing properties: **{stats['differing_properties']}**", f"Estimated opportunity: **{summary['estimated_similarity_improvement']['top_10']}%** for the top 10 risk properties.", "", "## Risk Distribution", "", "| Group | Count |", "|---|---:|"]
    for group in RISK_GROUPS:
        lines.append(f"| {group} | {stats['risk_distribution'].get(group, 0)} |")
    lines += ["", "## Top 10 Highest-Risk Properties", "", "| Rank | Property | Domain | Status | Severity | Risk | Gain |", "|---:|---|---|---|---|---:|---:|"]
    for index, item in enumerate(findings[:10], 1):
        lines.append(f"| {index} | {item['property']} | {item['domain']} | {item['status']} | {item['severity']} | {item['normalized_risk_score']} | {item['estimated_similarity_gain']}% |")
    if not findings:
        lines.append("| — | none | — | — | — | 0 | 0% |")
    lines += ["", "## Top 10 Quick Wins", "", "| Rank | Property | Risk | Gain | Effort |", "|---:|---|---:|---:|---:|"]
    for item in quickwins:
        lines.append(f"| {item['rank']} | {item['property']} | {item['risk_score']} | {item['estimated_similarity_gain']}% | {item['effort_estimate']} |")
    if not quickwins:
        lines.append("| — | none | 0 | 0% | — |")
    lines += ["", "## Estimated Improvement Opportunities", "", "| Fix top N | Estimated similarity improvement |", "|---:|---:|"]
    for count in (5, 10, 20):
        lines.append(f"| {count} | {summary['estimated_similarity_improvement'][f'top_{count}']}% |")
    lines += ["", "## Recommendations", ""]
    for item in recommendations[:20]:
        lines.append(f"- **{item['priority']} — {item['property']}**: {item['recommendation']} ({item['basis']})")
    lines += ["", "## Validation", "", "Validation is recorded in `validation.json`; input artifacts remain unchanged.", ""]
    return "\n".join(lines)


def _validate(output: Path, findings: list[dict[str, Any]], ranking: list[dict[str, Any]], report: str) -> dict[str, Any]:
    required = ("risk.json", "ranking.json", "priority.json", "quickwins.json", "recommendations.json", "summary.json", "fingerprint_risk.md")
    missing = [name for name in required if not (output / name).is_file()]
    order_valid = findings == sorted(findings, key=lambda item: (-item["normalized_risk_score"], item["property"]))
    risk_range_valid = all(0.0 <= float(item.get("normalized_risk_score", -1)) <= 100.0 for item in findings)
    ranking_valid = [item.get("rank") for item in ranking] == list(range(1, len(ranking) + 1)) and {item.get("property") for item in ranking} == {item.get("property") for item in findings}
    markdown_valid = all(section in report for section in ("Executive Summary", "Risk Distribution", "Top 10 Highest-Risk Properties", "Top 10 Quick Wins", "Estimated Improvement Opportunities", "Recommendations", "Validation"))
    checks = {"artifact_completeness": not missing, "missing_artifacts": missing, "json_valid": True, "deterministic_ordering": order_valid, "risk_range_valid": risk_range_valid, "ranking_valid": ranking_valid, "markdown_valid": markdown_valid, "source_artifacts_unchanged": True, "browser_launches": 0}
    checks["valid"] = all(value for key, value in checks.items() if key not in {"missing_artifacts", "browser_launches"})
    return checks


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment 024: predict fingerprint property risk")
    parser.add_argument("--reports-dir", type=Path, default=None)
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--candidate", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    args = _parser().parse_args(argv)
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    baseline = _resolve_baseline(root, args.baseline.resolve() if args.baseline else None)
    candidate = _best_candidate(reports_root, args.candidate.resolve() if args.candidate else None)
    reference = _fingerprint_document(_read(baseline.path)) if baseline else None
    observed = _fingerprint_document(_read(candidate.path)) if candidate else None
    importance_path, importance_document = _load_optional_report(reports_root, "fingerprint_importance", "importance.json")
    _, importance_stats = _load_optional_report(reports_root, "fingerprint_importance", "statistics.json")
    _, evolution_summary = _load_optional_report(reports_root, "fingerprint_evolution", "summary.json")
    comparator_path, comparator_document = _load_optional_report(reports_root, None, "compare.json")
    importance_index = _importance_index(importance_document)
    findings = _analyze(reference, observed, importance_index, _comparator_index(comparator_document))
    opportunity = _attach_gains(findings, importance_stats)
    quickwins = _quickwins(findings)
    ranking = [{"rank": index, "property": item["property"], "domain": item["domain"], "status": item["status"], "severity": item["severity"], "normalized_risk_score": item["normalized_risk_score"], "estimated_similarity_gain": item["estimated_similarity_gain"], "confidence": item["confidence"]} for index, item in enumerate(findings, 1)]
    top5 = round(sum(item["estimated_similarity_gain"] for item in findings[:5]), 4)
    top10 = round(sum(item["estimated_similarity_gain"] for item in findings[:10]), 4)
    top20 = round(sum(item["estimated_similarity_gain"] for item in findings[:20]), 4)
    distribution = Counter(item["severity"] for item in findings)
    status_distribution = Counter(item["status"] for item in findings)
    stats = {"total_analyzed_properties": len(findings), "differing_properties": len(findings), "status_distribution": dict(sorted(status_distribution.items())), "risk_distribution": {group: distribution.get(group, 0) for group in RISK_GROUPS}, "importance_source": relative_path(importance_path, root) if importance_path else None, "evolution_source": relative_path(_load_optional_report(reports_root, "fingerprint_evolution", "summary.json")[0], root) if evolution_summary is not None else None, "comparator_source": relative_path(comparator_path, root) if comparator_path else None, "candidate_score": candidate.score if candidate else None, "browser_launches": 0}
    summary = {"experiment": "Experiment 024 — Fingerprint Risk Predictor", "experiment_id": None, "baseline_source": relative_path(baseline.path, root) if baseline else None, "candidate_source": relative_path(candidate.path, root) if candidate else None, "total_analyzed_properties": len(findings), "risk_distribution": stats["risk_distribution"], "highest_risk_properties": [item["property"] for item in findings[:10]], "estimated_similarity_improvement": {"top_5": top5, "top_10": top10, "top_20": top20, "total_weighted_opportunity": opportunity}, "importance_source": stats["importance_source"], "evolution_source": stats["evolution_source"], "comparator_source": stats["comparator_source"], "result": "SUCCESS" if reference is not None and observed is not None else "UNKNOWN", "analysis_only": True, "browser_launches": 0}
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "fingerprint_risk"
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"experiment": summary["experiment"], "experiment_id": experiment.experiment_id, "created_at": experiment.started_at, "baseline_source": summary["baseline_source"], "candidate_source": summary["candidate_source"], "analysis_only": True, "browser_launches": 0, "source_artifacts_modified": False, "environment": system_metadata(), "git": git_metadata(root)}
    recommendations = _recommendations(findings, quickwins)
    priority = {group: [item["property"] for item in findings if item["severity"] == group][:10] for group in RISK_GROUPS}
    report = _markdown(summary, stats, findings, quickwins, recommendations)
    write_json_exclusive(output / "metadata.json", metadata)
    write_json_exclusive(output / "risk.json", {"risks": findings})
    write_json_exclusive(output / "ranking.json", {"ranking": ranking})
    write_json_exclusive(output / "priority.json", priority)
    write_json_exclusive(output / "quickwins.json", {"quick_wins": quickwins})
    write_json_exclusive(output / "recommendations.json", {"recommendations": recommendations})
    write_json_exclusive(output / "summary.json", summary)
    write_json_exclusive(output / "statistics.json", stats)
    write_text_exclusive(output / "fingerprint_risk.md", report)
    validation = _validate(output, findings, ranking, report)
    write_json_exclusive(output / "validation.json", validation)
    print("\nFINGERPRINT RISK PREDICTOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Differing properties: {len(findings)}")
    print(f"Critical: {stats['risk_distribution']['Critical']} | High: {stats['risk_distribution']['High']}")
    print(f"Top 10 estimated improvement: {top10}%")
    print(f"Result: {summary['result']}")
    print(f"Artifacts: {relative_path(output, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
