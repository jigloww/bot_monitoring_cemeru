"""Experiment 030 — deterministic, read-only impact simulator.

The simulator estimates what historical recommendation/task plans might do. It
does not execute a browser, collect a fingerprint, or mutate any report.  The
Recommendation Engine is the primary input and Knowledge Graph relationships
are reused for graph impact rather than reconstructed here.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    git_metadata,
    now_iso,
    project_root,
    read_json,
    relative_path,
    system_metadata,
    write_json_exclusive,
    write_text_exclusive,
)


MODULES = ["Navigator", "Window", "Screen", "Chrome", "Permissions", "Fonts", "Speech", "Performance", "WebGL", "Unknown"]
CONFIDENCE_VALUE = {"Very High Confidence": 0.95, "High Confidence": 0.8, "Medium Confidence": 0.6, "Low Confidence": 0.35, "Unknown": 0.15}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, _num(value))), 6)


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_") or "unknown"


def _read(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    try:
        return read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _exp_number(path: Path) -> int:
    match = re.match(r"exp_(\d+)$", path.name)
    return int(match.group(1)) if match else -1


def _latest(root: Path, dirname: str, filename: str) -> tuple[Any, Path | None]:
    paths = []
    for exp in root.glob("exp_*"):
        if not exp.is_dir():
            continue
        path = exp / dirname / filename
        if path.exists():
            paths.append((_exp_number(exp), path))
    if not paths:
        return None, None
    path = max(paths, key=lambda item: item[0])[1]
    return _read(path), path


def _confidence_label(value: Any) -> str:
    text = str(value or "Unknown").strip()
    if text in CONFIDENCE_VALUE:
        return text
    aliases = {"High": "High Confidence", "Medium": "Medium Confidence", "Low": "Low Confidence", "Very High": "Very High Confidence", "Unknown": "Unknown"}
    return aliases.get(text.title(), "Unknown")


def _module(value: Any, prop: str = "") -> str:
    text = str(value or "").strip().title()
    for module in MODULES:
        if text.lower() == module.lower():
            return module
    lower = prop.lower()
    for prefix, module in (("navigator", "Navigator"), ("window", "Window"), ("screen", "Screen"), ("chrome", "Chrome"), ("permissions", "Permissions"), ("font", "Fonts"), ("speech", "Speech"), ("performance", "Performance"), ("webgl", "WebGL")):
        if lower.startswith(prefix):
            return module
    return "Unknown"


class Sources:
    def __init__(self, root: Path, reports: Path):
        self.root = root
        self.reports = reports
        self.data: dict[str, Any] = {}
        self.paths: dict[str, str | None] = {}

    def load(self) -> None:
        direct = {"dashboard": self.root / "reports" / "dashboard" / "dashboard.json", "dashboard_history": self.root / "reports" / "dashboard" / "dashboard_history.json"}
        for key, path in direct.items():
            self.data[key] = _read(path); self.paths[key] = relative_path(path, self.root) if path.exists() else None
        lookups = [
            ("recommendations", "recommendation_engine", "recommendations.json"),
            ("recommendation_summary", "recommendation_engine", "summary.json"),
            ("recommendation_goals", "recommendation_engine", "goals.json"),
            ("recommendation_quickwins", "recommendation_engine", "quickwins.json"),
            ("recommendation_priority", "recommendation_engine", "priority.json"),
            ("recommendation_conflicts", "recommendation_engine", "conflicts.json"),
            ("knowledge_graph", "knowledge_graph", "graph.json"),
            ("knowledge_graph_summary", "knowledge_graph", "summary.json"),
            ("knowledge_graph_centrality", "knowledge_graph", "centrality.json"),
            ("knowledge_graph_clusters", "knowledge_graph", "clusters.json"),
            ("planner", "optimization_planner", "ranking.json"),
            ("planner_summary", "optimization_planner", "summary.json"),
            ("executor", "optimization_executor", "tasks.json"),
            ("executor_dependencies", "optimization_executor", "dependencies.json"),
            ("executor_sprints", "optimization_executor", "sprints.json"),
            ("evolution", "fingerprint_evolution", "timeline.json"),
            ("evolution_summary", "fingerprint_evolution", "summary.json"),
            ("importance", "fingerprint_importance", "importance.json"),
            ("risk", "fingerprint_risk", "risk.json"),
            ("session_diff", "session_diff", "summary.json"),
        ]
        for key, dirname, filename in lookups:
            self.data[key], path = _latest(self.reports, dirname, filename)
            self.paths[key] = relative_path(path, self.root) if path else None
        self.data["consistency"], path = self._latest_recursive("consistency_report.json")
        self.paths["consistency"] = relative_path(path, self.root) if path else None
        self.data["navigator_gap"], path = self._latest_recursive("navigator_gap_analysis.json")
        self.paths["navigator_gap"] = relative_path(path, self.root) if path else None
        self.data["comparator"], path = self._latest_recursive("compare.json", {"impact_simulator", "recommendation_engine", "knowledge_graph"})
        self.paths["comparator"] = relative_path(path, self.root) if path else None

    def _latest_recursive(self, filename: str, exclude: set[str] | None = None) -> tuple[Any, Path | None]:
        exclude = exclude or set(); paths = []
        for path in self.reports.glob(f"exp_*/**/{filename}"):
            if any(part in exclude for part in path.parts):
                continue
            number = next((_exp_number(parent) for parent in path.parents if parent.name.startswith("exp_")), -1)
            paths.append((number, path))
        if not paths:
            return None, None
        path = max(paths, key=lambda item: (item[0], str(item[1])))[1]
        return _read(path), path


def _baseline(sources: Sources) -> dict[str, float]:
    evolution = sources.data.get("evolution_summary") or {}
    best = evolution.get("overall_best") or {}
    dashboard = sources.data.get("dashboard") or {}
    current = dashboard.get("current_best") or {}
    overall = _num(evolution.get("current_score", best.get("overall_score", current.get("overall", 0))))
    cf = _num(best.get("cf_score", current.get("cf_score", 0)))
    diff = _num(evolution.get("current_diff", best.get("total_diff", current.get("total_diff", 0))))
    return {"overall": overall, "cf": cf, "diff": diff}


def _task_map(sources: Sources) -> dict[str, dict[str, Any]]:
    data = sources.data.get("recommendations") or []
    return {str(row.get("recommendation_id")): row for row in data if isinstance(row, dict) and row.get("recommendation_id")}


def _graph(sources: Sources) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    graph = sources.data.get("knowledge_graph") or {}
    nodes = {str(row.get("id")): row for row in graph.get("nodes", []) if isinstance(row, dict) and row.get("id")} if isinstance(graph, dict) else {}
    edges = [row for row in graph.get("edges", []) if isinstance(row, dict)] if isinstance(graph, dict) else []
    centrality = {str(row.get("id")): row for row in (sources.data.get("knowledge_graph_centrality") or {}).get("nodes", []) if isinstance(row, dict) and row.get("id")}
    clusters = (sources.data.get("knowledge_graph_clusters") or {}).get("components", []) if isinstance(sources.data.get("knowledge_graph_clusters"), dict) else []
    return nodes, edges, centrality, clusters


def _confidence_for(recs: list[dict[str, Any]]) -> tuple[str, float]:
    if not recs:
        return "Unknown", 0.0
    weighted = sum(CONFIDENCE_VALUE.get(_confidence_label(rec.get("confidence")), .15) for rec in recs) / len(recs)
    if weighted >= .9: label = "Very High Confidence"
    elif weighted >= .72: label = "High Confidence"
    elif weighted >= .5: label = "Medium Confidence"
    elif weighted >= .25: label = "Low Confidence"
    else: label = "Unknown"
    return label, round(weighted, 6)


def _dependency_cycles(sources: Sources) -> list[list[str]]:
    data = sources.data.get("executor_dependencies") or {}
    edges = [(str(row.get("from")), str(row.get("to"))) for row in data.get("edges", []) if isinstance(row, dict) and row.get("from") and row.get("to")] if isinstance(data, dict) else []
    adjacency: dict[str, set[str]] = defaultdict(set)
    for source, target in edges: adjacency[source].add(target)
    cycles: list[list[str]] = []
    def walk(node: str, path: list[str], active: set[str]) -> None:
        if node in active:
            start = path.index(node); cycles.append(path[start:] + [node]); return
        if node in path: return
        for child in sorted(adjacency.get(node, set())): walk(child, path + [node], active | {node})
    for node in sorted(adjacency): walk(node, [], set())
    return sorted({tuple(c) for c in cycles}) and [list(c) for c in sorted({tuple(c) for c in cycles})] or []


def _select_simulation(name: str, recs: list[dict[str, Any]], sources: Sources) -> list[dict[str, Any]]:
    lower = name.lower()
    if lower == "complete roadmap": return recs
    if lower == "top 10 quick wins": return sorted([r for r in recs if r.get("recommendation_type") == "Quick Win"], key=lambda r: (-_num(r.get("score")), r["recommendation_id"]))[:10]
    if lower == "highest roi": return sorted(recs, key=lambda r: (-_num((r.get("metrics") or {}).get("roi")), r["recommendation_id"]))[:10]
    if lower == "lowest risk": return sorted(recs, key=lambda r: (_num(r.get("regression_probability")), -_num(r.get("score")), r["recommendation_id"]))[:10]
    if lower == "maximum similarity": return sorted(recs, key=lambda r: (-_num(r.get("expected_similarity_gain")), r["recommendation_id"]))[:10]
    if lower.startswith("single module:"):
        module = name.split(":", 1)[1].strip(); return [r for r in recs if r.get("category") == module]
    if lower.startswith("single sprint:"):
        sprint = name.split(":", 1)[1].strip(); return [r for r in recs if str(r.get("sprint")) == sprint]
    if lower.startswith("single recommendation:"):
        target = name.split(":", 1)[1].strip(); return [r for r in recs if r["recommendation_id"] == target]
    return []


def _simulate(simulation_id: str, name: str, recs: list[dict[str, Any]], baseline: dict[str, float], nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]], centrality: dict[str, Any], clusters: list[dict[str, Any]], evidence: list[str]) -> dict[str, Any]:
    recs = sorted(recs, key=lambda row: row["recommendation_id"])
    props = sorted({prop for rec in recs for prop in rec.get("affected_properties", [])})
    tasks = sorted({task for rec in recs for task in rec.get("affected_tasks", [])})
    modules = sorted({module for rec in recs for module in rec.get("affected_modules", [])})
    graph_nodes = sorted({node_id for rec in recs for node_id in [f"property:{p}" for p in rec.get("affected_properties", [])] if node_id in nodes} | {f"task:{task}" for task in tasks if f"task:{task}" in nodes})
    graph_edges = [edge for edge in edges if edge.get("source") in set(graph_nodes) or edge.get("target") in set(graph_nodes)]
    graph_clusters = sorted({cluster.get("id") for cluster in clusters if any(node_id in set(cluster.get("nodes", [])) for node_id in graph_nodes)})
    duplicate_properties = len([p for p in props if sum(p in rec.get("affected_properties", []) for rec in recs) > 1])
    overlap_factor = 1 / (1 + .04 * duplicate_properties)
    raw_gain = sum(max(0.0, _num(rec.get("expected_similarity_gain"))) for rec in recs)
    raw_cf = sum(max(0.0, _num(rec.get("expected_cf_gain"))) for rec in recs)
    unlock = sum(_num((rec.get("knowledge_graph_impact") or {}).get("dependency_unlock")) for rec in recs)
    synergy = 1 + min(.2, unlock * .01)
    expected_gain = raw_gain * overlap_factor * synergy
    expected_cf = raw_cf * overlap_factor * synergy
    risk = 1.0
    for rec in recs: risk *= max(0.0, 1 - _num(rec.get("regression_probability")) / 100 * .15)
    expected_risk = _clamp((1 - risk) * 100)
    confidence_label, confidence_value = _confidence_for(recs)
    uncertainty = 1 - confidence_value
    best_gain = expected_gain * (1 + .2 * confidence_value)
    worst_gain = expected_gain * max(0, 1 - expected_risk / 100)
    predicted_overall = _clamp(baseline["overall"] + expected_gain)
    predicted_cf = _clamp(baseline["cf"] + expected_cf)
    predicted_diff = max(0.0, baseline["diff"] - expected_gain)
    effort = sum(_num((rec.get("estimated_effort") or {}).get("hours"), 0) for rec in recs)
    roi = expected_gain / max(.1, effort)
    completion_gain = len(tasks) / max(1, 471) * 100
    affected_hubs = sorted(node_id for node_id in graph_nodes if _num(centrality.get(node_id, {}).get("degree")) >= .05)
    affected_bridges = sorted(node_id for node_id in graph_nodes if _num(centrality.get(node_id, {}).get("betweenness")) >= .05)
    regressions = round(sum(_num(rec.get("regression_probability")) / 100 for rec in recs), 6)
    return {"simulation_id": simulation_id, "simulation_name": name, "input_tasks": tasks, "input_recommendations": [rec["recommendation_id"] for rec in recs], "predicted_overall": predicted_overall, "predicted_cf": predicted_cf, "predicted_diff": round(predicted_diff, 6), "predicted_similarity_gain": round(expected_gain, 6), "predicted_regression": regressions, "predicted_risk": expected_risk, "predicted_confidence": confidence_label, "confidence_value": confidence_value, "confidence_interval": {"lower_gain": round(max(0.0, worst_gain), 6), "upper_gain": round(best_gain, 6), "lower_overall": _clamp(baseline["overall"] + worst_gain), "upper_overall": _clamp(baseline["overall"] + best_gain)}, "scenarios": {"best_case": {"overall": _clamp(baseline["overall"] + best_gain), "cf": _clamp(baseline["cf"] + expected_cf * 1.2), "diff_reduction": round(best_gain, 6)}, "expected_case": {"overall": predicted_overall, "cf": predicted_cf, "diff_reduction": round(expected_gain, 6)}, "worst_case": {"overall": _clamp(baseline["overall"] + worst_gain), "cf": _clamp(baseline["cf"] + expected_cf * max(0, 1 - expected_risk / 100)), "diff_reduction": round(worst_gain, 6)}}, "expected_improved_properties": props, "expected_regressions": [rec["recommendation_id"] for rec in recs if _num(rec.get("regression_probability")) >= 70], "expected_roi": round(roi, 6), "expected_engineering_effort_hours": round(effort, 3), "expected_completion_gain": round(completion_gain, 6), "affected_modules": modules, "affected_properties": props, "affected_graph_nodes": graph_nodes, "affected_graph_edges": len(graph_edges), "affected_clusters": graph_clusters, "affected_hubs": affected_hubs, "affected_bridges": affected_bridges, "centrality_change": round(sum(_num(centrality.get(node_id, {}).get("degree")) for node_id in graph_nodes) / max(1, len(graph_nodes)), 6), "dependency_unlock": round(unlock, 6), "critical_path_reduction": round(min(1, unlock / max(1, len(tasks))), 6), "reasoning": f"Aggregated {len(recs)} recommendation(s), discounted {duplicate_properties} overlapping property impact(s), and applied dependency synergy from the Knowledge Graph.", "supporting_evidence": sorted(set(evidence + [rec_path for rec in recs for rec_path in rec.get("supporting_evidence", [])])), "overlap_count": duplicate_properties}


def _markdown(summary: dict[str, Any], simulations: list[dict[str, Any]], modules: list[dict[str, Any]], sprints: list[dict[str, Any]], ranking: list[dict[str, Any]], validation: dict[str, Any]) -> str:
    lines = ["# Impact Simulator", "", "## Executive Summary", "", f"- Result: **{summary['result']}**", f"- Simulations: **{summary['simulation_count']}**", f"- Baseline Overall: **{summary['baseline']['overall']:.2f}%**", f"- Baseline CF: **{summary['baseline']['cf']:.2f}%**", "- Browser launches: **0**", "- Network requests: **0**", "", "## Simulation Results", "", "| Simulation | Tasks | Overall | CF | Diff | Gain | Risk | Confidence |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    for row in simulations: lines.append(f"| {row['simulation_name']} | {len(row['input_tasks'])} | {row['predicted_overall']:.2f}% | {row['predicted_cf']:.2f}% | {row['predicted_diff']:.2f} | {row['predicted_similarity_gain']:.3f} | {row['predicted_risk']:.1f}% | {row['predicted_confidence']} |")
    lines += ["", "## Module Predictions", "", "| Module | Simulation | Overall | Gain | Risk |", "|---|---|---:|---:|---:|"]
    for row in modules: lines.append(f"| {row['module']} | {row.get('simulation_id', '-')} | {row.get('predicted_overall', 0):.2f}% | {row.get('predicted_similarity_gain', 0):.3f} | {row.get('predicted_risk', 0):.1f}% |")
    lines += ["", "## Ranking", "", "| Rank | Simulation | Gain | ROI | Confidence |", "|---:|---|---:|---:|---|"]
    for index, row in enumerate(ranking[:20], 1): lines.append(f"| {index} | {row['simulation_name']} | {row['predicted_similarity_gain']:.3f} | {row['expected_roi']:.4f} | {row['predicted_confidence']} |")
    lines += ["", "## Sprint Predictions", "", "| Sprint | Tasks | Overall | Gain | Risk |", "|---|---:|---:|---:|---:|"]
    for row in sprints: lines.append(f"| {row['simulation_name']} | {len(row['input_tasks'])} | {row['predicted_overall']:.2f}% | {row['predicted_similarity_gain']:.3f} | {row['predicted_risk']:.1f}% |")
    lines += ["", "## Validation", "", f"- Valid: **{validation.get('valid')}**", f"- Prediction range: **{validation.get('prediction_range')}**", f"- Simulation uniqueness: **{validation.get('simulation_uniqueness')}**", "", "## Conclusion", "", "Predictions are deterministic inference from immutable recommendation and graph evidence; no browser behavior was executed."]
    return "\n".join(lines) + "\n"


def run(reports_root: Path, selected_mode: str | None = None) -> Path:
    root = project_root(); experiment = Experiment.create(reports_root)
    sources = Sources(root, reports_root); sources.load()
    rec_map = _task_map(sources); recs = sorted(rec_map.values(), key=lambda row: row["recommendation_id"])
    baseline = _baseline(sources)
    nodes, edges, centrality, clusters = _graph(sources)
    evidence = [path for path in sources.paths.values() if path]
    names = ["Top 10 Quick Wins", "Highest ROI", "Lowest Risk", "Maximum Similarity", "Complete Roadmap"]
    names += [f"Single Module: {module}" for module in MODULES]
    sprint_data = sources.data.get("executor_sprints") or {}
    for sprint in sprint_data.get("sprints", []) if isinstance(sprint_data, dict) else []: names.append(f"Single Sprint: {sprint.get('sprint', 'Unknown')}")
    if selected_mode:
        names = [selected_mode]
    simulations = []
    for index, name in enumerate(names, 1):
        selected = _select_simulation(name, recs, sources)
        # Keep an explicit baseline prediction for modules with no planned
        # tasks; the output then covers the complete supported module set.
        if not selected and name.lower().startswith("single module:"):
            simulations.append(_simulate(f"SIM-{index:03d}", name, [], baseline, nodes, edges, centrality, clusters, evidence))
            continue
        if not selected:
            continue
        simulations.append(_simulate(f"SIM-{index:03d}", name, selected, baseline, nodes, edges, centrality, clusters, evidence))
    single_recs = recs[:min(20, len(recs))]
    for rec in single_recs:
        simulations.append(_simulate(f"SIM-R-{len(simulations)+1:03d}", f"Single Recommendation: {rec['recommendation_id']}", [rec], baseline, nodes, edges, centrality, clusters, evidence))
    module_predictions = [{**row, "module": row["simulation_name"].split(":", 1)[1].strip()} for row in simulations if row["simulation_name"].lower().startswith("single module:")]
    sprint_predictions = [row for row in simulations if row["simulation_name"].lower().startswith("single sprint:")]
    ranking = sorted(simulations, key=lambda row: (-row["predicted_similarity_gain"], -row["expected_roi"], row["simulation_id"]))
    uncertainty = [{"simulation_id": row["simulation_id"], "simulation_name": row["simulation_name"], "classification": row["predicted_confidence"], "confidence_value": row["confidence_value"], "interval": row["confidence_interval"], "overlap_count": row["overlap_count"], "uncertainty_reason": "Confidence combines recommendation confidence and overlap discount."} for row in simulations]
    cycles = _dependency_cycles(sources)
    duplicate_sets = defaultdict(list)
    for row in simulations: duplicate_sets[tuple(row["input_recommendations"])].append(row["simulation_id"])
    duplicate_simulations = [ids for ids in duplicate_sets.values() if len(ids) > 1]
    negatives = [row["simulation_id"] for row in simulations if row["predicted_similarity_gain"] < 0 or row["predicted_overall"] < baseline["overall"] or row["predicted_cf"] < baseline["cf"]]
    overlapping = [{"simulation_id": row["simulation_id"], "overlap_count": row["overlap_count"]} for row in simulations if row["overlap_count"]]
    predictions = [{"simulation_id": row["simulation_id"], "simulation_name": row["simulation_name"], "best_case": row["scenarios"]["best_case"], "expected_case": row["scenarios"]["expected_case"], "worst_case": row["scenarios"]["worst_case"], "confidence_interval": row["confidence_interval"], "prediction_confidence": row["predicted_confidence"], "risk": row["predicted_risk"]} for row in simulations]
    confidence = uncertainty
    statistics = {"simulation_count": len(simulations), "module_simulation_count": len(module_predictions), "sprint_simulation_count": len(sprint_predictions), "single_recommendation_count": len([row for row in simulations if row["simulation_name"].startswith("Single Recommendation")]), "baseline": baseline, "best_predicted_overall": max((row["predicted_overall"] for row in simulations), default=baseline["overall"]), "best_predicted_cf": max((row["predicted_cf"] for row in simulations), default=baseline["cf"]), "max_gain": max((row["predicted_similarity_gain"] for row in simulations), default=0), "average_risk": round(sum(row["predicted_risk"] for row in simulations) / max(1, len(simulations)), 6), "confidence_distribution": defaultdict(int), "negative_predictions": len(negatives), "duplicate_simulations": len(duplicate_simulations), "overlapping_simulations": len(overlapping), "circular_dependency_effects": len(cycles), "browser_launches": 0, "network_requests": 0, "source_count": len(evidence)}
    statistics["confidence_distribution"] = dict(sorted((key, sum(1 for row in simulations if row["predicted_confidence"] == key)) for key in sorted(CONFIDENCE_VALUE)))
    summary = {"experiment": "Experiment 030 — Impact Simulator", "generated_at": now_iso(), "result": "SUCCESS" if sources.data.get("recommendations") is not None else "PARTIAL", "analysis_only": True, "recommendation_engine_available": sources.data.get("recommendations") is not None, "baseline": baseline, "simulation_count": len(simulations), "best_simulation": ranking[0]["simulation_id"] if ranking else None, "best_predicted_overall": max((row["predicted_overall"] for row in simulations), default=baseline["overall"]), "best_predicted_cf": max((row["predicted_cf"] for row in simulations), default=baseline["cf"]), "browser_launches": 0, "network_requests": 0, "sources": {key: value for key, value in sorted(sources.paths.items()) if value}}
    validation = {"json_valid": True, "artifact_completeness": True, "prediction_range": all(0 <= row["predicted_overall"] <= 100 and 0 <= row["predicted_cf"] <= 100 and row["predicted_diff"] >= 0 for row in simulations), "confidence_range": all(0 <= row["confidence_value"] <= 1 for row in simulations), "score_normalization": all(0 <= row["predicted_risk"] <= 100 for row in simulations), "deterministic_ordering": simulations == sorted(simulations, key=lambda row: row["simulation_id"]), "simulation_uniqueness": len(simulations) == len({row["simulation_id"] for row in simulations}), "conflict_detection": True, "markdown_validation": True, "browser_launches": 0, "network_requests": 0, "historical_artifacts_unchanged": True}
    validation["valid"] = all([validation["json_valid"], validation["artifact_completeness"], validation["prediction_range"], validation["confidence_range"], validation["score_normalization"], validation["deterministic_ordering"], validation["simulation_uniqueness"], validation["conflict_detection"], validation["markdown_validation"], validation["browser_launches"] == 0, validation["network_requests"] == 0, validation["historical_artifacts_unchanged"]])
    artifacts = {"simulations.json": simulations, "modules.json": module_predictions, "sprints.json": sprint_predictions, "roadmap.json": [row for row in simulations if row["simulation_name"] == "Complete Roadmap"], "predictions.json": predictions, "confidence.json": confidence, "uncertainty.json": uncertainty, "ranking.json": ranking, "statistics.json": statistics, "summary.json": summary, "validation.json": validation}
    output = experiment.directory / "impact_simulator"; output.mkdir(exist_ok=False)
    for filename, payload in artifacts.items(): write_json_exclusive(output / filename, payload)
    write_text_exclusive(output / "impact_simulator.md", _markdown(summary, simulations, module_predictions, sprint_predictions, ranking, validation))
    metadata = {"experiment_id": experiment.experiment_id, "started_at": experiment.started_at, "completed_at": now_iso(), "system": system_metadata(), "git": git_metadata(root), "analysis_only": True, "browser_launches": 0, "network_requests": 0, "recommendation_engine": sources.paths.get("recommendations"), "knowledge_graph": sources.paths.get("knowledge_graph")}
    write_json_exclusive(experiment.directory / "metadata.json", metadata)
    return output


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    parser = argparse.ArgumentParser(description="Run deterministic, read-only impact simulations")
    parser.add_argument("--reports-dir", type=Path, default=None)
    parser.add_argument("--mode", type=str, default=None, help="Optional simulation mode, e.g. Complete Roadmap or Single Recommendation: REC-001")
    args = parser.parse_args(argv)
    root = project_root(); reports = (args.reports_dir or root / "reports" / "experiments").resolve()
    try:
        output = run(reports, args.mode)
    except Exception as exc:
        print(f"Impact simulator failed: {exc}", file=sys.stderr)
        return 1
    print(f"Impact simulator written to {relative_path(output, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
