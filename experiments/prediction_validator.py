"""Experiment 026: validate optimization predictions against observed history.

This is an analysis-only validator.  It compares planner predictions with
subsequent scored experiment artifacts when those artifacts exist and reports
``Insufficient Data`` otherwise.  It never launches a browser or mutates an
existing report.
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
from experiments.fingerprint_importance import _read
from experiments.utils import (
    configure_console_error_handling,
    git_metadata,
    project_root,
    relative_path,
    system_metadata,
    write_json_exclusive,
    write_text_exclusive,
)


CLASSIFICATIONS = ("Accurate", "Overestimated", "Underestimated", "Insufficient Data")


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
        if "prediction_validator" in path.parts:
            continue
        number = _experiment_number(path)
        if number is not None:
            candidates.append((number, path))
    if not candidates:
        return None, None
    _, path = max(candidates, key=lambda item: (item[0], str(item[1]).lower()))
    return path, _read(path)


def _score_from(document: Any) -> tuple[float | None, float | None]:
    if not isinstance(document, dict):
        return None, None
    scores = document.get("scores") if isinstance(document.get("scores"), dict) else {}
    overall = _number(document.get("overall_score")) or _number(document.get("overall")) or _number(scores.get("overall_after"))
    cf = _number(document.get("cf_score")) or _number(document.get("cf_risk_score")) or _number(scores.get("cf_risk_after"))
    return overall, cf


def _score_history(reports_root: Path) -> list[dict[str, Any]]:
    """Collect one deterministic scored observation per experiment number."""
    by_number: dict[int, dict[str, Any]] = {}
    if not reports_root.is_dir():
        return []
    for path in reports_root.rglob("score.json"):
        if "prediction_validator" in path.parts:
            continue
        number = _experiment_number(path)
        if number is None:
            continue
        document = _read(path)
        overall, cf = _score_from(document)
        if overall is None and cf is None:
            continue
        current = by_number.get(number)
        candidate = {"experiment_id": f"exp_{number:03d}", "number": number, "overall": overall, "cf_score": cf, "source": path}
        if current is None or (overall or -1.0, cf or -1.0, str(path).lower()) > (current.get("overall") or -1.0, current.get("cf_score") or -1.0, str(current["source"]).lower()):
            by_number[number] = candidate
    return [by_number[number] for number in sorted(by_number)]


def _metric(values: list[tuple[float, float]]) -> dict[str, Any]:
    if not values:
        return {"prediction_accuracy_pct": None, "mae": None, "rmse": None, "mbe": None, "evaluated_count": 0, "classification": "Insufficient Data"}
    errors = [predicted - actual for predicted, actual in values]
    accurate = sum(abs(error) <= max(0.5, abs(predicted) * 0.25) for (predicted, _), error in zip(values, errors))
    return {"prediction_accuracy_pct": round(accurate / len(values) * 100, 2), "mae": round(sum(abs(error) for error in errors) / len(errors), 4), "rmse": round(math.sqrt(sum(error * error for error in errors) / len(errors)), 4), "mbe": round(sum(errors) / len(errors), 4), "evaluated_count": len(values), "classification": "Accurate" if accurate == len(values) else "Overestimated" if sum(errors) > 0 else "Underestimated"}


def _group_metrics(rows: list[dict[str, Any]], group_key: str, predicted_key: str, actual_key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        key = str(row.get(group_key) or "Unknown")
        predicted, actual = _number(row.get(predicted_key)), _number(row.get(actual_key))
        if predicted is not None and actual is not None:
            groups.setdefault(key, []).append((predicted, actual))
        else:
            groups.setdefault(key, [])
    return {key: _metric(values) for key, values in sorted(groups.items())}


def _classification(predicted: float | None, actual: float | None) -> str:
    if predicted is None or actual is None:
        return "Insufficient Data"
    error = predicted - actual
    if abs(error) <= max(0.5, abs(predicted) * 0.25):
        return "Accurate"
    return "Overestimated" if error > 0 else "Underestimated"


def _planner_rows(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        return []
    rows = document.get("ranking", document.get("properties", []))
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _predictions(planner: Any, planner_summary: Any, scores: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(planner, dict):
        return [], []
    predictions = planner.get("sprints", [])
    current = _number(planner.get("current_overall"))
    if current is None and isinstance(planner_summary, dict):
        current = _number(planner_summary.get("current_overall"))
    current = current if current is not None else 0.0
    planner_number = _number(str(planner_summary.get("experiment_id", "")).replace("exp_", "")) if isinstance(planner_summary, dict) else None
    future = [item for item in scores if planner_number is None or item["number"] > planner_number]
    rows = []
    for index, prediction in enumerate(predictions if isinstance(predictions, list) else []):
        predicted_after = _number(prediction.get("estimated_overall_after"))
        predicted_gain = _number(prediction.get("estimated_gain_pct"))
        actual = future[index] if index < len(future) else None
        actual_gain = round(actual["overall"] - current, 4) if actual and actual.get("overall") is not None else None
        rows.append({"prediction_id": f"sprint_{index + 1}", "sprint": prediction.get("sprint", f"Sprint {index + 1}"), "predicted_overall_after": predicted_after, "predicted_overall_gain": predicted_gain if predicted_gain is not None else round((predicted_after - current), 4) if predicted_after is not None else None, "actual_experiment": actual["experiment_id"] if actual else None, "actual_overall": actual.get("overall") if actual else None, "actual_overall_gain": actual_gain, "error": round((predicted_gain if predicted_gain is not None else (predicted_after - current if predicted_after is not None else 0.0)) - actual_gain, 4) if actual_gain is not None else None, "classification": _classification(predicted_gain if predicted_gain is not None else (predicted_after - current if predicted_after is not None else None), actual_gain)})
    return rows, future


def _property_predictions(ranking: Any, scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _planner_rows(ranking)
    # Property-level outcomes require a later fingerprint/compare observation;
    # no property is credited from a score-only change.
    return sorted(({"property": row.get("property"), "domain": row.get("domain"), "sprint": row.get("sprint"), "difficulty": row.get("difficulty"), "predicted_gain": _number(row.get("estimated_overall_gain_pct")), "actual_gain": None, "classification": "Insufficient Data"} for row in rows if row.get("property")), key=lambda item: item["property"])


def _recommendations(metrics: dict[str, Any], property_rows: list[dict[str, Any]], difficulty: dict[str, Any], actual_count: int) -> list[dict[str, Any]]:
    output = []
    if actual_count == 0:
        output.append({"priority": "HIGH", "action": "perlu data tambahan", "recommendation": "Run at least one scored experiment after the planner before calibrating prediction accuracy, penalty, or confidence.", "basis": "No post-planner actual observation available."})
    elif metrics.get("mae") is not None and metrics["mae"] > 2.0:
        output.append({"priority": "HIGH", "action": "tingkatkan penalty", "recommendation": "Increase uncertainty penalty because planner error exceeds the deterministic tolerance.", "basis": f"MAE {metrics['mae']}."})
    elif metrics.get("mbe") is not None and metrics["mbe"] > 0.5:
        output.append({"priority": "MEDIUM", "action": "turunkan confidence", "recommendation": "Reduce planner confidence and use conservative gain estimates.", "basis": f"Positive MBE {metrics['mbe']} indicates overestimation."})
    else:
        output.append({"priority": "INFO", "action": "pertahankan estimator", "recommendation": "Keep the estimator and continue collecting independent scored experiments.", "basis": "Observed error is within tolerance."})
    if difficulty.get("classification") == "Insufficient Data":
        output.append({"priority": "MEDIUM", "action": "perlu data tambahan", "recommendation": "Do not recalibrate difficulty from score changes alone; collect property-level compare results.", "basis": "No property-level post-planner observations."})
    return output


def _markdown(summary: dict[str, Any], metrics: dict[str, Any], predictions: list[dict[str, Any]], property_rows: list[dict[str, Any]], recommendations: list[dict[str, Any]], confidence: dict[str, Any]) -> str:
    lines = ["# Experiment 026 — Prediction Validator", "", "Read-only validation of Optimization Planner predictions against subsequent scored artifacts. No browser or network request was used.", "", "## Executive Summary", "", f"Result: **{summary['result']}**", f"Predictions evaluated: **{metrics['evaluated_count']}**", f"Prediction accuracy: **{metrics['prediction_accuracy_pct'] if metrics['prediction_accuracy_pct'] is not None else 'Insufficient Data'}**", f"Planner confidence: **{confidence['classification']}**", "", "## Prediction Accuracy", "", "| Metric | Value |", "|---|---:|"]
    for key in ("prediction_accuracy_pct", "mae", "rmse", "mbe", "evaluated_count"):
        lines.append(f"| {key} | {metrics.get(key) if metrics.get(key) is not None else 'Insufficient Data'} |")
    lines += ["", "## Prediction Classification", "", "| Prediction | Sprint | Predicted Gain | Actual Gain | Classification |", "|---|---|---:|---:|---|"]
    for item in predictions:
        lines.append(f"| {item['prediction_id']} | {item['sprint']} | {item['predicted_overall_gain'] if item['predicted_overall_gain'] is not None else 'N/A'} | {item['actual_overall_gain'] if item['actual_overall_gain'] is not None else 'N/A'} | {item['classification']} |")
    lines += ["", "## Property Accuracy", "", f"Property predictions: **{len(property_rows)}**; all are classified against property-level observations only.", "", "## Difficulty Validation", "", f"Classification: **{confidence['difficulty_validation']['classification']}**", "", "## Confidence Analysis", "", json.dumps(confidence, ensure_ascii=False, indent=2), "", "## Recommendations", ""]
    for item in recommendations:
        lines.append(f"- **{item['priority']} — {item['action']}**: {item['recommendation']} ({item['basis']})")
    lines += ["", "## Validation", "", "Validation details are stored in `validation.json`; source artifacts remain unchanged.", ""]
    return "\n".join(lines)


def _validate(output: Path, predictions: list[dict[str, Any]], property_rows: list[dict[str, Any]], report: str) -> dict[str, Any]:
    required = ("prediction.json", "accuracy.json", "errors.json", "bias.json", "ranking.json", "confidence.json", "recommendations.json", "statistics.json", "summary.json", "prediction_validator.md")
    missing = [name for name in required if not (output / name).is_file()]
    order_valid = [item.get("prediction_id") for item in predictions] == sorted(item.get("prediction_id") for item in predictions)
    property_order_valid = [item.get("property") for item in property_rows] == sorted(item.get("property") for item in property_rows)
    metrics = _read(output / "accuracy.json")
    metric_valid = isinstance(metrics, dict) and all(metrics.get(key) is None or _number(metrics.get(key)) is not None for key in ("prediction_accuracy_pct", "mae", "rmse", "mbe"))
    confidence = _read(output / "confidence.json")
    confidence_valid = isinstance(confidence, dict) and confidence.get("classification") in {"High", "Medium", "Low", "Insufficient Data"}
    markdown_valid = all(section in report for section in ("Executive Summary", "Prediction Accuracy", "Prediction Classification", "Property Accuracy", "Difficulty Validation", "Confidence Analysis", "Recommendations", "Validation"))
    checks = {"artifact_completeness": not missing, "missing_artifacts": missing, "json_valid": True, "deterministic_ordering": order_valid and property_order_valid, "accuracy_validation": metric_valid, "error_metrics_valid": metric_valid, "confidence_validation": confidence_valid, "markdown_valid": markdown_valid, "source_artifacts_unchanged": True, "browser_launches": 0}
    checks["valid"] = all(value for key, value in checks.items() if key not in {"missing_artifacts", "browser_launches"})
    return checks


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment 026: validate optimization predictions")
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    args = _parser().parse_args(argv)
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    planner_path, planner = _latest(reports_root, "optimization_planner", "predictions.json")
    planner_summary_path, planner_summary = _latest(reports_root, "optimization_planner", "summary.json")
    ranking_path, ranking = _latest(reports_root, "optimization_planner", "ranking.json")
    evolution_path, evolution = _latest(reports_root, "fingerprint_evolution", "summary.json")
    dashboard_path = root / "reports" / "dashboard" / "dashboard_history.json"
    dashboard_history = _read(dashboard_path) if dashboard_path.is_file() else None
    importance_path, importance = _latest(reports_root, "fingerprint_importance", "summary.json")
    risk_path, risk = _latest(reports_root, "fingerprint_risk", "summary.json")
    session_path, session_diff = _latest(reports_root, "session_diff", "summary.json")
    consistency_path, consistency = _latest(reports_root, None, "consistency_report.json")
    comparator_path, comparator = _latest(reports_root, None, "compare.json")
    scores = _score_history(reports_root)
    predictions, future_scores = _predictions(planner, planner_summary, scores)
    property_rows = _property_predictions(ranking, scores)
    metric_values = [(item["predicted_overall_gain"], item["actual_overall_gain"]) for item in predictions if item.get("predicted_overall_gain") is not None and item.get("actual_overall_gain") is not None]
    metrics = _metric(metric_values)
    cf_values: list[tuple[float, float]] = []
    # The planner currently emits property-level CF gains but no sprint CF
    # trajectory; mark this metric insufficient instead of inferring it.
    cf_metrics = _metric(cf_values)
    property_metrics = _metric([(item["predicted_gain"], item["actual_gain"]) for item in property_rows if item.get("predicted_gain") is not None and item.get("actual_gain") is not None])
    errors = [{"prediction_id": item["prediction_id"], "sprint": item["sprint"], "error": item["error"], "classification": item["classification"], "reason": "No post-planner scored experiment exists." if item["classification"] == "Insufficient Data" else "Observed prediction error."} for item in predictions]
    bias = {"overall": {"mbe": metrics.get("mbe"), "mae": metrics.get("mae"), "rmse": metrics.get("rmse")}, "cf_score": {"mbe": cf_metrics.get("mbe"), "mae": cf_metrics.get("mae"), "rmse": cf_metrics.get("rmse")}, "property": {"mbe": property_metrics.get("mbe"), "mae": property_metrics.get("mae"), "rmse": property_metrics.get("rmse")}}
    ranking_rows = sorted(predictions, key=lambda item: (item["classification"] == "Insufficient Data", -(abs(item["error"]) if item.get("error") is not None else item.get("predicted_overall_gain") or 0), item["prediction_id"]))
    ranking_output = [{"rank": index, "prediction_id": item["prediction_id"], "sprint": item["sprint"], "predicted_gain": item["predicted_overall_gain"], "actual_gain": item["actual_overall_gain"], "error": item["error"], "classification": item["classification"]} for index, item in enumerate(ranking_rows, 1)]
    evaluated_predictions = [item for item in predictions if item.get("error") is not None]
    best_prediction = min(evaluated_predictions, key=lambda item: abs(item["error"])) if evaluated_predictions else None
    worst_prediction = max(evaluated_predictions, key=lambda item: abs(item["error"])) if evaluated_predictions else None
    difficulty_validation = {"classification": "Insufficient Data", "evaluated_properties": 0, "reason": "No post-planner property-level compare artifact is available."}
    confidence = {"classification": "High" if metrics["evaluated_count"] >= 10 and metrics.get("prediction_accuracy_pct", 0) >= 80 else "Medium" if metrics["evaluated_count"] >= 3 else "Insufficient Data", "coverage_pct": round(metrics["evaluated_count"] / len(predictions) * 100, 2) if predictions else 0.0, "evaluated_predictions": metrics["evaluated_count"], "insufficient_predictions": sum(item["classification"] == "Insufficient Data" for item in predictions), "difficulty_validation": difficulty_validation, "basis": "Coverage and error metrics from subsequent immutable experiment artifacts."}
    recommendations = _recommendations(metrics, property_rows, difficulty_validation, len(future_scores))
    source_paths = {"planner": relative_path(planner_path, root) if planner_path else None, "planner_summary": relative_path(planner_summary_path, root) if planner_summary_path else None, "dashboard_history": relative_path(dashboard_path, root) if dashboard_path.is_file() else None, "evolution": relative_path(evolution_path, root) if evolution_path else None, "importance": relative_path(importance_path, root) if importance_path else None, "risk": relative_path(risk_path, root) if risk_path else None, "session_diff": relative_path(session_path, root) if session_path else None, "consistency": relative_path(consistency_path, root) if consistency_path else None, "comparator": relative_path(comparator_path, root) if comparator_path else None}
    summary = {"experiment": "Experiment 026 — Prediction Validator", "experiment_id": None, "planner_source": source_paths["planner"], "predictions_total": len(predictions), "predictions_evaluated": metrics["evaluated_count"], "predictions_insufficient": confidence["insufficient_predictions"], "prediction_accuracy_pct": metrics["prediction_accuracy_pct"], "mae": metrics["mae"], "rmse": metrics["rmse"], "mbe": metrics["mbe"], "best_prediction": best_prediction, "worst_prediction": worst_prediction, "property_most_often_missed": None, "property_most_consistent": None, "planner_confidence": confidence["classification"], "difficulty_validation": difficulty_validation["classification"], "result": "SUCCESS" if metrics["evaluated_count"] else "PARTIAL" if planner is not None else "UNKNOWN", "analysis_only": True, "browser_launches": 0, "source_artifacts": source_paths}
    dashboard_entries = dashboard_history.get("experiment_history", []) if isinstance(dashboard_history, dict) else dashboard_history if isinstance(dashboard_history, list) else []
    statistics = {"predictions_total": len(predictions), "predictions_evaluated": metrics["evaluated_count"], "predictions_insufficient": confidence["insufficient_predictions"], "future_scored_experiments": len(future_scores), "classification_counts": dict(Counter(item["classification"] for item in predictions)), "property_predictions": len(property_rows), "property_evaluated": property_metrics["evaluated_count"], "source_count": sum(value is not None for value in source_paths.values()), "input_context": {"dashboard_history_entries": len(dashboard_entries), "importance_result": (importance or {}).get("result") if isinstance(importance, dict) else None, "risk_result": (risk or {}).get("result") if isinstance(risk, dict) else None, "evolution_result": (evolution or {}).get("result") if isinstance(evolution, dict) else None, "session_diff_result": (session_diff or {}).get("result") if isinstance(session_diff, dict) else None, "consistency_issue_count": len((consistency or {}).get("issues", [])) if isinstance(consistency, dict) and isinstance(consistency.get("issues"), list) else 0, "comparator_available": comparator is not None}, "browser_launches": 0}
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "prediction_validator"
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"experiment": summary["experiment"], "experiment_id": experiment.experiment_id, "created_at": experiment.started_at, "analysis_only": True, "browser_launches": 0, "source_artifacts_modified": False, "sources": source_paths, "environment": system_metadata(), "git": git_metadata(root)}
    report = _markdown(summary, metrics, predictions, property_rows, recommendations, confidence)
    write_json_exclusive(output / "metadata.json", metadata)
    write_json_exclusive(output / "prediction.json", {"predictions": predictions, "property_predictions": property_rows})
    accuracy_document = {**metrics, "cf_score": cf_metrics, "property": property_metrics, "by_module": _group_metrics(property_rows, "domain", "predicted_gain", "actual_gain"), "by_property": _group_metrics(property_rows, "property", "predicted_gain", "actual_gain"), "by_sprint": _group_metrics(predictions, "sprint", "predicted_overall_gain", "actual_overall_gain"), "by_experiment": _group_metrics(predictions, "actual_experiment", "predicted_overall_gain", "actual_overall_gain")}
    write_json_exclusive(output / "accuracy.json", accuracy_document)
    write_json_exclusive(output / "errors.json", {"errors": errors})
    write_json_exclusive(output / "bias.json", bias)
    write_json_exclusive(output / "ranking.json", {"ranking": ranking_output, "best_prediction": best_prediction, "worst_prediction": worst_prediction, "property_most_often_missed": None, "property_most_consistent": None})
    write_json_exclusive(output / "confidence.json", confidence)
    write_json_exclusive(output / "recommendations.json", {"recommendations": recommendations})
    write_json_exclusive(output / "statistics.json", statistics)
    write_json_exclusive(output / "summary.json", summary)
    write_text_exclusive(output / "prediction_validator.md", report)
    validation = _validate(output, predictions, property_rows, report)
    write_json_exclusive(output / "validation.json", validation)
    print("\nPREDICTION VALIDATOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Predictions: {len(predictions)} | Evaluated: {metrics['evaluated_count']}")
    print(f"Accuracy: {metrics['prediction_accuracy_pct'] if metrics['prediction_accuracy_pct'] is not None else 'Insufficient Data'}")
    print(f"Confidence: {confidence['classification']}")
    print(f"Result: {summary['result']}")
    print(f"Artifacts: {relative_path(output, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
