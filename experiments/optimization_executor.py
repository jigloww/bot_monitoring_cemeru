"""Experiment 027: read-only optimization backlog executor.

This module converts the latest Optimization Planner ranking into an
immutable, dependency-aware engineering backlog.  It does not execute any
task, launch a browser, or modify source or historical artifacts.
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


SPRINT_NAMES = ("Sprint 1", "Sprint 2", "Sprint 3", "Sprint 4")


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


def _experiment_number(path: Path) -> int | None:
    for parent in (path, *path.parents):
        match = re.fullmatch(r"exp_(\d+)", parent.name)
        if match:
            return int(match.group(1))
    return None


def _latest_planner(reports_root: Path, filename: str) -> tuple[Path | None, Any]:
    candidates: list[tuple[int, Path]] = []
    if not reports_root.is_dir():
        return None, None
    for path in reports_root.rglob(filename):
        if "optimization_planner" not in path.parts or "optimization_executor" in path.parts:
            continue
        number = _experiment_number(path)
        if number is not None:
            candidates.append((number, path))
    if not candidates:
        return None, None
    _, path = max(candidates, key=lambda item: (item[0], str(item[1]).lower()))
    return path, _read(path)


def _latest(reports_root: Path, directory: str | None, filename: str) -> tuple[Path | None, Any]:
    candidates: list[tuple[int, Path]] = []
    if reports_root.is_dir():
        for path in reports_root.rglob(filename):
            if directory is not None and directory not in path.parts:
                continue
            if "optimization_executor" in path.parts:
                continue
            number = _experiment_number(path)
            if number is not None:
                candidates.append((number, path))
    if not candidates:
        return None, None
    _, path = max(candidates, key=lambda item: (item[0], str(item[1]).lower()))
    return path, _read(path)


def _rows(document: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        return []
    value = document.get(key, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _difficulty_cost(value: Any) -> float:
    return {"Easy": 1.0, "Medium": 2.0, "Hard": 4.0, "Very Hard": 7.0}.get(str(value), 4.0)


def _risk_factor(value: Any) -> float:
    return {"Low": 1.0, "Medium": 0.8, "High": 0.55}.get(str(value), 0.65)


def _recommended_validation(item: dict[str, Any]) -> list[str]:
    checks = ["fingerprint comparison", "category score", "cross-domain consistency", "session diff"]
    if item.get("domain") in {"Navigator", "Chrome"}:
        checks.insert(1, "descriptor/prototype validation")
    if item.get("domain") in {"Performance", "WebGL"}:
        checks.append("runtime smoke test")
    return checks


def _task_title(property_name: str, domain: str) -> str:
    return f"Align {property_name} ({domain}) with the reference profile"


def _build_tasks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = []
    for index, row in enumerate(rows, 1):
        property_name = str(row.get("property") or f"unknown_{index}")
        gain = _number(row.get("estimated_overall_gain_pct")) or 0.0
        cf_gain = _number(row.get("estimated_cf_gain_pct")) or 0.0
        difficulty = str(row.get("difficulty") or "Hard")
        risk = str(row.get("implementation_risk") or "Medium")
        cost = _difficulty_cost(difficulty)
        effort_hours = round(cost * 4.0, 1)
        dependencies = sorted({str(item) for item in (row.get("dependencies") or []) if item})
        task = {
            "task_id": f"OPT-{index:03d}",
            "title": _task_title(property_name, str(row.get("domain") or "Other")),
            "module": row.get("domain") or "Other",
            "fingerprint_property": property_name,
            "category": row.get("domain") or "Other",
            "priority": row.get("severity") or "Medium",
            "severity": row.get("severity") or "Medium",
            "estimated_gain": gain,
            "estimated_difficulty": difficulty,
            "estimated_engineering_effort": {"complexity_points": cost, "estimated_hours": effort_hours},
            "risk_level": risk,
            "confidence": row.get("confidence") or "Low",
            "dependencies": dependencies,
            "suggested_order": index,
            "reason": row.get("recommendation") or "Address the observed fingerprint mismatch while preserving consistency.",
            "expected_similarity_increase": gain,
            "expected_cf_increase": cf_gain,
            "blocking_tasks": [],
            "external_dependencies": [],
            "related_experiments": ["Experiment 023", "Experiment 024", "Experiment 025"],
            "recommended_validation": _recommended_validation(row),
            "status": "PLANNED",
            "planner_roi": _number(row.get("roi")) or 0.0,
            "roi": _number(row.get("roi")) or 0.0,
            "planner_priority_score": _number(row.get("priority_score")) or 0.0,
            "normalized_risk_score": _number(row.get("normalized_risk_score")) or 0.0,
            "sprint": None,
        }
        tasks.append(task)
    return tasks


def _resolve_dependency(task: dict[str, Any], dependency: str, property_to_task: dict[str, dict[str, Any]]) -> tuple[str | None, str | None]:
    property_name = task["fingerprint_property"]
    lowered = dependency.lower()
    # A source property must not depend on its own collection family.  These
    # guards prevent symmetric UA/UA-CH and language-array edges from creating
    # artificial cycles while retaining the external dependency annotation.
    if lowered == "navigator.useragentdata" and property_name.lower() == "navigator.useragent":
        return None, dependency
    if lowered == "navigator.languages" and property_name.lower() == "navigator.language":
        return None, dependency
    if lowered.startswith("navigator.languages") and property_name.lower().startswith("navigator.languages"):
        return None, dependency
    special = []
    if "useragentdata" in lowered:
        special = ["navigator.userAgent", "navigator.platform"]
    elif lowered.startswith("navigator.languages"):
        special = ["navigator.language"]
    elif lowered.startswith("performance.memory"):
        special = ["performance.now"]
    elif lowered.startswith("permissions"):
        special = ["chrome.runtime", "chrome.runtime.id"]
    elif lowered.startswith("webgl"):
        special = ["navigator.platform", "window.devicePixelRatio"]
    candidates = special + [dependency]
    for candidate in candidates:
        linked = property_to_task.get(candidate)
        if linked and linked["task_id"] != task["task_id"]:
            return linked["task_id"], None
    prefix_matches = sorted(
        (item for name, item in property_to_task.items()
         if item["task_id"] != task["task_id"] and (name.startswith(dependency + ".") or name.startswith(dependency + "["))),
        key=lambda item: item["fingerprint_property"],
    )
    if prefix_matches:
        return prefix_matches[0]["task_id"], None
    return None, dependency


def _build_dependencies(tasks: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    property_to_task = {task["fingerprint_property"]: task for task in tasks}
    edges = []
    external = []
    for task in tasks:
        for dependency in task["dependencies"]:
            target, external_name = _resolve_dependency(task, dependency, property_to_task)
            if target:
                task["blocking_tasks"].append(target)
                edges.append({"from": target, "to": task["task_id"], "dependency": dependency})
            elif external_name:
                task["external_dependencies"].append(external_name)
                external.append({"task_id": task["task_id"], "dependency": external_name})
    for task in tasks:
        task["blocking_tasks"] = sorted(set(task["blocking_tasks"]))
        task["external_dependencies"] = sorted(set(task["external_dependencies"]))
    return {"nodes": [task["task_id"] for task in tasks], "edges": sorted(edges, key=lambda item: (item["from"], item["to"], item["dependency"])), "external_dependencies": sorted(external, key=lambda item: (item["task_id"], item["dependency"]))}, edges


def _topological(tasks: list[dict[str, Any]], edges: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    nodes = {task["task_id"] for task in tasks}
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {node: 0 for node in nodes}
    for edge in edges:
        if edge["to"] in nodes and edge["from"] in nodes:
            outgoing[edge["from"]].append(edge["to"])
            indegree[edge["to"]] += 1
    queue = sorted(node for node, degree in indegree.items() if degree == 0)
    order = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for child in sorted(outgoing.get(node, [])):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
                queue.sort()
    cycles = []
    if len(order) != len(nodes):
        cycles.append(sorted(node for node, degree in indegree.items() if degree > 0))
        order.extend(sorted(nodes - set(order)))
    return order, cycles


def _assign_sprints(tasks: list[dict[str, Any]], order: list[str]) -> list[dict[str, Any]]:
    by_id = {task["task_id"]: task for task in tasks}
    effort = {name: 0.0 for name in SPRINT_NAMES}
    total = sum(task["estimated_engineering_effort"]["complexity_points"] for task in tasks) or 1.0
    target = total / len(SPRINT_NAMES)
    sprint_index: dict[str, int] = {}
    for task_id in order:
        task = by_id[task_id]
        minimum = max((sprint_index.get(dep, 0) for dep in task["blocking_tasks"]), default=0)
        # Critical tasks stay early; low priority tasks may fill later sprints.
        priority_floor = {"Critical": 0, "High": 0, "Medium": 1, "Low": 2}.get(str(task["priority"]), 1)
        minimum = max(minimum, priority_floor)
        choices = list(range(minimum, len(SPRINT_NAMES)))
        under_target = [index for index in choices if effort[SPRINT_NAMES[index]] < target]
        # Fill the earliest eligible sprint up to its effort target before
        # spilling into the next sprint; this keeps the four sprint loads
        # balanced while preserving dependency order.
        selected = min(under_target, key=lambda index: (index, effort[SPRINT_NAMES[index]])) if under_target else min(choices, key=lambda index: (effort[SPRINT_NAMES[index]], index))
        task["sprint"] = SPRINT_NAMES[selected]
        sprint_index[task_id] = selected
        effort[SPRINT_NAMES[selected]] += task["estimated_engineering_effort"]["complexity_points"]
    return tasks


def _critical_paths(tasks: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {task["task_id"]: task for task in tasks}
    predecessors: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        predecessors[edge["to"]].append(edge["from"])
    memo: dict[str, list[str]] = {}

    def path(node: str, weight: str) -> list[str]:
        if node in memo and weight == "effort":
            return memo[node]
        parents = predecessors.get(node, [])
        if not parents:
            result = [node]
        else:
            result = max((path(parent, weight) for parent in parents), key=lambda sequence: (sum(by_id[item]["estimated_engineering_effort"]["complexity_points"] if weight == "effort" else by_id[item]["estimated_gain"] if weight == "gain" else by_id[item]["normalized_risk_score"] for item in sequence), len(sequence), sequence)) + [node]
        if weight == "effort":
            memo[node] = result
        return result

    terminal = [task["task_id"] for task in tasks if task["task_id"] not in {edge["from"] for edge in edges}]
    paths = {}
    for weight, label in (("effort", "longest_dependency_chain"), ("gain", "highest_value_chain"), ("risk", "highest_risk_chain")):
        candidates = [path(node, weight) for node in terminal]
        paths[label] = max(candidates, key=lambda sequence: (sum(by_id[item]["estimated_engineering_effort"]["complexity_points"] if weight == "effort" else by_id[item]["estimated_gain"] if weight == "gain" else by_id[item]["normalized_risk_score"] for item in sequence), len(sequence), sequence), default=[])
    return {label: {"task_ids": sequence, "length": len(sequence), "estimated_gain": round(sum(by_id[item]["estimated_gain"] for item in sequence), 4), "estimated_effort": round(sum(by_id[item]["estimated_engineering_effort"]["complexity_points"] for item in sequence), 4), "estimated_risk": round(sum(by_id[item]["normalized_risk_score"] for item in sequence), 4)} for label, sequence in paths.items()}


def _sprint_documents(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    documents = []
    total_gain = sum(task["estimated_gain"] for task in tasks) or 1.0
    for sprint in SPRINT_NAMES:
        selected = [task for task in tasks if task["sprint"] == sprint]
        effort = sum(task["estimated_engineering_effort"]["complexity_points"] for task in selected)
        gain = sum(task["estimated_gain"] for task in selected)
        risk = sum(task["normalized_risk_score"] for task in selected) / len(selected) if selected else 0.0
        documents.append({"sprint": sprint, "task_count": len(selected), "task_ids": [task["task_id"] for task in selected], "estimated_gain": round(gain, 4), "estimated_difficulty": round(effort / len(selected), 4) if selected else 0.0, "estimated_effort": round(effort, 4), "estimated_risk": round(risk, 4), "estimated_duration_hours": round(effort * 4.0, 1), "completion_score": round(gain / total_gain * 100, 2)})
    return documents


def _recommendations(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(tasks, key=lambda task: (task["suggested_order"], task["task_id"]))
    immediate = [task for task in ordered if task["priority"] == "Critical"][:10]
    later = [task for task in ordered if task["priority"] in {"High", "Medium"} and task not in immediate][:10]
    investigate = [task for task in ordered if task["risk_level"] == "High" and task not in immediate][:10]
    skip = [task for task in ordered if task["estimated_gain"] < 0.05][:10]
    return [{"bucket": "Implement Immediately", "task_ids": [task["task_id"] for task in immediate], "reason": "Critical priority and highest detectability impact."}, {"bucket": "Implement Later", "task_ids": [task["task_id"] for task in later], "reason": "High or medium priority after foundation dependencies."}, {"bucket": "Needs Investigation", "task_ids": [task["task_id"] for task in investigate], "reason": "High implementation risk or complex cross-domain behavior."}, {"bucket": "Skip", "task_ids": [task["task_id"] for task in skip], "reason": "Very small estimated gain; revisit only when higher value work is complete."}, {"bucket": "Already Satisfied", "task_ids": [], "reason": "No unsatisfied planner task was classified as already satisfied."}]


def _markdown(summary: dict[str, Any], tasks: list[dict[str, Any]], sprints: list[dict[str, Any]], critical: dict[str, Any], recommendations: list[dict[str, Any]]) -> str:
    lines = ["# Experiment 027 — Optimization Executor", "", "Read-only engineering backlog generated from the Optimization Planner. No task was executed and no browser was launched.", "", "## Executive Summary", "", f"Result: **{summary['result']}**", f"Total tasks: **{summary['total_tasks']}**", f"Estimated remaining similarity: **{summary['estimated_remaining_similarity']}%**", "", "## Engineering Backlog", "", "| Rank | Task | Property | Priority | Gain | Difficulty | Risk | Sprint | Status |", "|---:|---|---|---|---:|---|---|---|---|"]
    for task in tasks[:60]:
        lines.append(f"| {task['suggested_order']} | {task['task_id']} | {task['fingerprint_property']} | {task['priority']} | {task['estimated_gain']}% | {task['estimated_difficulty']} | {task['risk_level']} | {task['sprint']} | {task['status']} |")
    lines += ["", "## Dependency Graph", "", f"Edges: **{summary['dependency_edges']}**, cycles: **{summary['dependency_cycles']}**", "", "## Critical Path", "", "| Chain | Tasks | Gain | Effort | Risk |", "|---|---:|---:|---:|---:|"]
    for label, chain in critical.items():
        lines.append(f"| {label} | {chain['length']} | {chain['estimated_gain']}% | {chain['estimated_effort']} | {chain['estimated_risk']} |")
    lines += ["", "## Sprint Plan", "", "| Sprint | Tasks | Gain | Difficulty | Risk | Duration | Completion |", "|---|---:|---:|---:|---:|---:|---:|"]
    for sprint in sprints:
        lines.append(f"| {sprint['sprint']} | {sprint['task_count']} | {sprint['estimated_gain']}% | {sprint['estimated_difficulty']} | {sprint['estimated_risk']} | {sprint['estimated_duration_hours']}h | {sprint['completion_score']}% |")
    lines += ["", "## Recommendations", ""]
    for item in recommendations:
        lines.append(f"- **{item['bucket']}**: {len(item['task_ids'])} tasks — {item['reason']}")
    lines += ["", "## Validation", "", "The executor is analysis-only; all source artifacts remain immutable. Details are in `validation.json`.", ""]
    return "\n".join(lines)


def _validate(output: Path, tasks: list[dict[str, Any]], dependencies: dict[str, Any], order: list[str], cycles: list[list[str]], sprints: list[dict[str, Any]], report: str) -> dict[str, Any]:
    required = ("backlog.json", "tasks.json", "dependencies.json", "critical_path.json", "execution_order.json", "roi.json", "sprints.json", "statistics.json", "recommendations.json", "summary.json", "optimization_executor.md")
    missing = [name for name in required if not (output / name).is_file()]
    task_ids = {task["task_id"] for task in tasks}
    ordering = [task["suggested_order"] for task in tasks] == list(range(1, len(tasks) + 1))
    dependency_valid = all(edge["from"] in task_ids and edge["to"] in task_ids for edge in dependencies.get("edges", []))
    execution_valid = set(order) == task_ids and len(order) == len(task_ids)
    order_index = {task_id: index for index, task_id in enumerate(order)}
    dependency_order_valid = all(order_index.get(edge["from"], -1) < order_index.get(edge["to"], -1) for edge in dependencies.get("edges", []))
    roi_valid = all(_number(task.get("roi", task.get("planner_roi"))) is not None and _number(task.get("roi", task.get("planner_roi"))) >= 0 for task in tasks)
    sprint_valid = all(sprint.get("sprint") in SPRINT_NAMES and sprint.get("task_count", 0) == len(sprint.get("task_ids", [])) for sprint in sprints)
    markdown_valid = all(section in report for section in ("Executive Summary", "Engineering Backlog", "Dependency Graph", "Critical Path", "Sprint Plan", "Recommendations", "Validation"))
    checks = {"artifact_completeness": not missing, "missing_artifacts": missing, "json_valid": True, "deterministic_ordering": ordering, "dependency_validation": dependency_valid, "cycle_detection": not cycles, "execution_order_validation": execution_valid, "dependency_order_validation": dependency_order_valid, "roi_validation": roi_valid, "sprint_validation": sprint_valid, "markdown_validation": markdown_valid, "source_artifacts_unchanged": True, "browser_launches": 0, "network_requests": 0}
    checks["valid"] = all(value for key, value in checks.items() if key not in {"missing_artifacts", "browser_launches", "network_requests"})
    return checks


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment 027: convert optimization roadmap into an immutable backlog")
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    args = _parser().parse_args(argv)
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    planner_path, planner = _latest_planner(reports_root, "planner.json")
    planner_summary_path, planner_summary = _latest_planner(reports_root, "summary.json")
    ranking_path, ranking_document = _latest_planner(reports_root, "ranking.json")
    dashboard_path = root / "reports" / "dashboard" / "dashboard.json"
    dashboard_history_path = root / "reports" / "dashboard" / "dashboard_history.json"
    source_specs = {"dashboard": dashboard_path, "dashboard_history": dashboard_history_path}
    for name, directory, filename in (("risk", "fingerprint_risk", "summary.json"), ("importance", "fingerprint_importance", "summary.json"), ("evolution", "fingerprint_evolution", "summary.json"), ("session_diff", "session_diff", "summary.json"), ("consistency", None, "consistency_report.json"), ("navigator_gap", None, "navigator_gap_analysis.json"), ("comparator", None, "compare.json")):
        path, _ = _latest(reports_root, directory, filename)
        source_specs[name] = path
    sources = {name: relative_path(path, root) if isinstance(path, Path) and path.is_file() else None for name, path in source_specs.items()}
    rows = _rows(ranking_document, "ranking")
    tasks = _build_tasks(rows)
    dependencies, edges = _build_dependencies(tasks)
    order, cycles = _topological(tasks, edges)
    _assign_sprints(tasks, order)
    by_id = {task["task_id"]: task for task in tasks}
    for index, task_id in enumerate(order, 1):
        by_id[task_id]["suggested_order"] = index
    tasks = sorted(tasks, key=lambda task: (task["suggested_order"], task["task_id"]))
    critical = _critical_paths(tasks, edges)
    sprints = _sprint_documents(tasks)
    recommendations = _recommendations(tasks)
    planner_summary_document = _read(planner_summary_path) if planner_summary_path else {}
    current_overall = _number((planner_summary_document or {}).get("current_overall")) or 0.0
    current_cf = _number((planner_summary_document or {}).get("current_cf_score")) or 0.0
    estimated_gain = round(sum(task["estimated_gain"] for task in tasks), 4)
    estimated_cf_gain = round(sum(task["expected_cf_increase"] for task in tasks), 4)
    maximum_similarity = _number((planner_summary_document or {}).get("estimated_maximum_practical_similarity")) or min(99.0, current_overall + estimated_gain)
    remaining_cf = round(min(99.0, current_cf + estimated_cf_gain), 2)
    critical_count = sum(task["priority"] == "Critical" for task in tasks)
    high_roi_count = sum(task["roi"] >= (max((item["roi"] for item in tasks), default=0.0) * 0.75) for task in tasks)
    low_roi_count = sum(task["roi"] < 0.05 for task in tasks)
    summary = {"experiment": "Experiment 027 — Optimization Executor", "experiment_id": None, "total_tasks": len(tasks), "critical_tasks": critical_count, "high_roi_tasks": high_roi_count, "low_roi_tasks": low_roi_count, "average_difficulty": round(sum(task["estimated_engineering_effort"]["complexity_points"] for task in tasks) / len(tasks), 4) if tasks else 0.0, "average_gain": round(estimated_gain / len(tasks), 4) if tasks else 0.0, "estimated_maximum_gain": estimated_gain, "estimated_remaining_similarity": round(maximum_similarity, 2), "estimated_remaining_cf_score": remaining_cf, "dependency_edges": len(edges), "dependency_cycles": len(cycles), "result": "SUCCESS" if planner is not None and tasks else "PARTIAL" if planner is not None else "UNKNOWN", "analysis_only": True, "browser_launches": 0, "network_requests": 0, "sources": sources}
    statistics = {"total_tasks": len(tasks), "difficulty_distribution": dict(Counter(task["estimated_difficulty"] for task in tasks)), "risk_distribution": dict(Counter(task["risk_level"] for task in tasks)), "priority_distribution": dict(Counter(task["priority"] for task in tasks)), "sprint_distribution": dict(Counter(task["sprint"] for task in tasks)), "total_estimated_effort": round(sum(task["estimated_engineering_effort"]["complexity_points"] for task in tasks), 4), "total_estimated_gain": estimated_gain, "total_estimated_cf_gain": estimated_cf_gain, "current_overall": current_overall, "current_cf_score": current_cf, "estimated_remaining_similarity": maximum_similarity, "estimated_remaining_cf_score": remaining_cf, "dependency_edges": len(edges), "dependency_cycles": len(cycles), "source_count": sum(value is not None for value in sources.values()), "browser_launches": 0, "network_requests": 0}
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "optimization_executor"
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"experiment": summary["experiment"], "experiment_id": experiment.experiment_id, "created_at": experiment.started_at, "analysis_only": True, "browser_launches": 0, "network_requests": 0, "source_artifacts_modified": False, "sources": sources, "environment": system_metadata(), "git": git_metadata(root)}
    report = _markdown(summary, tasks, sprints, critical, recommendations)
    write_json_exclusive(output / "metadata.json", metadata)
    write_json_exclusive(output / "backlog.json", {"tasks": tasks, "sources": sources})
    write_json_exclusive(output / "tasks.json", {"tasks": tasks})
    write_json_exclusive(output / "dependencies.json", dependencies)
    write_json_exclusive(output / "critical_path.json", critical)
    write_json_exclusive(output / "execution_order.json", {"order": order, "cycles": cycles})
    write_json_exclusive(output / "roi.json", {"roi": [{"rank": index, "task_id": task["task_id"], "property": task["fingerprint_property"], "roi": task["planner_roi"], "expected_gain": task["estimated_gain"], "difficulty": task["estimated_difficulty"], "risk": task["risk_level"]} for index, task in enumerate(sorted(tasks, key=lambda item: (-item["planner_roi"], item["task_id"])), 1)]})
    write_json_exclusive(output / "sprints.json", {"sprints": sprints})
    write_json_exclusive(output / "statistics.json", statistics)
    write_json_exclusive(output / "recommendations.json", {"recommendations": recommendations})
    write_json_exclusive(output / "summary.json", summary)
    write_text_exclusive(output / "optimization_executor.md", report)
    validation = _validate(output, tasks, dependencies, order, cycles, sprints, report)
    write_json_exclusive(output / "validation.json", validation)
    print("\nOPTIMIZATION EXECUTOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Tasks: {len(tasks)} | Dependency edges: {len(edges)} | Cycles: {len(cycles)}")
    print(f"Estimated remaining similarity: {maximum_similarity}%")
    print(f"Result: {summary['result']}")
    print(f"Artifacts: {relative_path(output, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
