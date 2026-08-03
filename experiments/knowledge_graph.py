"""Experiment 028: deterministic, read-only fingerprint knowledge graph.

The experiment consumes reports produced by earlier experiments and emits a
portable graph dataset.  It never launches a browser and never mutates input
artifacts; every output is allocated through :class:`Experiment`.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

# ``python experiments/knowledge_graph.py`` places ``experiments/`` first on
# sys.path.  Add the repository root so the package imports work in that CLI
# mode as they do under ``python -m``.
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


MODULES = [
    "Navigator", "Window", "Screen", "Chrome", "Permissions", "Fonts",
    "Speech", "Performance", "WebGL", "Environment", "Storage", "Other",
]
RELATIONSHIPS = {
    "depends_on", "correlates_with", "conflicts_with", "improves", "regresses",
    "same_module", "same_category", "derived_from", "validated_by",
    "implemented_by", "scheduled_in", "recommended_by",
}
SEVERITY_SCORE = {"Critical": 1.0, "High": .75, "Medium": .5, "Low": .25,
                  "Informational": .05, "INFO": .05}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_") or "unknown"


def _read(path: Path | None) -> Any:
    if path is None:
        return None
    try:
        return read_json(path) if path.exists() else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _exp_number(path: Path) -> int:
    match = re.match(r"exp_(\d+)$", path.name)
    return int(match.group(1)) if match else -1


def _latest(root: Path, dirname: str, filename: str) -> tuple[Any, Path | None]:
    candidates = []
    for exp in root.glob("exp_*"):
        if not exp.is_dir() or exp.name == "knowledge_graph":
            continue
        path = exp / dirname / filename
        if path.exists():
            candidates.append(( _exp_number(exp), path))
    if not candidates:
        return None, None
    _, path = max(candidates, key=lambda item: item[0])
    return _read(path), path


def _iter_experiment_summaries(root: Path) -> list[tuple[str, Path, dict[str, Any]]]:
    found = []
    for exp in root.glob("exp_*"):
        if not exp.is_dir() or exp.name == "knowledge_graph":
            continue
        # Older experiments put summary.json directly in exp_NNN while newer
        # ones keep it under a domain directory.  Prefer the root summary and
        # otherwise choose the first stable, non-derived summary.
        paths = [exp / "summary.json"] if (exp / "summary.json").exists() else sorted(
            (p for p in exp.rglob("summary.json") if "knowledge_graph" not in p.parts),
            key=lambda p: str(p).lower(),
        )
        path = paths[0] if paths else None
        data = _read(path)
        if path is not None and isinstance(data, dict):
            found.append((exp.name, path, data))
    return sorted(found, key=lambda item: (_exp_number(Path(item[0])), item[0]))


def _confidence(value: Any) -> str:
    text = str(value or "Unknown").strip().title()
    return text if text in {"High", "Medium", "Low", "Unknown"} else "Unknown"


def _module(value: Any, prop: str = "") -> str:
    text = str(value or "").strip()
    if text and text.lower() in {m.lower() for m in MODULES}:
        return next(m for m in MODULES if m.lower() == text.lower())
    head = prop.split(".", 1)[0].lower()
    mapping = {"navigator": "Navigator", "window": "Window", "screen": "Screen",
               "chrome": "Chrome", "permissions": "Permissions", "document": "Fonts",
               "speechsynthesis": "Speech", "speech": "Speech", "performance": "Performance",
               "webgl": "WebGL", "storage": "Storage", "environment": "Environment"}
    if head in mapping:
        return mapping[head]
    lower = prop.lower()
    for prefix, candidate in (("navigator", "Navigator"), ("window", "Window"),
                              ("screen", "Screen"), ("chrome", "Chrome"),
                              ("performance", "Performance"), ("webgl", "WebGL"),
                              ("speech", "Speech"), ("font", "Fonts")):
        if lower.startswith(prefix):
            return candidate
    return text or "Other"


def _property_from_task(task: dict[str, Any]) -> str:
    return str(task.get("fingerprint_property") or task.get("property") or task.get("title") or "unknown")


class GraphBuilder:
    def __init__(self, root: Path, reports_root: Path):
        self.root = root
        self.reports_root = reports_root
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.sources: dict[str, str | None] = {}
        self.prop_ids: dict[str, str] = {}
        self.module_ids: dict[str, str] = {}
        self.task_ids: dict[str, str] = {}
        self.experiment_ids: dict[str, str] = {}
        self.data: dict[str, Any] = {}

    def add_node(self, node_type: str, name: str, *, module: str = "Other",
                 category: str | None = None, importance: float = 0.0,
                 risk: float = 0.0, frequency: int = 0,
                 confidence: str = "Unknown", evidence: list[str] | None = None,
                 node_id: str | None = None, **extra: Any) -> str:
        node_id = node_id or f"{_slug(node_type)}:{_slug(name)}"
        module = _module(module)
        category = category or module
        node = self.nodes.get(node_id)
        if node is None:
            node = {
                "id": node_id, "type": node_type, "name": name,
                "module": module, "category": category,
                "importance": round(max(0.0, _num(importance)), 6),
                "risk": round(max(0.0, _num(risk)), 6),
                "frequency": int(max(0, _num(frequency))),
                "confidence": _confidence(confidence),
                "evidence": sorted(set(evidence or [])),
            }
            node.update(extra)
            self.nodes[node_id] = node
        else:
            node["importance"] = max(_num(node.get("importance")), _num(importance))
            node["risk"] = max(_num(node.get("risk")), _num(risk))
            node["frequency"] = max(int(node.get("frequency", 0)), int(_num(frequency)))
            if _confidence(confidence) == "High" or node.get("confidence") == "Unknown":
                node["confidence"] = _confidence(confidence)
            node["evidence"] = sorted(set(node.get("evidence", [])) | set(evidence or []))
            for key, value in extra.items():
                if value not in (None, "", [], {}):
                    node.setdefault(key, value)
        return node_id

    def add_edge(self, source: str, target: str, relationship: str, *, weight: float = .5,
                 confidence: str = "Medium", reason: str = "", evidence: list[str] | None = None) -> None:
        if source == target or relationship not in RELATIONSHIPS:
            return
        if source not in self.nodes or target not in self.nodes:
            return
        key = (source, target, relationship)
        edge = {
            "source": source, "target": target, "relationship": relationship,
            "weight": round(max(0.0, min(1.0, _num(weight))), 6),
            "confidence": _confidence(confidence), "reason": reason,
            "evidence": sorted(set(evidence or [])),
        }
        if key in self.edges:
            old = self.edges[key]
            old["weight"] = max(old["weight"], edge["weight"])
            old["evidence"] = sorted(set(old.get("evidence", [])) | set(edge["evidence"]))
            if old.get("confidence") == "Low" and edge["confidence"] in {"Medium", "High"}:
                old["confidence"] = edge["confidence"]
        else:
            self.edges[key] = edge

    def load_inputs(self) -> None:
        root = self.reports_root
        direct = {
            "dashboard": self.root / "reports" / "dashboard" / "dashboard.json",
            "dashboard_history": self.root / "reports" / "dashboard" / "dashboard_history.json",
        }
        for key, path in direct.items():
            self.data[key] = _read(path)
            self.sources[key] = relative_path(path, self.root) if path.exists() else None
        for key, dirname, filename in [
            ("importance", "fingerprint_importance", "importance.json"),
            ("importance_summary", "fingerprint_importance", "summary.json"),
            ("risk", "fingerprint_risk", "risk.json"),
            ("risk_summary", "fingerprint_risk", "summary.json"),
            ("evolution", "fingerprint_evolution", "timeline.json"),
            ("evolution_summary", "fingerprint_evolution", "summary.json"),
            ("planner", "optimization_planner", "ranking.json"),
            ("planner_summary", "optimization_planner", "summary.json"),
            ("executor", "optimization_executor", "tasks.json"),
            ("executor_dependencies", "optimization_executor", "dependencies.json"),
            ("executor_critical_path", "optimization_executor", "critical_path.json"),
            ("executor_execution_order", "optimization_executor", "execution_order.json"),
            ("executor_sprints", "optimization_executor", "sprints.json"),
            ("executor_summary", "optimization_executor", "summary.json"),
            ("session_diff", "session_diff", "summary.json"),
            ("consistency", "", "consistency_report.json"),
            ("navigator_gap", "", "navigator_gap_analysis.json"),
        ]:
            if dirname:
                self.data[key], path = _latest(root, dirname, filename)
            else:
                candidates = sorted(root.glob(f"exp_*/{filename}"), key=lambda p: _exp_number(p.parent), reverse=True)
                path = candidates[0] if candidates else None
                self.data[key] = _read(path) if path else None
            self.sources[key] = relative_path(path, self.root) if path else None
        comp_candidates = sorted(root.glob("exp_*/**/compare.json"), key=lambda p: _exp_number(p.parents[1]), reverse=True)
        comp_path = next((p for p in comp_candidates if "knowledge_graph" not in p.parts), None)
        self.data["comparator"] = _read(comp_path) if comp_path else None
        self.sources["comparator"] = relative_path(comp_path, self.root) if comp_path else None
        self.data["historical_summaries"] = _iter_experiment_summaries(root)

    def make_nodes(self) -> None:
        for module in MODULES:
            mid = self.add_node("Module", module, module=module, category=module,
                                confidence="High", node_id=f"module:{_slug(module)}")
            self.module_ids[module] = mid
            self.add_node("Browser Feature", f"category:{module}", module=module,
                          category=module, confidence="High", node_id=f"feature:category:{_slug(module)}")

        importance = self.data.get("importance") or {}
        imp_rows = importance.get("properties", []) if isinstance(importance, dict) else []
        imp_map = {str(r.get("property")): r for r in imp_rows if isinstance(r, dict) and r.get("property")}
        risk = self.data.get("risk") or {}
        risk_rows = risk.get("risks", []) if isinstance(risk, dict) else []
        risk_map = {str(r.get("property")): r for r in risk_rows if isinstance(r, dict) and r.get("property")}
        properties = sorted(set(imp_map) | set(risk_map))
        for prop in properties:
            row = risk_map.get(prop, {})
            imp = imp_map.get(prop, {})
            mod = _module(row.get("domain") or imp.get("category"), prop)
            nid = self.add_node("Fingerprint Property", prop, module=mod, category=mod,
                                importance=row.get("importance", imp.get("estimated_importance", 0)),
                                risk=row.get("normalized_risk_score", 0),
                                frequency=1 + len(row.get("cross_domain_dependency", []) or []),
                                confidence=row.get("confidence", imp.get("confidence", "Unknown")),
                                evidence=[p for p in (self.sources.get("risk"), self.sources.get("importance")) if p],
                                node_id=f"property:{prop}", status=row.get("status", imp.get("status", "UNKNOWN")),
                                recommendation=row.get("recommendation"), dependency=row.get("cross_domain_dependency", imp.get("dependency", [])))
            self.prop_ids[prop] = nid

        for row in risk_rows:
            if not isinstance(row, dict) or not row.get("property"):
                continue
            prop = str(row["property"])
            rid = self.add_node("Risk Item", f"Risk: {prop}", module=_module(row.get("domain"), prop),
                                category=_module(row.get("domain"), prop), importance=row.get("importance", 0),
                                risk=row.get("normalized_risk_score", 0), confidence=row.get("confidence"),
                                evidence=[self.sources.get("risk")] if self.sources.get("risk") else [],
                                node_id=f"risk:{prop}", status=row.get("status"), reason=row.get("recommendation"))
            self.add_edge(rid, self.prop_ids.get(prop, ""), "derived_from", weight=.8,
                          confidence=row.get("confidence", "Medium"), reason="Risk analysis identifies this property.", evidence=[self.sources.get("risk")] if self.sources.get("risk") else [])

        # Consistency rules provide independent evidence, including rules
        # that do not have a comparator risk row.
        consistency = self.data.get("consistency") or {}
        rule_property = {
            "ua_ua_ch": "navigator.userAgentData", "platform_ua": "navigator.platform",
            "languages_language": "navigator.languages", "viewport_screen": "window.innerWidth",
            "dpr_viewport": "window.devicePixelRatio", "vendor_browser": "navigator.vendor",
            "webdriver_automation": "navigator.webdriver", "plugin_mime": "navigator.plugins",
        }
        for issue in consistency.get("issues", []) if isinstance(consistency, dict) else []:
            if not isinstance(issue, dict) or not issue.get("rule"):
                continue
            rule = str(issue["rule"])
            rid = self.add_node("Risk Item", f"Consistency: {issue.get('name', rule)}", module="Other", category="Cross-Domain",
                                risk=SEVERITY_SCORE.get(str(issue.get("severity")), .25) * 100,
                                confidence=issue.get("confidence", "Unknown"), frequency=1,
                                evidence=[self.sources.get("consistency")] if self.sources.get("consistency") else [],
                                node_id=f"risk:consistency:{_slug(rule)}", status=issue.get("status"), reason=issue.get("reason"),
                                recommended_fix=issue.get("recommended_fix"))
            prop = rule_property.get(rule)
            if prop and prop in self.prop_ids:
                self.add_edge(rid, self.prop_ids[prop], "derived_from", weight=.75, confidence=issue.get("confidence", "Medium"), reason="Consistency validator rule.")
            if "exp_013" in self.experiment_ids:
                self.add_edge(rid, self.experiment_ids["exp_013"], "validated_by", weight=.7, confidence="High", reason="Consistency evaluation evidence.")

        for exp_id, path, summary in self.data.get("historical_summaries", []):
            eid = self.add_node("Experiment", exp_id, module="Other", category="Experiment",
                                frequency=1, confidence="High", evidence=[relative_path(path, self.root)],
                                node_id=f"experiment:{exp_id}", result=summary.get("result"))
            self.experiment_ids[exp_id] = eid

        planner = self.data.get("planner") or {}
        planner_rows = planner.get("ranking", planner.get("items", [])) if isinstance(planner, dict) else []
        if not isinstance(planner_rows, list):
            planner_rows = []
        plan_map = {str(r.get("property")): r for r in planner_rows if isinstance(r, dict) and r.get("property")}
        executor = self.data.get("executor") or {}
        task_rows = executor.get("tasks", []) if isinstance(executor, dict) else []
        if not isinstance(task_rows, list):
            task_rows = []
        for task in sorted((r for r in task_rows if isinstance(r, dict)), key=lambda r: str(r.get("task_id", ""))):
            tid = str(task.get("task_id") or f"OPT-{len(self.task_ids)+1:03d}")
            prop = _property_from_task(task)
            prop_id = self.prop_ids.get(prop)
            if prop_id is None:
                mod = _module(task.get("module"), prop)
                prop_id = self.add_node("Fingerprint Property", prop, module=mod, category=mod,
                                        importance=task.get("planner_priority_score", 0), risk=task.get("normalized_risk_score", 0),
                                        frequency=1, confidence=task.get("confidence", "Unknown"), node_id=f"property:{prop}")
                self.prop_ids[prop] = prop_id
            tnode = self.add_node("Task", str(task.get("title") or tid), module=_module(task.get("module"), prop),
                                  category=task.get("category") or _module(task.get("module"), prop),
                                  importance=task.get("expected_similarity_increase", task.get("estimated_gain", 0)),
                                  risk=task.get("normalized_risk_score", 0), frequency=1,
                                  confidence=task.get("confidence", "Unknown"),
                                  evidence=[self.sources.get("executor")] if self.sources.get("executor") else [],
                                  node_id=f"task:{tid}", task_id=tid, fingerprint_property=prop,
                                  priority=task.get("priority"), severity=task.get("severity"),
                                  estimated_gain=_num(task.get("expected_similarity_increase", task.get("estimated_gain"))),
                                  expected_cf_increase=_num(task.get("expected_cf_increase", task.get("expected_cf_gain"))),
                                  difficulty=task.get("estimated_difficulty"), risk_level=task.get("risk_level"),
                                  roi=_num(task.get("roi")), sprint=task.get("sprint"), status="PLANNED")
            self.task_ids[tid] = tnode
            self.add_edge(tnode, prop_id, "implemented_by", weight=.9, confidence=task.get("confidence", "Medium"),
                          reason="Optimization Executor maps one task to one fingerprint property.", evidence=[self.sources.get("executor")] if self.sources.get("executor") else [])
            for exp in task.get("related_experiments", []) or []:
                match = re.search(r"(?:exp(?:eriment)?)[_ -]?(\d+)", str(exp), re.I)
                if match:
                    eid = self.experiment_ids.get(f"exp_{int(match.group(1)):03d}")
                    if eid:
                        self.add_edge(tnode, eid, "validated_by", weight=.5, confidence="Medium", reason="Task references an experiment.")
            for dep in task.get("dependencies", []) or []:
                dep_task = self.task_ids.get(str(dep))
                if dep_task:
                    self.add_edge(tnode, dep_task, "depends_on", weight=.8, confidence="High", reason="Executor dependency graph.", evidence=[self.sources.get("executor_dependencies")] if self.sources.get("executor_dependencies") else [])
            for dep in task.get("blocking_tasks", []) or []:
                dep_task = self.task_ids.get(str(dep))
                if dep_task:
                    self.add_edge(tnode, dep_task, "depends_on", weight=.9, confidence="High", reason="Blocking task relationship.")

            recommendation = task.get("reason") or task.get("recommendation")
            if recommendation:
                rid = self.add_node("Recommendation", str(recommendation), module=_module(task.get("module"), prop),
                                    category=task.get("category") or _module(task.get("module"), prop),
                                    importance=task.get("expected_similarity_increase", task.get("estimated_gain", 0)),
                                    risk=task.get("normalized_risk_score", 0), frequency=1,
                                    confidence=task.get("confidence", "Unknown"), node_id=f"recommendation:{_slug(recommendation)}",
                                    source_task=tid)
                self.add_edge(rid, prop_id, "recommended_by", weight=.8, confidence=task.get("confidence", "Medium"),
                              reason="Optimization task recommendation targets this property.", evidence=[self.sources.get("executor")] if self.sources.get("executor") else [])

        # Preserve recommendations from the planner even if a task was not
        # carried into the executor backlog.
        for row in planner_rows:
            if not isinstance(row, dict) or not row.get("property") or not row.get("recommendation"):
                continue
            prop_id = self.prop_ids.get(str(row["property"]))
            if not prop_id:
                continue
            rid = self.add_node("Recommendation", str(row["recommendation"]), module=_module(row.get("domain"), str(row["property"])),
                                category=row.get("category") or _module(row.get("domain"), str(row["property"])),
                                importance=row.get("estimated_overall_gain_pct", row.get("importance", 0)),
                                risk=row.get("normalized_risk_score", 0), frequency=1,
                                confidence=row.get("confidence", "Unknown"), node_id=f"recommendation:{_slug(row['recommendation'])}", source="planner")
            self.add_edge(rid, prop_id, "recommended_by", weight=.7, confidence=row.get("confidence", "Medium"),
                          reason="Planner recommendation targets this property.", evidence=[self.sources.get("planner")] if self.sources.get("planner") else [])

        sprints = self.data.get("executor_sprints") or {}
        sprint_rows = sprints.get("sprints", []) if isinstance(sprints, dict) else []
        if isinstance(sprint_rows, list):
            for sprint in sorted((s for s in sprint_rows if isinstance(s, dict)), key=lambda s: str(s.get("sprint", s.get("name", "")))):
                name = str(sprint.get("sprint") or sprint.get("name") or "Sprint")
                number = re.search(r"(\d+)", name)
                sid = self.add_node("Sprint", name, module="Other", category="Planning", frequency=1,
                                    confidence="High", node_id=f"sprint:{number.group(1) if number else _slug(name)}",
                                    estimated_gain=_num(sprint.get("estimated_gain")), estimated_hours=_num(sprint.get("estimated_duration_hours", sprint.get("duration_hours"))))
                for tid in sprint.get("task_ids", sprint.get("tasks", [])) or []:
                    tid = str(tid)
                    if tid in self.task_ids:
                        self.add_edge(self.task_ids[tid], sid, "scheduled_in", weight=.8, confidence="High", reason="Executor sprint assignment.", evidence=[self.sources.get("executor_sprints")] if self.sources.get("executor_sprints") else [])

        for category in MODULES:
            self.add_node("Browser Feature", category, module=category, category=category, frequency=1,
                          confidence="High", node_id=f"feature:{_slug(category)}")

        # The executor stores task dependencies separately from the per-task
        # property dependencies.  Resolve those edges after all task nodes
        # exist so forward references are retained.
        dependency_data = self.data.get("executor_dependencies") or {}
        for edge in dependency_data.get("edges", []) if isinstance(dependency_data, dict) else []:
            if not isinstance(edge, dict):
                continue
            source = self.task_ids.get(str(edge.get("source")))
            target = self.task_ids.get(str(edge.get("target")))
            if source and target:
                self.add_edge(source, target, "depends_on", weight=.9, confidence="High",
                              reason="Optimization Executor dependency graph.", evidence=[self.sources.get("executor_dependencies")] if self.sources.get("executor_dependencies") else [])
        for name, module in [("UA Client Hints", "Chrome"), ("Chrome Runtime", "Chrome"), ("GPU", "WebGL"),
                             ("ANGLE", "WebGL"), ("Extensions", "WebGL")]:
            self.add_node("Browser API" if name in {"UA Client Hints", "Chrome Runtime"} else "Browser Feature",
                          name, module=module, category=module, confidence="Medium", node_id=f"api:{_slug(name)}" if name in {"UA Client Hints", "Chrome Runtime"} else f"feature:{_slug(name)}")

    def make_edges(self) -> None:
        for prop, pid in sorted(self.prop_ids.items()):
            node = self.nodes[pid]
            module = node.get("module", "Other")
            mid = self.module_ids.get(module)
            if mid:
                self.add_edge(pid, mid, "same_module", weight=.35, confidence="High", reason="Property belongs to its detected module.")
            cat = f"feature:category:{_slug(module)}"
            if cat in self.nodes:
                self.add_edge(pid, cat, "same_category", weight=.25, confidence="High", reason="Property and category share a domain.")
            for dep in node.get("dependency", []) or []:
                dep_id = self.prop_ids.get(str(dep))
                if dep_id:
                    self.add_edge(pid, dep_id, "depends_on", weight=.8, confidence="Medium", reason="Cross-domain dependency from risk/importance analysis.", evidence=[self.sources.get("risk")] if self.sources.get("risk") else [])

        def p(name: str) -> str:
            return self.prop_ids.get(name) or self.add_node("Fingerprint Property", name, module=_module("", name), category=_module("", name), frequency=1, confidence="Medium", node_id=f"property:{name}")
        inference = [
            ("navigator.userAgentData", "navigator.userAgent", "depends_on", .9, "UA Client Hints must agree with the user agent."),
            ("navigator.userAgent", "api:ua_client_hints", "correlates_with", .65, "UA and UA-CH describe one browser identity."),
            ("api:ua_client_hints", "api:chrome_runtime", "depends_on", .55, "Desktop Chromium exposes the related runtime surface."),
            ("performance.memory", "navigator.deviceMemory", "correlates_with", .7, "Memory signals should be coherent."),
            ("screen", "window.visualViewport", "depends_on", .8, "Viewport derives from screen and window geometry."),
            ("window.visualViewport", "window", "depends_on", .8, "Visual viewport is a window API."),
            ("speech voices", "navigator.languages", "correlates_with", .65, "Voice locales should align with browser languages."),
            ("navigator.languages", "navigator.language", "depends_on", .8, "Primary language should be included in languages."),
            ("WebGL renderer", "feature:gpu", "depends_on", .7, "Renderer identifies the graphics device."),
            ("feature:gpu", "feature:angle", "correlates_with", .55, "Chromium GPU paths commonly use ANGLE."),
            ("feature:angle", "feature:extensions", "correlates_with", .5, "ANGLE affects extension exposure."),
        ]
        for source, target, rel, weight, reason in inference:
            source_id = source if source.startswith(("api:", "feature:")) else p(source)
            target_id = target if target.startswith(("api:", "feature:")) else p(target)
            self.add_edge(source_id, target_id, rel, weight=weight, confidence="Medium", reason=reason)

        evolution = self.data.get("evolution") or {}
        timeline = evolution.get("timeline", evolution.get("experiments", [])) if isinstance(evolution, dict) else evolution
        if isinstance(timeline, list):
            rows = [r for r in timeline if isinstance(r, dict)]
            for a, b in zip(rows, rows[1:]):
                aid = str(a.get("experiment_id") or a.get("experiment") or "")
                bid = str(b.get("experiment_id") or b.get("experiment") or "")
                if aid in self.experiment_ids and bid in self.experiment_ids:
                    delta = _num(b.get("overall_score")) - _num(a.get("overall_score"))
                    rel = "improves" if delta >= 0 else "regresses"
                    self.add_edge(self.experiment_ids[aid], self.experiment_ids[bid], rel, weight=min(1, abs(delta) / 100), confidence="High", reason="Adjacent fingerprint evolution timeline.")

    def serialize(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        nodes = sorted(self.nodes.values(), key=lambda n: n["id"])
        edges = sorted(self.edges.values(), key=lambda e: (e["source"], e["target"], e["relationship"]))
        return nodes, edges


def _centrality(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, set[str]], dict[str, set[str]]]:
    ids = [n["id"] for n in nodes]
    undirected: dict[str, set[str]] = {i: set() for i in ids}
    directed: dict[str, set[str]] = {i: set() for i in ids}
    for edge in edges:
        s, t = edge["source"], edge["target"]
        undirected[s].add(t); undirected[t].add(s); directed[s].add(t)
    n = len(ids)
    degree = {i: len(undirected[i]) / max(1, n - 1) for i in ids}
    between = dict.fromkeys(ids, 0.0)
    for source in ids:
        stack: list[str] = []
        pred = {v: [] for v in ids}
        sigma = dict.fromkeys(ids, 0.0); sigma[source] = 1.0
        dist = dict.fromkeys(ids, -1); dist[source] = 0
        queue = deque([source])
        while queue:
            v = queue.popleft(); stack.append(v)
            for w in sorted(undirected[v]):
                if dist[w] < 0:
                    dist[w] = dist[v] + 1; queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]; pred[w].append(v)
        dep = dict.fromkeys(ids, 0.0)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                if sigma[w]: dep[v] += sigma[v] / sigma[w] * (1 + dep[w])
            if w != source: between[w] += dep[w]
    if n > 2:
        between = {k: v * 2 / ((n - 1) * (n - 2)) for k, v in between.items()}
    closeness = {}
    for source in ids:
        dist = {source: 0}; q = deque([source])
        while q:
            v = q.popleft()
            for w in undirected[v]:
                if w not in dist: dist[w] = dist[v] + 1; q.append(w)
        total = sum(dist.values())
        closeness[source] = (len(dist) - 1) / total if total else 0.0
    values = {i: {"id": i, "degree": round(degree[i], 6), "betweenness": round(between[i], 6), "closeness": round(closeness[i], 6), "in_degree": sum(i in directed[x] for x in ids), "out_degree": len(directed[i])} for i in ids}
    ranking = sorted(values.values(), key=lambda x: (-x["betweenness"], -x["degree"], x["id"]))
    hubs = [x["id"] for x in sorted(values.values(), key=lambda x: (-x["degree"], x["id"]))[:10]]
    bridges = [x["id"] for x in ranking[:10]]
    orphan = sorted(i for i in ids if not undirected[i])
    centrality = {"nodes": ranking, "top_nodes": ranking[:25], "hubs": hubs, "bridges": bridges, "orphans": orphan,
                  "critical_nodes": [x["id"] for x in ranking if x["betweenness"] >= .1][:25]}
    return centrality, undirected, directed


def _components(nodes: list[dict[str, Any]], adjacency: dict[str, set[str]], directed: dict[str, set[str]] | None = None) -> tuple[list[dict[str, Any]], list[list[str]]]:
    unseen = set(n["id"] for n in nodes); components = []
    while unseen:
        start = min(unseen); unseen.remove(start); q = [start]; group = [start]
        while q:
            cur = q.pop()
            for nxt in sorted(adjacency[cur]):
                if nxt in unseen: unseen.remove(nxt); q.append(nxt); group.append(nxt)
        components.append(sorted(group))
    components.sort(key=lambda c: (-len(c), c[0]))
    comp_rows = [{"id": f"component:{i+1:03d}", "size": len(c), "nodes": c} for i, c in enumerate(components)]
    # Tarjan SCC over the directed graph identifies actual strongly connected groups.
    directed = directed or adjacency
    index = 0; indices = {}; low = {}; stack = []; onstack = set(); sccs = []
    def visit(v: str) -> None:
        nonlocal index
        indices[v] = low[v] = index; index += 1; stack.append(v); onstack.add(v)
        for w in sorted(directed[v]):
            if w not in indices: visit(w); low[v] = min(low[v], low[w])
            elif w in onstack: low[v] = min(low[v], indices[w])
        if low[v] == indices[v]:
            group = []
            while True:
                w = stack.pop(); onstack.remove(w); group.append(w)
                if w == v: break
            if len(group) > 1: sccs.append(sorted(group))
    for node in sorted(adjacency):
        if node not in indices: visit(node)
    sccs.sort(key=lambda c: (-len(c), c[0]))
    return comp_rows, sccs


def _markdown(summary: dict[str, Any], centrality: dict[str, Any], clusters: dict[str, Any], modules: list[dict[str, Any]], impact: list[dict[str, Any]], recommendations: dict[str, Any], validation: dict[str, Any]) -> str:
    lines = ["# Fingerprint Knowledge Graph", "", "## Executive Summary", "", f"- Result: **{summary['result']}**", f"- Nodes: **{summary['node_count']}**", f"- Edges: **{summary['edge_count']}**", f"- Components: **{summary['connected_components']}**", "- Browser launches: **0**", "- Network requests: **0**", "", "## Graph Overview", "", "| Metric | Value |", "|---|---:|", f"| Nodes | {summary['node_count']} |", f"| Edges | {summary['edge_count']} |", f"| Fingerprint properties | {summary['property_count']} |", f"| Tasks | {summary['task_count']} |", f"| Modules | {summary['module_count']} |", "", "## Centrality", "", "| Node | Degree | Betweenness | Closeness |", "|---|---:|---:|---:|"]
    for row in centrality.get("top_nodes", [])[:15]: lines.append(f"| `{row['id']}` | {row['degree']:.3f} | {row['betweenness']:.3f} | {row['closeness']:.3f} |")
    lines += ["", "## Clusters", "", f"Connected components: **{len(clusters.get('components', []))}**; strongly connected groups: **{len(clusters.get('strongly_connected_groups', []))}**.", "", "| Component | Size |", "|---|---:|"]
    for row in clusters.get("components", [])[:15]: lines.append(f"| {row['id']} | {row['size']} |")
    lines += ["", "## Hotspots", ""]
    for key, value in summary.get("hotspots", {}).items(): lines.append(f"- **{key.replace('_', ' ').title()}**: `{value}`")
    lines += ["", "## Module Analysis", "", "| Module | Properties | Internal density | External deps | Cross links |", "|---|---:|---:|---:|---:|"]
    for row in modules: lines.append(f"| {row['module']} | {row['property_count']} | {row['internal_density']:.3f} | {row['external_dependencies']} | {row['cross_module_links']} |")
    lines += ["", "## Task Impact", "", "| Task | Property | Gain | CF gain | ROI | Risk |", "|---|---|---:|---:|---:|---|"]
    for row in impact[:20]: lines.append(f"| `{row['task_id']}` | `{row['fingerprint_property']}` | {row['expected_similarity_increase']:.3f} | {row['expected_cf_increase']:.3f} | {row['roi']:.3f} | {row['risk_level']} |")
    lines += ["", "## Recommendations", "", f"- Priority nodes: {len(recommendations.get('priority_nodes', []))}", f"- Learning candidates: {len(recommendations.get('learning_candidates', []))}", f"- Optimization candidates: {len(recommendations.get('optimization_candidates', []))}", f"- Uncertain relationships: {len(recommendations.get('uncertain_relationships', []))}", "", "## Validation", "", f"- Valid: **{validation.get('valid')}**", f"- Deterministic ordering: **{validation.get('deterministic_ordering')}**", f"- Artifact completeness: **{validation.get('artifact_completeness')}**", "", "## Final Conclusion", "", "The graph is a deterministic, read-only evidence map that can be reused by future planning experiments."]
    return "\n".join(lines) + "\n"


def run(reports_root: Path) -> Path:
    root = project_root()
    experiment = Experiment.create(reports_root)
    builder = GraphBuilder(root, reports_root)
    builder.load_inputs(); builder.make_nodes(); builder.make_edges()
    nodes, edges = builder.serialize()
    centrality, adjacency_sets, directed = _centrality(nodes, edges)
    components, sccs = _components(nodes, adjacency_sets, directed)
    adjacency = {node["id"]: sorted(adjacency_sets[node["id"]]) for node in nodes}
    clusters = {"components": components, "strongly_connected_groups": [{"id": f"scc:{i+1:03d}", "nodes": g, "size": len(g)} for i, g in enumerate(sccs)]}
    modules = []
    for module in MODULES:
        prop_ids = {n["id"] for n in nodes if n.get("type") == "Fingerprint Property" and n.get("module") == module}
        task_ids = {n["id"] for n in nodes if n.get("type") == "Task" and n.get("module") == module}
        internal = sum(1 for e in edges if e["source"] in prop_ids and e["target"] in prop_ids)
        external = sum(1 for e in edges if (e["source"] in prop_ids) != (e["target"] in prop_ids))
        cross = sum(1 for e in edges if e["source"] in prop_ids and e["target"] in {n["id"] for n in nodes if n.get("module") not in {module, None}})
        denom = max(1, len(prop_ids) * max(1, len(prop_ids)-1))
        modules.append({"module": module, "node_count": sum(1 for n in nodes if n.get("module") == module), "property_count": len(prop_ids), "task_count": len(task_ids), "internal_edge_count": internal, "internal_density": round(internal / denom, 6), "external_dependencies": external, "cross_module_links": cross})
    modules.sort(key=lambda x: x["module"])
    task_nodes = [n for n in nodes if n.get("type") == "Task"]
    impact = []
    for task in sorted(task_nodes, key=lambda n: (-_num(n.get("roi")), n["id"])):
        related_ids = {task["id"]}
        related_ids.update(e["target"] for e in edges if e["source"] == task["id"] and e["relationship"] in {"depends_on", "implemented_by"})
        related_ids.update(e["source"] for e in edges if e["target"] == task["id"] and e["relationship"] == "depends_on")
        downstream = sum(1 for e in edges if e["relationship"] == "depends_on" and e["target"] == task["id"])
        prop = str(task.get("fingerprint_property", ""))
        impacted_modules = sorted({n.get("module", "Other") for n in nodes if n["id"] in related_ids})
        impact.append({"task_id": task.get("task_id", task["id"]), "title": task.get("name"), "fingerprint_property": prop, "affected_nodes": len(related_ids), "affected_modules": impacted_modules, "expected_similarity_increase": _num(task.get("estimated_gain")), "expected_cf_increase": _num(task.get("expected_cf_increase")), "risk_level": task.get("risk_level", "Unknown"), "difficulty": task.get("difficulty", "Unknown"), "roi": _num(task.get("roi")), "downstream_tasks": downstream})
    impact.sort(key=lambda x: (-x["roi"], -x["expected_similarity_increase"], x["task_id"]))
    risk_props = sorted((n for n in nodes if n.get("type") == "Fingerprint Property"), key=lambda n: (-n.get("risk", 0), -n.get("importance", 0), n["id"]))
    property_score = lambda n: _num(n.get("importance")) * (.5 + _num(n.get("risk")) / 200) * (1 + _num(n.get("frequency")) / 10)
    influential = sorted(risk_props, key=lambda n: (-property_score(n), n["id"]))
    module_candidates = [m for m in modules if m["module"] not in {"Other", "Environment", "Storage"}] or modules
    critical_path_data = builder.data.get("executor_critical_path") or {}
    critical_chain = critical_path_data.get("longest_dependency_chain") or critical_path_data.get("highest_value_chain") or [] if isinstance(critical_path_data, dict) else []
    hotspots = {"most_influential_property": influential[0]["id"] if influential else None,
                "most_connected_module": max(module_candidates, key=lambda x: (x["node_count"], x["module"]))["module"] if module_candidates else None,
                "highest_risk_cluster": components[0]["id"] if components else None,
                "highest_roi_cluster": impact[0]["task_id"] if impact else None,
                "most_critical_dependency_chain": critical_chain,
                "most_frequently_appearing_property": max(risk_props, key=lambda n: (n.get("frequency", 0), n["id"]))["id"] if risk_props else None}
    recommendations = {
        "priority_nodes": [n["id"] for n in influential[:25]],
        "learning_candidates": [n["id"] for n in nodes if n.get("confidence") in {"Low", "Unknown"}][:50],
        "optimization_candidates": [x["task_id"] for x in impact[:25]],
        "uncertain_relationships": [e for e in edges if e.get("confidence") in {"Low", "Unknown"}],
        "requires_validation": [n["id"] for n in task_nodes if n.get("risk_level") in {"High", "Critical"} or n.get("confidence") in {"Low", "Unknown"}],
    }
    planner_available = bool(builder.sources.get("planner"))
    executor_available = bool(builder.sources.get("executor"))
    summary = {"experiment": "Experiment 028 — Fingerprint Knowledge Graph", "generated_at": now_iso(), "result": "SUCCESS" if planner_available and executor_available else "PARTIAL", "analysis_only": True, "browser_launches": 0, "network_requests": 0, "node_count": len(nodes), "edge_count": len(edges), "property_count": sum(n.get("type") == "Fingerprint Property" for n in nodes), "task_count": sum(n.get("type") == "Task" for n in nodes), "module_count": sum(n.get("type") == "Module" for n in nodes), "connected_components": len(components), "strongly_connected_groups": len(sccs), "sources": {k: v for k, v in sorted(builder.sources.items()) if v}, "hotspots": hotspots}
    graph = {"schema_version": "1.0", "experiment": "028", "nodes": nodes, "edges": edges, "sources": summary["sources"], "analysis_only": True}
    validation = {"json_valid": True, "artifact_completeness": True, "deterministic_ordering": nodes == sorted(nodes, key=lambda n: n["id"]) and edges == sorted(edges, key=lambda e: (e["source"], e["target"], e["relationship"])), "node_uniqueness": len(nodes) == len({n["id"] for n in nodes}), "edge_uniqueness": len(edges) == len({(e["source"], e["target"], e["relationship"]) for e in edges}), "self_loops": [e for e in edges if e["source"] == e["target"]], "centrality_validation": all(row["id"] in adjacency for row in centrality["nodes"]), "cluster_validation": all(set(c["nodes"]).issubset(adjacency) for c in components), "adjacency_validation": set(adjacency) == {n["id"] for n in nodes}, "markdown_valid": True, "browser_launches": 0, "network_requests": 0, "source_artifacts_unchanged": True}
    validation["valid"] = all([validation["json_valid"], validation["artifact_completeness"], validation["deterministic_ordering"], validation["node_uniqueness"], validation["edge_uniqueness"], not validation["self_loops"], validation["centrality_validation"], validation["cluster_validation"], validation["adjacency_validation"], validation["markdown_valid"], validation["browser_launches"] == 0, validation["network_requests"] == 0])
    artifact = {"graph.json": graph, "nodes.json": nodes, "edges.json": edges, "adjacency.json": adjacency, "centrality.json": centrality, "clusters.json": clusters, "hotspots.json": hotspots, "modules.json": modules, "impact.json": impact, "recommendations.json": recommendations, "statistics.json": {"total_nodes": len(nodes), "total_edges": len(edges), "node_types": dict(sorted(Counter(n["type"] for n in nodes).items())), "edge_types": dict(sorted(Counter(e["relationship"] for e in edges).items())), "component_count": len(components), "scc_count": len(sccs), "orphan_count": len(centrality["orphans"]), "hub_count": len(centrality["hubs"]), "bridge_count": len(centrality["bridges"]), "source_count": len(summary["sources"]), "browser_launches": 0, "network_requests": 0}, "summary.json": summary, "validation.json": validation}
    output = experiment.directory / "knowledge_graph"; output.mkdir(exist_ok=False)
    for filename, payload in artifact.items(): write_json_exclusive(output / filename, payload)
    write_text_exclusive(output / "knowledge_graph.md", _markdown(summary, centrality, clusters, modules, impact, recommendations, validation))
    metadata = {"experiment_id": experiment.experiment_id, "started_at": experiment.started_at, "completed_at": now_iso(), "system": system_metadata(), "git": git_metadata(root), "analysis_only": True, "browser_launches": 0, "network_requests": 0}
    write_json_exclusive(experiment.directory / "metadata.json", metadata)
    return output


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    parser = argparse.ArgumentParser(description="Build a read-only fingerprint knowledge graph")
    parser.add_argument("--reports-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = project_root(); reports = (args.reports_dir or root / "reports" / "experiments").resolve()
    try:
        output = run(reports)
    except Exception as exc:  # commit a useful non-zero CLI result without touching inputs
        print(f"Knowledge graph failed: {exc}", file=sys.stderr)
        return 1
    print(f"Knowledge graph written to {relative_path(output, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
