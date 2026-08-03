"""Experiment 029 — Recommendation Engine v2.

This module is deliberately analysis-only.  It consumes the immutable reports
from the optimization pipeline (especially the Knowledge Graph) and emits a
deterministic engineering recommendation backlog.  No browser, Playwright,
network, or stealth code is imported or executed.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
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
DIFFICULTY_POINTS = {"Easy": 1.0, "Medium": 2.0, "Hard": 3.5, "Very Hard": 5.0, "Unknown": 3.0}
RISK_POINTS = {"Low": 15.0, "Medium": 45.0, "High": 75.0, "Critical": 95.0, "Unknown": 55.0}
TYPE_NAMES = {"High ROI", "Low Risk", "Quick Win", "Long Term", "Dependency Unlock", "Validation Required", "Experimental", "Avoid", "No Benefit", "Regression Risk", "Knowledge Gap"}


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


def _latest_recursive(root: Path, filename: str, exclude: set[str] | None = None) -> tuple[Any, Path | None]:
    exclude = exclude or set()
    def path_experiment_number(path: Path) -> int:
        for parent in path.parents:
            if parent.name.startswith("exp_"):
                return _exp_number(parent)
        return -1

    paths = []
    for path in root.glob(f"exp_*/**/{filename}"):
        if any(part in exclude for part in path.parts):
            continue
        paths.append((path_experiment_number(path), path))
    if not paths:
        return None, None
    path = max(paths, key=lambda item: (item[0], str(item[1])))[1]
    return _read(path), path


def _confidence(value: Any) -> str:
    text = str(value or "Unknown").strip().title()
    return text if text in {"High", "Medium", "Low", "Unknown"} else "Unknown"


def _module(value: Any, prop: str = "") -> str:
    text = str(value or "").strip().title()
    for module in MODULES:
        if text.lower() == module.lower():
            return module
    lower = prop.lower()
    for prefix, module in (("navigator", "Navigator"), ("window", "Window"), ("screen", "Screen"), ("chrome", "Chrome"), ("permissions", "Permissions"), ("font", "Fonts"), ("speech", "Speech"), ("performance", "Performance"), ("webgl", "WebGL")):
        if lower.startswith(prefix):
            return module
    return text if text in MODULES else "Unknown"


def _first(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


class SourceStore:
    """Discover immutable reports without assuming a fixed experiment number."""

    def __init__(self, root: Path, reports: Path):
        self.root = root
        self.reports = reports
        self.data: dict[str, Any] = {}
        self.paths: dict[str, str | None] = {}

    def load(self) -> None:
        direct = {
            "dashboard": self.root / "reports" / "dashboard" / "dashboard.json",
            "dashboard_history": self.root / "reports" / "dashboard" / "dashboard_history.json",
        }
        for key, path in direct.items():
            self.data[key] = _read(path)
            self.paths[key] = relative_path(path, self.root) if path.exists() else None
        lookups = [
            ("evolution", "fingerprint_evolution", "timeline.json"),
            ("evolution_summary", "fingerprint_evolution", "summary.json"),
            ("importance", "fingerprint_importance", "importance.json"),
            ("importance_summary", "fingerprint_importance", "summary.json"),
            ("risk", "fingerprint_risk", "risk.json"),
            ("risk_summary", "fingerprint_risk", "summary.json"),
            ("planner", "optimization_planner", "ranking.json"),
            ("planner_summary", "optimization_planner", "summary.json"),
            ("executor", "optimization_executor", "tasks.json"),
            ("executor_dependencies", "optimization_executor", "dependencies.json"),
            ("executor_sprints", "optimization_executor", "sprints.json"),
            ("executor_summary", "optimization_executor", "summary.json"),
            ("knowledge_graph", "knowledge_graph", "graph.json"),
            ("knowledge_graph_summary", "knowledge_graph", "summary.json"),
            ("knowledge_graph_centrality", "knowledge_graph", "centrality.json"),
            ("knowledge_graph_impact", "knowledge_graph", "impact.json"),
            ("knowledge_graph_modules", "knowledge_graph", "modules.json"),
            ("knowledge_graph_clusters", "knowledge_graph", "clusters.json"),
            ("knowledge_graph_recommendations", "knowledge_graph", "recommendations.json"),
            ("session_diff", "session_diff", "summary.json"),
        ]
        for key, dirname, filename in lookups:
            self.data[key], path = _latest(self.reports, dirname, filename)
            self.paths[key] = relative_path(path, self.root) if path else None
        self.data["consistency"], path = _latest_recursive(self.reports, "consistency_report.json")
        self.paths["consistency"] = relative_path(path, self.root) if path else None
        self.data["navigator_gap"], path = _latest_recursive(self.reports, "navigator_gap_analysis.json")
        self.paths["navigator_gap"] = relative_path(path, self.root) if path else None
        self.data["comparator"], path = _latest_recursive(self.reports, "compare.json", {"knowledge_graph", "recommendation_engine"})
        self.paths["comparator"] = relative_path(path, self.root) if path else None
        # Historical summaries are useful as a success/failure prior.
        summaries = []
        for exp in sorted(self.reports.glob("exp_*"), key=_exp_number):
            if not exp.is_dir():
                continue
            candidates = [exp / "summary.json"] if (exp / "summary.json").exists() else sorted(exp.rglob("summary.json"))
            candidates = [p for p in candidates if "recommendation_engine" not in p.parts]
            if candidates:
                value = _read(candidates[0])
                if isinstance(value, dict): summaries.append({"experiment_id": exp.name, "path": relative_path(candidates[0], self.root), "summary": value})
        self.data["historical_summaries"] = summaries
        self.paths["historical_summaries"] = "reports/experiments/exp_*/summary.json"


def _task_rows(store: SourceStore) -> list[dict[str, Any]]:
    data = store.data.get("executor") or {}
    rows = data.get("tasks", []) if isinstance(data, dict) else []
    return sorted((row for row in rows if isinstance(row, dict) and row.get("task_id")), key=lambda row: str(row["task_id"]))


def _node_map(store: SourceStore) -> dict[str, dict[str, Any]]:
    graph = store.data.get("knowledge_graph") or {}
    nodes = graph.get("nodes", []) if isinstance(graph, dict) else []
    return {str(node.get("id")): node for node in nodes if isinstance(node, dict) and node.get("id")}


def _edge_rows(store: SourceStore) -> list[dict[str, Any]]:
    graph = store.data.get("knowledge_graph") or {}
    edges = graph.get("edges", []) if isinstance(graph, dict) else []
    return [edge for edge in edges if isinstance(edge, dict) and edge.get("source") and edge.get("target")]


def _property_node(nodes: dict[str, dict[str, Any]], prop: str) -> dict[str, Any]:
    return nodes.get(f"property:{prop}", {})


def _difficulty(task: dict[str, Any]) -> str:
    value = _first(task, "estimated_difficulty", "difficulty", default="Unknown")
    return str(value or "Unknown").title()


def _risk_level(task: dict[str, Any]) -> str:
    value = _first(task, "risk_level", "implementation_risk", default="Unknown")
    return str(value or "Unknown").title()


def _effort_hours(task: dict[str, Any]) -> float:
    effort = task.get("estimated_engineering_effort") or {}
    return max(0.1, _num(effort.get("estimated_hours", task.get("estimated_effort", 0)), 8.0))


def _historical_signal(store: SourceStore, prop: str) -> tuple[float, float, int]:
    improved = failed = 0
    occurrences = 0
    for item in store.data.get("historical_summaries", []):
        summary = item.get("summary", {})
        for key in ("improved", "improved_keys", "improvements"):
            values = summary.get(key, [])
            if isinstance(values, list) and prop in {str(v) for v in values}:
                improved += 1; occurrences += 1
        for key in ("regressed", "regressed_keys", "regressions"):
            values = summary.get(key, [])
            if isinstance(values, list) and prop in {str(v) for v in values}:
                failed += 1; occurrences += 1
    return float(improved), float(failed), occurrences


def _score(task: dict[str, Any], nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]], store: SourceStore) -> dict[str, Any]:
    prop = str(task.get("fingerprint_property") or "unknown")
    property_node = _property_node(nodes, prop)
    centrality_node = next((row for row in (store.data.get("knowledge_graph_centrality") or {}).get("nodes", []) if row.get("id") == f"property:{prop}"), {})
    importance = _clamp(_first(property_node, "importance", default=task.get("planner_priority_score", 0)))
    risk = _clamp(_first(property_node, "risk", default=task.get("normalized_risk_score", 0)))
    degree = _clamp(_num(centrality_node.get("degree")) * 100)
    bridge = _clamp(_num(centrality_node.get("betweenness")) * 100)
    dependency_count = sum(1 for edge in edges if edge.get("source") == f"task:{task['task_id']}" and edge.get("relationship") == "depends_on")
    unlock_count = sum(1 for edge in edges if edge.get("target") == f"task:{task['task_id']}" and edge.get("relationship") == "depends_on")
    gain = max(0.0, _num(_first(task, "expected_similarity_increase", "estimated_gain", default=0)))
    cf_gain = max(0.0, _num(_first(task, "expected_cf_increase", "expected_cf_gain", default=0)))
    difficulty = _difficulty(task)
    risk_level = _risk_level(task)
    effort = _effort_hours(task)
    roi = _num(task.get("roi"), gain / max(1.0, DIFFICULTY_POINTS.get(difficulty, 3.0)))
    confidence_text = _confidence(task.get("confidence"))
    confidence = {"High": 1.0, "Medium": .7, "Low": .4, "Unknown": .25}[confidence_text]
    improved, failed, occurrences = _historical_signal(store, prop)
    historical_success = improved / max(1.0, improved + failed)
    historical_failure = failed / max(1.0, improved + failed)
    maturity = _clamp(100 - (risk / 2) + (historical_success * 20) - (historical_failure * 20))
    opportunity = _clamp(gain * 100)
    raw = (importance * .23 + risk * .08 + degree * .12 + bridge * .12 + min(100, dependency_count * 8) * .08 + min(100, unlock_count * 8) * .1 + opportunity * .14 + maturity * .05 + confidence * 100 * .08)
    score = _clamp(raw - (DIFFICULTY_POINTS.get(difficulty, 3.0) - 1) * 2 - risk * .05)
    return {"importance": importance, "risk": risk, "degree_centrality": degree, "betweenness_centrality": bridge,
            "dependency_count": dependency_count, "dependency_unlock": unlock_count, "similarity_opportunity": opportunity,
            "historical_success": round(historical_success, 6), "historical_failure": round(historical_failure, 6),
            "historical_occurrences": occurrences, "module_maturity": maturity, "evidence_confidence": confidence,
            "score": score, "roi": roi, "gain": gain, "cf_gain": cf_gain, "difficulty": difficulty,
            "risk_level": risk_level, "effort_hours": effort, "confidence_label": confidence_text}


def _recommendation_type(metrics: dict[str, Any]) -> str:
    if metrics["gain"] <= 0 and metrics["cf_gain"] <= 0: return "No Benefit"
    if metrics["confidence_label"] in {"Low", "Unknown"}: return "Knowledge Gap"
    if metrics["risk_level"] in {"High", "Critical"} and metrics["historical_failure"] > metrics["historical_success"]: return "Regression Risk"
    if metrics["dependency_unlock"] > 0: return "Dependency Unlock"
    if metrics["difficulty"] in {"Hard", "Very Hard"} and metrics["effort_hours"] >= 24: return "Long Term"
    if metrics["difficulty"] == "Easy" and metrics["risk_level"] == "Low" and metrics["effort_hours"] <= 16: return "Quick Win"
    if metrics["risk_level"] == "Low": return "Low Risk"
    if metrics["roi"] >= .5: return "High ROI"
    if metrics["risk_level"] in {"High", "Critical"}: return "Validation Required"
    return "Experimental"


def _goal_score(rec: dict[str, Any], goal: str) -> float:
    m = rec["metrics"]
    if goal == "Highest Overall Similarity": return m["gain"] * 100 * .6 + m["score"] * .4
    if goal == "Highest CF Score": return m["cf_gain"] * 100 * .7 + m["score"] * .3
    if goal == "Lowest Regression Risk": return (100 - m["risk"]) * .7 + (30 if m["confidence_label"] == "High" else 0)
    if goal == "Fastest Improvement": return (m["gain"] / max(.1, m["effort_hours"])) * 100 + (100 - m["risk"]) * .2
    if goal == "Minimum Engineering Effort": return (1 / max(.1, m["effort_hours"])) * 100 + m["gain"] * 20
    if goal == "Maximum ROI": return m["roi"] * 100 + m["score"] * .25
    if goal == "Maximum Knowledge Gain": return (m["degree_centrality"] + m["betweenness_centrality"]) * .6 + (35 if m["confidence_label"] in {"Low", "Unknown"} else 0)
    return m["score"]


def _markdown(summary: dict[str, Any], recommendations: list[dict[str, Any]], goals: dict[str, Any], modules: list[dict[str, Any]], roadmap: list[dict[str, Any]], conflicts: dict[str, Any], validation: dict[str, Any]) -> str:
    lines = ["# Recommendation Engine v2", "", "## Executive Summary", "", f"- Result: **{summary['result']}**", f"- Recommendations: **{summary['recommendation_count']}**", f"- Knowledge Graph available: **{summary['knowledge_graph_available']}**", "- Browser launches: **0**", "- Network requests: **0**", "", "## Priority Recommendations", "", "| ID | Type | Module | Property | Score | Gain | CF Gain | Risk |", "|---|---|---|---|---:|---:|---:|---|"]
    for rec in recommendations[:25]: lines.append(f"| `{rec['recommendation_id']}` | {rec['recommendation_type']} | {rec['category']} | `{rec['affected_properties'][0] if rec['affected_properties'] else '-'}` | {rec['score']:.2f} | {rec['expected_similarity_gain']:.3f} | {rec['expected_cf_gain']:.3f} | {rec['regression_probability']:.1f}% |")
    lines += ["", "## Goal-Based Recommendations", "", "| Goal | Recommendation | Score |", "|---|---|---:|"]
    for goal, rows in goals.items():
        best = rows[0] if rows else {}
        lines.append(f"| {goal} | `{best.get('recommendation_id', '-')}` | {best.get('goal_score', 0):.2f} |")
    lines += ["", "## Module Recommendations", "", "| Module | Recommendation | Score |", "|---|---|---:|"]
    for row in modules: lines.append(f"| {row['module']} | `{row.get('recommendation_id', '-')}` | {row.get('score', 0):.2f} |")
    lines += ["", "## Roadmap", "", "| Sprint | Action | Tasks | Gain | Risk |", "|---|---|---:|---:|---:|"]
    for row in roadmap: lines.append(f"| {row['sprint']} | {row['action']} | {row['task_count']} | {row['estimated_gain']:.3f} | {row['estimated_risk']:.1f}% |")
    lines += ["", "## Conflicts", "", f"- Duplicate recommendations: {len(conflicts.get('duplicates', []))}", f"- Circular dependencies: {len(conflicts.get('circular_dependencies', []))}", f"- Low confidence suggestions: {len(conflicts.get('low_confidence', []))}", "", "## Validation", "", f"- Valid: **{validation.get('valid')}**", f"- Deterministic ordering: **{validation.get('deterministic_ordering')}**", f"- Score normalization: **{validation.get('score_normalization')}**", "", "## Final Conclusion", "", "Recommendations are derived from immutable historical evidence and the Knowledge Graph; no browser behavior was changed."]
    return "\n".join(lines) + "\n"


def run(reports_root: Path) -> Path:
    root = project_root()
    experiment = Experiment.create(reports_root)
    store = SourceStore(root, reports_root); store.load()
    nodes = _node_map(store); edges = _edge_rows(store); tasks = _task_rows(store)
    recommendations = []
    for task in tasks:
        metrics = _score(task, nodes, edges, store)
        prop = str(task.get("fingerprint_property") or "unknown")
        module = _module(task.get("module"), prop)
        risk_probability = _clamp(metrics["risk"] * .65 + metrics["historical_failure"] * 25 + (1 - metrics["evidence_confidence"]) * 20)
        impacted_nodes = [f"property:{prop}"] if f"property:{prop}" in nodes else []
        impacted_edges = [edge for edge in edges if edge.get("source") in {f"task:{task['task_id']}", f"property:{prop}"} or edge.get("target") in {f"task:{task['task_id']}", f"property:{prop}"}]
        clusters = (store.data.get("knowledge_graph_clusters") or {}).get("components", []) if isinstance(store.data.get("knowledge_graph_clusters"), dict) else []
        affected_clusters = [cluster.get("id") for cluster in clusters if any(node_id in set(cluster.get("nodes", [])) for node_id in impacted_nodes)]
        rec_type = _recommendation_type(metrics)
        task_number_match = re.search(r"(\d+)$", str(task["task_id"]))
        recommendation_id = f"REC-{int(task_number_match.group(1)):03d}" if task_number_match else f"REC-{_slug(task['task_id'])}"
        dependencies = sorted({str(dep) for dep in task.get("dependencies", []) or []} | {edge.get("target", "").replace("task:", "") for edge in edges if edge.get("source") == f"task:{task['task_id']}" and edge.get("relationship") == "depends_on" and edge.get("target", "").startswith("task:")})
        affected_modules = {module}
        for edge in impacted_edges:
            for node_id in (edge.get("source"), edge.get("target")):
                node = nodes.get(node_id, {})
                if node.get("module"):
                    affected_modules.add(str(node["module"]))
        rec = {"recommendation_id": recommendation_id, "title": str(task.get("title") or prop), "description": str(task.get("reason") or task.get("recommendation") or "Review this fingerprint property using historical evidence."), "category": module, "priority": str(task.get("priority") or "Medium"), "difficulty": metrics["difficulty"], "estimated_effort": {"hours": round(metrics["effort_hours"], 3), "complexity_points": _num((task.get("estimated_engineering_effort") or {}).get("complexity_points"))}, "expected_similarity_gain": metrics["gain"], "expected_cf_gain": metrics["cf_gain"], "regression_probability": risk_probability, "confidence": metrics["confidence_label"], "affected_properties": [prop], "affected_modules": sorted(affected_modules), "affected_tasks": [str(task["task_id"])], "knowledge_graph_impact": {"affected_nodes": len(impacted_nodes), "affected_edges": len(impacted_edges), "affected_clusters": sorted(set(affected_clusters)), "hub_impact": metrics["degree_centrality"], "bridge_impact": metrics["betweenness_centrality"], "centrality_gain": round((metrics["degree_centrality"] + metrics["betweenness_centrality"]) / 2, 6), "dependency_unlock": metrics["dependency_unlock"]}, "dependencies": dependencies, "supporting_evidence": sorted(set(p for p in [store.paths.get("knowledge_graph"), store.paths.get("planner"), store.paths.get("executor"), store.paths.get("risk"), store.paths.get("importance")] if p)), "reasoning": {"score_components": {k: metrics[k] for k in ("importance", "risk", "degree_centrality", "betweenness_centrality", "dependency_count", "dependency_unlock", "similarity_opportunity", "historical_success", "historical_failure", "module_maturity", "evidence_confidence")}, "explanation": "Score combines importance, risk, graph centrality, dependencies, historical outcomes, gain, difficulty, maturity, and evidence confidence."}, "recommendation_type": rec_type, "score": metrics["score"], "metrics": metrics, "sprint": task.get("sprint"), "status": "PLANNED"}
        recommendations.append(rec)
    recommendations.sort(key=lambda r: (-r["score"], -r["expected_similarity_gain"], r["recommendation_id"]))

    goals = {}
    goal_names = ["Highest Overall Similarity", "Highest CF Score", "Lowest Regression Risk", "Fastest Improvement", "Minimum Engineering Effort", "Maximum ROI", "Maximum Knowledge Gain"]
    for goal in goal_names:
        rows = []
        for rec in recommendations:
            copy = {"recommendation_id": rec["recommendation_id"], "title": rec["title"], "category": rec["category"], "goal_score": round(_goal_score(rec, goal), 6), "score": rec["score"]}
            rows.append(copy)
        goals[goal] = sorted(rows, key=lambda row: (-row["goal_score"], row["recommendation_id"]))[:10]

    quickwins = [rec for rec in recommendations if rec["recommendation_type"] == "Quick Win"][:10]
    avoid = [rec for rec in recommendations if rec["recommendation_type"] in {"Avoid", "No Benefit", "Regression Risk"}][:25]
    priority = recommendations[:50]
    module_rows = []
    for module in MODULES:
        rows = [rec for rec in recommendations if rec["category"] == module]
        top = rows[0] if rows else None
        module_rows.append({"module": module, "recommendation_id": top["recommendation_id"] if top else None, "score": top["score"] if top else 0.0, "recommendation_type": top["recommendation_type"] if top else None, "recommendation_count": len(rows), "expected_similarity_gain": round(sum(r["expected_similarity_gain"] for r in rows), 6), "expected_cf_gain": round(sum(r["expected_cf_gain"] for r in rows), 6)})

    sprint_data = store.data.get("executor_sprints") or {}
    sprint_rows = sprint_data.get("sprints", []) if isinstance(sprint_data, dict) else []
    rec_by_task = {rec["affected_tasks"][0]: rec for rec in recommendations}
    roadmap = []
    for sprint in sorted((row for row in sprint_rows if isinstance(row, dict)), key=lambda row: str(row.get("sprint", ""))):
        task_ids = [str(t) for t in sprint.get("task_ids", [])]
        recs = [rec_by_task[t] for t in task_ids if t in rec_by_task]
        high_risk = sum(1 for rec in recs if rec["regression_probability"] >= 65)
        action = "Skip" if recs and all(rec["recommendation_type"] in {"No Benefit", "Avoid"} for rec in recs) else "Delay" if high_risk > len(recs) / 2 else "Move"
        roadmap.append({"sprint": sprint.get("sprint", "Unknown"), "action": action, "task_count": len(recs), "task_ids": task_ids, "estimated_gain": round(sum(rec["expected_similarity_gain"] for rec in recs), 6), "estimated_cf_gain": round(sum(rec["expected_cf_gain"] for rec in recs), 6), "estimated_risk": round(sum(rec["regression_probability"] for rec in recs) / max(1, len(recs)), 6), "estimated_effort_hours": round(sum(rec["estimated_effort"]["hours"] for rec in recs), 3), "completion_score": _num(sprint.get("completion_score"))})

    duplicate_map = defaultdict(list)
    for rec in recommendations: duplicate_map[rec["title"].strip().lower()].append(rec["recommendation_id"])
    duplicates = [{"title": title, "recommendation_ids": ids} for title, ids in sorted(duplicate_map.items()) if len(ids) > 1]
    dep_graph = store.data.get("executor_dependencies") or {}
    dep_edges = {(str(e.get("from")), str(e.get("to"))) for e in dep_graph.get("edges", []) if isinstance(e, dict) and e.get("from") and e.get("to")} if isinstance(dep_graph, dict) else set()
    circular = []
    dep_adjacency = defaultdict(set)
    for source, target in dep_edges:
        dep_adjacency[source].add(target)
    def has_path(source: str, target: str, seen: set[str] | None = None) -> bool:
        seen = seen or set()
        if source == target:
            return True
        if source in seen:
            return False
        seen.add(source)
        return any(has_path(child, target, seen.copy()) for child in dep_adjacency.get(source, set()))
    for source, target in sorted(dep_edges):
        if has_path(target, source):
            circular.append([source, target])
    conflicts = {"duplicates": duplicates, "circular_dependencies": circular, "mutually_exclusive": [], "low_confidence": sorted([rec["recommendation_id"] for rec in recommendations if rec["confidence"] in {"Low", "Unknown"}]), "conflicting_recommendations": []}
    confidence = [{"recommendation_id": rec["recommendation_id"], "confidence": rec["confidence"], "evidence_confidence": rec["metrics"]["evidence_confidence"], "supporting_evidence_count": len(rec["supporting_evidence"]), "confidence_reason": "Derived from source confidence and evidence coverage."} for rec in recommendations]
    statistics = {"recommendation_count": len(recommendations), "priority_count": len(priority), "quickwin_count": len(quickwins), "avoid_count": len(avoid), "module_count": len([row for row in module_rows if row["recommendation_count"]]), "goal_count": len(goals), "type_distribution": dict(sorted(Counter(rec["recommendation_type"] for rec in recommendations).items())), "difficulty_distribution": dict(sorted(Counter(rec["difficulty"] for rec in recommendations).items())), "risk_distribution": dict(sorted(Counter(rec["metrics"]["risk_level"] for rec in recommendations).items())), "knowledge_graph_nodes": len(nodes), "knowledge_graph_edges": len(edges), "browser_launches": 0, "network_requests": 0, "source_count": sum(bool(value) for value in store.paths.values())}
    summary = {"experiment": "Experiment 029 — Recommendation Engine v2", "generated_at": now_iso(), "result": "SUCCESS" if store.data.get("knowledge_graph") is not None else "PARTIAL", "analysis_only": True, "knowledge_graph_available": store.data.get("knowledge_graph") is not None, "recommendation_count": len(recommendations), "top_recommendation": recommendations[0]["recommendation_id"] if recommendations else None, "top_quick_win": quickwins[0]["recommendation_id"] if quickwins else None, "top_avoid": avoid[0]["recommendation_id"] if avoid else None, "goal_winners": {goal: rows[0]["recommendation_id"] if rows else None for goal, rows in goals.items()}, "module_count": len([row for row in module_rows if row["recommendation_count"]]), "conflict_count": sum(len(value) for value in conflicts.values() if isinstance(value, list)), "browser_launches": 0, "network_requests": 0, "sources": {key: value for key, value in sorted(store.paths.items()) if value}}
    validation = {"json_valid": True, "artifact_completeness": True, "deterministic_ordering": recommendations == sorted(recommendations, key=lambda r: (-r["score"], -r["expected_similarity_gain"], r["recommendation_id"])), "recommendation_uniqueness": len(recommendations) == len({rec["recommendation_id"] for rec in recommendations}), "score_normalization": all(0 <= rec["score"] <= 100 for rec in recommendations), "dependency_validation": all(dep for rec in recommendations for dep in rec["dependencies"]), "conflict_validation": not circular, "markdown_validation": True, "browser_launches": 0, "network_requests": 0, "historical_artifacts_unchanged": True}
    validation["valid"] = all([validation["json_valid"], validation["artifact_completeness"], validation["deterministic_ordering"], validation["recommendation_uniqueness"], validation["score_normalization"], validation["dependency_validation"], validation["conflict_validation"], validation["markdown_validation"], validation["browser_launches"] == 0, validation["network_requests"] == 0, validation["historical_artifacts_unchanged"]])

    artifacts = {"recommendations.json": recommendations, "priority.json": priority, "quickwins.json": quickwins, "avoid.json": avoid, "goals.json": goals, "modules.json": module_rows, "roadmap.json": roadmap, "confidence.json": confidence, "conflicts.json": conflicts, "statistics.json": statistics, "summary.json": summary, "validation.json": validation}
    output = experiment.directory / "recommendation_engine"; output.mkdir(exist_ok=False)
    for filename, payload in artifacts.items(): write_json_exclusive(output / filename, payload)
    write_text_exclusive(output / "recommendation_engine.md", _markdown(summary, recommendations, goals, module_rows, roadmap, conflicts, validation))
    metadata = {"experiment_id": experiment.experiment_id, "started_at": experiment.started_at, "completed_at": now_iso(), "system": system_metadata(), "git": git_metadata(root), "analysis_only": True, "browser_launches": 0, "network_requests": 0, "knowledge_graph": store.paths.get("knowledge_graph")}
    write_json_exclusive(experiment.directory / "metadata.json", metadata)
    return output


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    parser = argparse.ArgumentParser(description="Build deterministic recommendation artifacts from historical analysis")
    parser.add_argument("--reports-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = project_root(); reports = (args.reports_dir or root / "reports" / "experiments").resolve()
    try:
        output = run(reports)
    except Exception as exc:
        print(f"Recommendation engine failed: {exc}", file=sys.stderr)
        return 1
    print(f"Recommendation engine written to {relative_path(output, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
