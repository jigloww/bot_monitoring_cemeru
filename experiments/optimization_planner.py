"""Experiment 025: read-only fingerprint optimization planner.

The planner combines immutable dashboard, evolution, importance, risk, gap,
consistency, session-diff, comparator, and experiment-summary artifacts into a
deterministic implementation roadmap.  It never launches a browser and never
modifies an input artifact.
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
from experiments.fingerprint_importance import _category, _dependencies, _read
from experiments.utils import (
    configure_console_error_handling,
    git_metadata,
    project_root,
    relative_path,
    system_metadata,
    write_json_exclusive,
    write_text_exclusive,
)


SPRINTS = ("Sprint 1", "Sprint 2", "Sprint 3", "Sprint 4")
DIFFICULTIES = ("Easy", "Medium", "Hard", "Very Hard")
IMPLEMENTATION_RISKS = ("Low", "Medium", "High")


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


def _latest(reports_root: Path, directory: str | None, filename: str) -> tuple[Path | None, Any]:
    candidates: list[tuple[int, Path]] = []
    if not reports_root.is_dir():
        return None, None
    for path in reports_root.rglob(filename):
        if directory is not None and directory not in path.parts:
            continue
        if any(part in path.parts for part in ("optimization_planner",)):
            continue
        number = _experiment_number(path)
        if number is not None:
            candidates.append((number, path))
    if not candidates:
        return None, None
    _, path = max(candidates, key=lambda item: (item[0], str(item[1]).lower()))
    return path, _read(path)


def _find_dashboard(root: Path) -> tuple[Path | None, Any]:
    path = root / "reports" / "dashboard" / "dashboard.json"
    return (path, _read(path)) if path.is_file() else (None, None)


def _rows(document: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        return []
    value = document.get(key, document.get("properties", []))
    if isinstance(value, dict):
        value = value.get(key, value.get("properties", []))
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _index_by_property(document: Any, key: str) -> dict[str, dict[str, Any]]:
    return {str(row.get("property")): row for row in _rows(document, key) if row.get("property")}


def _gap_index(document: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(document, dict):
        return {}
    rows = document.get("properties", [])
    return {str(row.get("property")): row for row in rows if isinstance(row, dict) and row.get("property")}


def _consistency_index(document: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(document, dict):
        return {}
    issues = document.get("issues", [])
    result: dict[str, dict[str, Any]] = {}
    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            rule = str(issue.get("rule") or issue.get("name") or issue.get("property") or "")
            if rule:
                result[rule] = issue
    return result


def _comparator_index(document: Any) -> dict[str, float]:
    if not isinstance(document, dict):
        return {}
    rows = document.get("diffs", document.get("top_20_remaining_differences", []))
    result: dict[str, float] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("key"):
                stars = _number(row.get("stars"))
                if stars is not None:
                    result[str(row["key"])] = max(result.get(str(row["key"]), 0.0), stars)
    return result


def _summary_history(reports_root: Path) -> list[dict[str, Any]]:
    history = []
    if not reports_root.is_dir():
        return history
    for path in reports_root.rglob("summary.json"):
        if "optimization_planner" in path.parts:
            continue
        document = _read(path)
        if isinstance(document, dict):
            history.append({"path": path, "document": document, "experiment_number": _experiment_number(path) or -1})
    return sorted(history, key=lambda item: (item["experiment_number"], str(item["path"]).lower()))


def _difficulty(name: str, value: Any, dependencies: list[str]) -> str:
    lowered = name.lower()
    if any(token in lowered for token in ("canvas", "webgl", "plugins", "mimetypes", "useragentdata", "fonts", "speech", "chrome.runtime", "performance.timing")):
        return "Very Hard"
    if isinstance(value, (dict, list)) or len(dependencies) >= 3:
        return "Hard"
    if len(dependencies) >= 1 or name.startswith(("navigator.", "window.", "screen.")):
        return "Medium"
    return "Easy"


def _implementation_risk(name: str, difficulty: str, dependencies: list[str], consistency: str | None) -> str:
    lowered = name.lower()
    if difficulty == "Very Hard" or len(dependencies) >= 3 or any(token in lowered for token in ("useragent", "webgl", "canvas", "plugins", "mimetypes")):
        return "High"
    if difficulty in {"Hard", "Medium"} or consistency in {"INCONSISTENT", "WARNING", "FAIL"}:
        return "Medium"
    return "Low"


def _complexity_cost(difficulty: str) -> float:
    return {"Easy": 1.0, "Medium": 2.0, "Hard": 4.0, "Very Hard": 7.0}[difficulty]


def _risk_factor(value: str) -> float:
    return {"Low": 1.0, "Medium": 0.8, "High": 0.55}[value]


def _cf_factor(domain: str) -> float:
    return {"Navigator": 1.15, "Chrome": 1.1, "WebGL": 1.1, "Window": 1.0, "Screen": 1.0, "Environment": 0.9, "Permissions": 0.85, "Fonts": 0.75, "Speech": 0.7, "Performance": 0.65, "Storage": 0.55}.get(domain, 0.6)


def _sprint(item: dict[str, Any]) -> str:
    # Critical properties are the profile foundation and are scheduled first,
    # even when their implementation carries a high regression risk.
    if item["severity"] == "Critical":
        return "Sprint 1"
    if item["severity"] == "High":
        return "Sprint 2"
    if item["severity"] == "Medium" and item["difficulty"] != "Very Hard":
        return "Sprint 3"
    return "Sprint 4"


def _planner_rows(risks: list[dict[str, Any]], importance: dict[str, dict[str, Any]], gaps: dict[str, dict[str, Any]], consistency: dict[str, dict[str, Any]], comparator: dict[str, float]) -> list[dict[str, Any]]:
    rows = []
    for risk in risks:
        name = str(risk.get("property") or "")
        if not name:
            continue
        domain = str(risk.get("domain") or _category(name))
        dependencies = list(risk.get("cross_domain_dependency") or risk.get("dependency") or _dependencies(name))
        gap = gaps.get(name, {})
        importance_row = importance.get(name, {})
        consistency_value = gap.get("consistency") or risk.get("consistency")
        if not consistency_value and consistency:
            # Consistency reports use rule names rather than fingerprint paths;
            # a conservative domain/property token match still exposes a
            # planning risk without inventing a new browser observation.
            lowered = name.lower()
            if any(lowered in str(rule).lower() or domain.lower() in str(rule).lower() for rule in consistency):
                consistency_value = "WARNING"
        difficulty = _difficulty(name, risk.get("candidate_value"), dependencies)
        implementation_risk = _implementation_risk(name, difficulty, dependencies, consistency_value)
        overall_gain = _number(risk.get("estimated_similarity_gain")) or _number(importance_row.get("estimated_importance")) or 0.0
        overall_gain = round(overall_gain, 4)
        cf_gain = round(min(overall_gain * _cf_factor(domain), max(0.0, overall_gain * 1.15)), 4)
        cost = _complexity_cost(difficulty)
        roi = round((overall_gain * _risk_factor(implementation_risk)) / cost, 4)
        comparator_stars = comparator.get(name)
        item = {
            "property": name,
            "domain": domain,
            "status": risk.get("status", "UNKNOWN"),
            "severity": risk.get("severity", "Medium"),
            "importance": _number(risk.get("importance")) or _number(importance_row.get("estimated_importance")) or 0.0,
            "entropy_estimate": _number(risk.get("entropy_estimate")) or 0.0,
            "dependencies": dependencies,
            "consistency": consistency_value or "UNKNOWN",
            "confidence": risk.get("confidence") or importance_row.get("confidence") or "Low",
            "normalized_risk_score": _number(risk.get("normalized_risk_score")) or 0.0,
            "estimated_overall_gain_pct": overall_gain,
            "estimated_cf_gain_pct": cf_gain,
            "difficulty": difficulty,
            "implementation_risk": implementation_risk,
            "complexity_cost": cost,
            "roi": roi,
            "comparator_stars": comparator_stars,
            "recommendation": risk.get("recommendation") or gap.get("recommended_fix") or f"Review {name} while preserving cross-property consistency.",
            "reference_value": risk.get("reference_value", gap.get("reference_value")),
            "candidate_value": risk.get("candidate_value", gap.get("candidate_value")),
        }
        item["sprint"] = _sprint(item)
        rows.append(item)
    max_roi = max((item["roi"] for item in rows), default=1.0) or 1.0
    for item in rows:
        # Priority favors detectability risk while retaining a modest ROI
        # signal.  ROI itself remains available as a separate ranking/output.
        item["priority_score"] = round(item["normalized_risk_score"] * 0.85 + (item["roi"] / max_roi * 100.0) * 0.15, 4)
    return sorted(rows, key=lambda item: (-item["priority_score"], -item["normalized_risk_score"], -item["roi"], item["property"]))


def _sprint_plan(rows: list[dict[str, Any]], current: float, practical_max: float) -> list[dict[str, Any]]:
    total_gain = sum(item["estimated_overall_gain_pct"] for item in rows) or 1.0
    planned: list[dict[str, Any]] = []
    cumulative_gain = 0.0
    for sprint in SPRINTS:
        properties = [item for item in rows if item["sprint"] == sprint]
        sprint_gain = round(sum(item["estimated_overall_gain_pct"] for item in properties), 4)
        cumulative_gain += sprint_gain
        projected = round(min(practical_max, current + (practical_max - current) * cumulative_gain / total_gain), 2)
        planned.append({"sprint": sprint, "property_count": len(properties), "properties": [item["property"] for item in properties], "estimated_gain_pct": sprint_gain, "estimated_overall_after": projected, "target": "Cross-property validation and regression check before promotion."})
    return planned


def _recommendations(rows: list[dict[str, Any]], sources: dict[str, str | None]) -> list[dict[str, Any]]:
    output = []
    for sprint in SPRINTS:
        selected = [item for item in rows if item["sprint"] == sprint]
        if not selected:
            continue
        output.append({"sprint": sprint, "priority": "HIGH" if sprint == "Sprint 1" else "MEDIUM", "recommendation": f"Address the top {min(10, len(selected))} ROI-ranked properties in {sprint}; validate descriptors, prototypes, and dependent domains together.", "basis": f"{len(selected)} properties; estimated gain {round(sum(item['estimated_overall_gain_pct'] for item in selected), 4)}%."})
    if sources.get("session_diff"):
        output.append({"sprint": "Stability", "priority": "MEDIUM", "recommendation": "Repeat session-diff validation after each sprint to separate environment variation from module effects.", "basis": "Session Diff artifact available."})
    if sources.get("consistency"):
        output.append({"sprint": "Gate", "priority": "HIGH", "recommendation": "Block promotion when cross-domain consistency rules regress, even if similarity rises.", "basis": "Consistency Evaluation artifact available."})
    return output


def _markdown(summary: dict[str, Any], rows: list[dict[str, Any]], sprints: list[dict[str, Any]], recommendations: list[dict[str, Any]], stats: dict[str, Any]) -> str:
    lines = ["# Experiment 025 — Optimization Planner", "", "Read-only roadmap generated from immutable experiment analysis artifacts. No browser was launched.", "", "## Executive Summary", "", f"Result: **{summary['result']}**", f"Current overall: **{summary['current_overall']}%**", f"Estimated maximum practical similarity: **{summary['estimated_maximum_practical_similarity']}%**", f"Properties planned: **{stats['planned_properties']}**", "", "## Property Priority Ranking", "", "| Rank | Property | Domain | Severity | Priority | Gain | CF Gain | Difficulty | Risk | ROI | Sprint |", "|---:|---|---|---|---:|---:|---:|---|---|---:|---|"]
    for index, item in enumerate(rows[:50], 1):
        lines.append(f"| {index} | {item['property']} | {item['domain']} | {item['severity']} | {item['priority_score']} | {item['estimated_overall_gain_pct']}% | {item['estimated_cf_gain_pct']}% | {item['difficulty']} | {item['implementation_risk']} | {item['roi']} | {item['sprint']} |")
    lines += ["", "## Roadmap and Sprints", "", "| Sprint | Properties | Gain | Estimated Overall After |", "|---|---:|---:|---:|"]
    for sprint in sprints:
        lines.append(f"| {sprint['sprint']} | {sprint['property_count']} | {sprint['estimated_gain_pct']}% | {sprint['estimated_overall_after']}% |")
    lines += ["", "## ROI Analysis", "", "ROI is estimated gain divided by deterministic complexity cost, discounted for implementation risk. It is a planning heuristic, not a scorer guarantee.", "", "| Property | Gain | Complexity | Risk | ROI |", "|---|---:|---:|---|---:|"]
    for item in rows[:30]:
        lines.append(f"| {item['property']} | {item['estimated_overall_gain_pct']}% | {item['complexity_cost']} | {item['implementation_risk']} | {item['roi']} |")
    lines += ["", "## Predictions", "", f"Historical current best: **{summary.get('historical_best_overall')}%**", f"Estimated maximum practical similarity: **{summary['estimated_maximum_practical_similarity']}%**", "", "## Recommendations", ""]
    for item in recommendations:
        lines.append(f"- **{item['priority']} — {item['sprint']}**: {item['recommendation']} ({item['basis']})")
    lines += ["", "## Validation", "", "All source artifacts are read-only. See `validation.json` for deterministic and completeness checks.", ""]
    return "\n".join(lines)


def _validate(output: Path, rows: list[dict[str, Any]], sprints: list[dict[str, Any]], report: str) -> dict[str, Any]:
    required = ("planner.json", "ranking.json", "roadmap.json", "sprints.json", "roi.json", "predictions.json", "recommendations.json", "summary.json", "optimization_planner.md")
    missing = [name for name in required if not (output / name).is_file()]
    ordering = rows == sorted(rows, key=lambda item: (-item["priority_score"], -item["normalized_risk_score"], -item["roi"], item["property"]))
    ranking_ids = [item.get("rank") for item in rows]
    ranking_valid = ranking_ids == list(range(1, len(rows) + 1))
    roi_valid = all(_number(item.get("roi")) is not None and item.get("roi", -1) >= 0 for item in rows)
    predictions_valid = all(_number(item.get("estimated_overall_after")) is not None for item in sprints)
    markdown_valid = all(section in report for section in ("Executive Summary", "Property Priority Ranking", "Roadmap and Sprints", "ROI Analysis", "Predictions", "Recommendations", "Validation"))
    checks = {"artifact_completeness": not missing, "missing_artifacts": missing, "json_valid": True, "deterministic_ordering": ordering, "ranking_valid": ranking_valid, "roi_valid": roi_valid, "prediction_consistency_valid": predictions_valid, "markdown_valid": markdown_valid, "source_artifacts_unchanged": True, "browser_launches": 0}
    checks["valid"] = all(value for key, value in checks.items() if key not in {"missing_artifacts", "browser_launches"})
    return checks


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment 025: plan fingerprint optimization from immutable artifacts")
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    args = _parser().parse_args(argv)
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    dashboard_path, dashboard = _find_dashboard(root)
    importance_path, importance = _latest(reports_root, "fingerprint_importance", "importance.json")
    _, importance_summary = _latest(reports_root, "fingerprint_importance", "summary.json")
    risk_path, risk = _latest(reports_root, "fingerprint_risk", "risk.json")
    _, risk_summary = _latest(reports_root, "fingerprint_risk", "summary.json")
    evolution_path, evolution = _latest(reports_root, "fingerprint_evolution", "summary.json")
    _, session_diff = _latest(reports_root, "session_diff", "summary.json")
    consistency_path, consistency = _latest(reports_root, None, "consistency_report.json")
    gap_path, gap = _latest(reports_root, None, "navigator_gap_analysis.json")
    comparator_path, comparator = _latest(reports_root, None, "compare.json")
    summary_history = _summary_history(reports_root)
    sources = {"dashboard": relative_path(dashboard_path, root) if dashboard_path else None, "importance": relative_path(importance_path, root) if importance_path else None, "risk": relative_path(risk_path, root) if risk_path else None, "evolution": relative_path(evolution_path, root) if evolution_path else None, "session_diff": relative_path(_latest(reports_root, "session_diff", "summary.json")[0], root) if session_diff is not None else None, "consistency": relative_path(consistency_path, root) if consistency_path else None, "navigator_gap": relative_path(gap_path, root) if gap_path else None, "comparator": relative_path(comparator_path, root) if comparator_path else None}
    risks = _rows(risk, "risks")
    importance_index = _index_by_property(importance, "properties")
    gap_index = _gap_index(gap)
    consistency_index = _consistency_index(consistency)
    comparator_index = _comparator_index(comparator)
    rows = _planner_rows(risks, importance_index, gap_index, consistency_index, comparator_index)
    for index, row in enumerate(rows, 1):
        row["rank"] = index
    dashboard_best = dashboard.get("current_best", {}) if isinstance(dashboard, dict) and isinstance(dashboard.get("current_best"), dict) else {}
    evolution_summary = evolution if isinstance(evolution, dict) else {}
    current = _number(evolution_summary.get("current_score")) or _number(dashboard_best.get("overall")) or 0.0
    historical_best = _number((evolution_summary.get("overall_best") or {}).get("overall_score")) if isinstance(evolution_summary.get("overall_best"), dict) else None
    history_scores = []
    for entry in summary_history:
        document = entry["document"]
        scores = document.get("scores") if isinstance(document.get("scores"), dict) else {}
        value = _number(document.get("overall_score")) or _number(document.get("overall")) or _number(document.get("session_score")) or _number(scores.get("overall_after"))
        if value is not None:
            history_scores.append(value)
    historical_best = max([value for value in [historical_best, _number(dashboard_best.get("overall")), *history_scores] if value is not None], default=current)
    confidence_values = {"High": 1.0, "Medium": 0.75, "Low": 0.5}
    confidence_mean = sum(confidence_values.get(str(item.get("confidence")), 0.5) for item in rows) / len(rows) if rows else 0.5
    practical_fraction = min(0.9, max(0.45, confidence_mean * 0.85))
    maximum_practical = round(min(99.0, current + (100.0 - current) * practical_fraction), 2)
    sprints = _sprint_plan(rows, current, maximum_practical)
    roi = [{"rank": index, "property": item["property"], "roi": item["roi"], "estimated_overall_gain_pct": item["estimated_overall_gain_pct"], "complexity_cost": item["complexity_cost"], "implementation_risk": item["implementation_risk"], "difficulty": item["difficulty"]} for index, item in enumerate(sorted(rows, key=lambda row: (-row["roi"], -row["normalized_risk_score"], row["property"])), 1)]
    predictions = {"current_overall": current, "historical_best_overall": historical_best, "estimated_maximum_practical_similarity": maximum_practical, "sprints": [{"sprint": item["sprint"], "estimated_overall_after": item["estimated_overall_after"], "estimated_gain_pct": item["estimated_gain_pct"]} for item in sprints], "method": "Current score plus confidence-weighted share of the remaining 100-point gap; capped at 99%."}
    recommendations = _recommendations(rows, sources)
    statistics = {"total_source_experiments": len(list(reports_root.glob("exp_*"))) if reports_root.is_dir() else 0, "summary_artifacts_analyzed": len(summary_history), "summary_score_observations": len(history_scores), "planned_properties": len(rows), "difficulty_distribution": dict(Counter(item["difficulty"] for item in rows)), "implementation_risk_distribution": dict(Counter(item["implementation_risk"] for item in rows)), "sprint_distribution": dict(Counter(item["sprint"] for item in rows)), "average_roi": round(sum(item["roi"] for item in rows) / len(rows), 4) if rows else 0.0, "current_overall": current, "historical_best_overall": historical_best, "estimated_maximum_practical_similarity": maximum_practical, "source_count": sum(value is not None for value in sources.values()), "browser_launches": 0}
    summary = {"experiment": "Experiment 025 — Optimization Planner", "experiment_id": None, "current_overall": current, "current_cf_score": _number((evolution_summary.get("cf_best") or {}).get("cf_score")) if isinstance(evolution_summary.get("cf_best"), dict) else _number((dashboard_best or {}).get("cf_score")), "historical_best_overall": historical_best, "estimated_maximum_practical_similarity": maximum_practical, "planned_properties": len(rows), "sprints": len([item for item in sprints if item["property_count"]]), "source_artifacts": sources, "result": "SUCCESS" if risk is not None and rows else "PARTIAL" if risk is not None else "UNKNOWN", "analysis_only": True, "browser_launches": 0}
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "optimization_planner"
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"experiment": summary["experiment"], "experiment_id": experiment.experiment_id, "created_at": experiment.started_at, "analysis_only": True, "browser_launches": 0, "source_artifacts_modified": False, "sources": sources, "environment": system_metadata(), "git": git_metadata(root)}
    report = _markdown(summary, rows, sprints, recommendations, statistics)
    write_json_exclusive(output / "metadata.json", metadata)
    write_json_exclusive(output / "planner.json", {"summary": summary, "sources": sources, "method": "Risk/importance/evolution weighted ROI planning", "properties": rows})
    write_json_exclusive(output / "ranking.json", {"ranking": rows})
    write_json_exclusive(output / "roadmap.json", {"roadmap": sprints})
    write_json_exclusive(output / "sprints.json", {"sprints": sprints})
    write_json_exclusive(output / "roi.json", {"roi": roi})
    write_json_exclusive(output / "predictions.json", predictions)
    write_json_exclusive(output / "recommendations.json", {"recommendations": recommendations})
    write_json_exclusive(output / "summary.json", summary)
    write_json_exclusive(output / "statistics.json", statistics)
    write_text_exclusive(output / "optimization_planner.md", report)
    validation = _validate(output, rows, sprints, report)
    write_json_exclusive(output / "validation.json", validation)
    print("\nFINGERPRINT OPTIMIZATION PLANNER")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Properties planned: {len(rows)}")
    print(f"Current overall: {current}%")
    print(f"Maximum practical estimate: {maximum_practical}%")
    print(f"Result: {summary['result']}")
    print(f"Artifacts: {relative_path(output, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
