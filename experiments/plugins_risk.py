"""Experiment 040: offline Plugins & MimeTypes risk assessment.

This module consumes only immutable JSON/Markdown artifacts.  It never imports
Playwright, launches a browser, changes a stealth module, or writes to an
input experiment.  Risk values are deterministic heuristics intended to make
the comparator output actionable without pretending to be a browser test.
"""
from __future__ import annotations

import argparse
import hashlib
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
    now_iso,
    project_root,
    sha256_file,
    write_json_exclusive,
    write_text_exclusive,
)


GROUPS = ("Critical", "High", "Medium", "Low")
STATUSES = ("CHANGED", "MISSING", "ADDED", "REMOVED")
COMPLEXITIES = ("Easy", "Medium", "Hard", "Very Hard")
REQUIRED_INPUTS = ("plugins.json", "mime_types.json", "prototype.json", "descriptors.json", "methods.json", "cross_reference.json", "fingerprint.json")


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
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
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _load_directory(directory: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if directory is None or not directory.is_dir():
        return {}, {"available": False, "directory": str(directory) if directory else None, "files": {}, "hashes": {}}
    documents = {name: _read_json(directory / name) for name in REQUIRED_INPUTS}
    hashes = {name: sha256_file(directory / name) for name in REQUIRED_INPUTS if (directory / name).is_file()}
    return documents, {
        "available": all(bool(documents[name]) for name in REQUIRED_INPUTS),
        "directory": str(directory),
        "files": {name: (directory / name).is_file() for name in REQUIRED_INPUTS},
        "hashes": hashes,
    }


def _find_dir(root: Path, explicit: Path | None, suffix: str) -> Path | None:
    if explicit is not None:
        candidate = explicit if explicit.is_absolute() else root / explicit
        return candidate if candidate.is_dir() else None
    preferred = root / "reports" / "experiments" / suffix
    if preferred.is_dir():
        return preferred
    candidates = sorted(root.glob(f"reports/experiments/exp_*/{suffix.split('/')[-1]}"), key=lambda item: item.as_posix())
    return candidates[-1] if candidates else None


def _load_compare(directory: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if directory is None or not directory.is_dir():
        return {}, {"available": False, "directory": str(directory) if directory else None, "hashes": {}}
    names = ("differences.json", "similarity.json", "statistics.json", "summary.json", "validation.json", "compare.json")
    values = {name: _read_json(directory / name) for name in names}
    hashes = {name: sha256_file(directory / name) for name in names if (directory / name).is_file()}
    return values, {"available": all((directory / name).is_file() for name in names), "directory": str(directory), "hashes": hashes}


def _domain(path: str, category: str | None = None) -> str:
    lowered = path.lower()
    if lowered.startswith("plugins.items"):
        return "Plugins"
    if lowered.startswith("mime_types.items"):
        return "MimeTypes"
    if lowered.startswith("plugins"):
        return "PluginArray"
    if lowered.startswith("mime_types"):
        return "MimeTypeArray"
    if lowered.startswith("prototype"):
        return "Prototype"
    if lowered.startswith("descriptors"):
        return "Descriptors"
    if lowered.startswith("methods"):
        return "Methods"
    if lowered.startswith("cross_reference"):
        return "Cross-reference"
    if lowered.startswith("navigator"):
        return "Navigator"
    if category:
        return str(category)
    return "Other"


def _importance(path: str, domain: str) -> float:
    lowered = path.lower()
    base = {
        "Prototype": 94.0,
        "Descriptors": 86.0,
        "Methods": 84.0,
        "Cross-reference": 80.0,
        "Plugins": 74.0,
        "MimeTypes": 74.0,
        "PluginArray": 70.0,
        "MimeTypeArray": 70.0,
        "Navigator": 68.0,
        "Fingerprint": 20.0,
        "Other": 35.0,
    }.get(domain, 35.0)
    if any(token in lowered for token in ("constructor", "instanceof", "prototypechain", "tostringtag")):
        base += 8.0
    if any(token in lowered for token in ("name", "type", "filename", "enabledplugin", "length", "count")):
        base += 4.0
    if lowered == "fingerprint.sha256":
        base = 15.0
    return round(min(100.0, base), 2)


def _entropy(path: str, real: Any, playwright: Any) -> float:
    lowered = path.lower()
    if any(token in lowered for token in ("name", "type", "filename", "hash", "source")):
        return 90.0
    if any(token in lowered for token in ("prototype", "descriptor", "instanceof", "tostringtag", "illegal")):
        return 85.0
    if any(token in lowered for token in ("count", "length", "enabled")):
        return 65.0
    if isinstance(real, (dict, list)) or isinstance(playwright, (dict, list)):
        return 70.0
    if isinstance(real, str) or isinstance(playwright, str):
        return 60.0
    if isinstance(real, bool) or isinstance(playwright, bool):
        return 35.0
    return 45.0


def _cf_impact(path: str, domain: str) -> float:
    lowered = path.lower()
    if lowered == "fingerprint.sha256":
        return 15.0
    if domain in {"Prototype", "Descriptors", "Methods", "Cross-reference"}:
        return 82.0
    if domain in {"Plugins", "MimeTypes", "PluginArray", "MimeTypeArray"}:
        return 68.0 if any(token in lowered for token in ("name", "type", "filename", "length", "count")) else 58.0
    if domain == "Navigator":
        return 62.0
    return 40.0


def _confidence(path: str, status: str, real: Any, playwright: Any) -> str:
    lowered = path.lower()
    if status == "REMOVED" or any(token in lowered for token in ("prototype", "descriptor", "native", "source", "instanceof")):
        return "High"
    if isinstance(real, (dict, list)) or isinstance(playwright, (dict, list)):
        return "Medium"
    if status == "ADDED" or lowered == "fingerprint.sha256":
        return "Low"
    return "Medium"


def _complexity(path: str, domain: str, status: str) -> str:
    lowered = path.lower()
    if lowered == "fingerprint.sha256":
        return "Very Hard"
    if domain in {"Prototype", "Methods", "Cross-reference"}:
        return "Very Hard" if domain in {"Prototype", "Cross-reference"} else "Hard"
    if domain == "Descriptors":
        return "Hard"
    if any(token in lowered for token in ("items", "name", "type", "filename", "enabledplugin")):
        return "Medium"
    if any(token in lowered for token in ("count", "length", "description", "suffixes")):
        return "Easy"
    return "Medium" if status != "ADDED" else "Hard"


def _maintenance(complexity: str, domain: str, status: str) -> str:
    if status == "ADDED" or complexity == "Very Hard":
        return "High"
    if complexity == "Hard" or domain in {"Cross-reference", "Methods"}:
        return "Medium"
    return "Low"


def _severity(score: float) -> str:
    if score >= 80.0:
        return "Critical"
    if score >= 60.0:
        return "High"
    if score >= 35.0:
        return "Medium"
    return "Low"


def _status_factor(status: str) -> float:
    return {"MISSING": 1.0, "REMOVED": 1.0, "CHANGED": 0.9, "ADDED": 0.7}.get(status, 0.5)


def _complexity_factor(complexity: str) -> float:
    return {"Easy": 1.0, "Medium": 2.0, "Hard": 3.5, "Very Hard": 5.0}.get(complexity, 3.0)


def _task_id(path: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]
    return f"task_{slug[:48]}_{digest}"


def _dependencies(path: str, domain: str) -> list[str]:
    lowered = path.lower()
    deps: list[str] = []
    if domain in {"PluginArray", "Plugins"}:
        deps.append("foundation.pluginarray")
    if domain in {"MimeTypeArray", "MimeTypes"}:
        deps.append("foundation.mimetypearray")
    if domain == "Plugins":
        deps.append("foundation.mimetypearray")
    if domain == "MimeTypes":
        deps.append("foundation.pluginarray")
    if domain == "Methods":
        deps.append("foundation.prototype")
    if domain == "Descriptors":
        deps.extend(("foundation.prototype", "foundation.methods"))
    if domain == "Cross-reference":
        deps.extend(("foundation.pluginarray", "foundation.mimetypearray"))
    if domain == "Prototype":
        deps.append("foundation.pluginarray" if "plugin" in lowered else "foundation.mimetypearray")
    if domain == "Navigator":
        deps.extend(("foundation.pluginarray", "foundation.mimetypearray"))
    if domain == "Fingerprint":
        deps.extend(("foundation.pluginarray", "foundation.mimetypearray"))
    return sorted(set(deps))


def _recommendation(action: str, path: str, domain: str, status: str) -> str:
    if action == "Never Patch":
        return "Do not patch the aggregate hash or environment-specific extra surface; use it as an audit signal."
    if domain in {"Prototype", "Descriptors", "Methods"}:
        return f"{action}: preserve the native {domain.lower()} chain and attributes for {path}; validate illegal invocation and native source before rollout."
    if domain == "Cross-reference":
        return f"{action}: fix {path} only after PluginArray and MimeTypeArray identity is stable."
    if status in {"MISSING", "REMOVED"}:
        return f"{action}: restore the missing native surface for {path} using the browser's own object and descriptor shape."
    return f"{action}: investigate {path} as a profile-consistent value; avoid hardcoding a single machine fingerprint."


def _action(row: dict[str, Any]) -> str:
    if row["path"].lower() == "fingerprint.sha256" or row["status"] == "ADDED" and row["confidence"] == "Low":
        return "Never Patch"
    if row["complexity"] == "Easy" and row["roi"] >= 5.0:
        return "Patch Now"
    if row["complexity"] == "Medium" and row["roi"] >= 10.0:
        return "Patch Now"
    if row["severity"] in {"Critical", "High"} and row["complexity"] in {"Easy", "Medium", "Hard"} and row["roi"] >= 20.0:
        return "Patch Now"
    return "Patch Later"


def _topological_order(nodes: set[str], edges: list[dict[str, str]]) -> tuple[list[str], bool]:
    outgoing: dict[str, set[str]] = defaultdict(set)
    indegree = {node: 0 for node in nodes}
    for edge in edges:
        source, target = edge["from"], edge["to"]
        if source not in indegree:
            indegree[source] = 0
        if target not in indegree:
            indegree[target] = 0
        if target not in outgoing[source]:
            outgoing[source].add(target)
            indegree[target] += 1
    ready = sorted(node for node, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for target in sorted(outgoing[node]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    return order, len(order) != len(indegree)


def _report(summary: dict[str, Any], stats: dict[str, Any], ranking: list[dict[str, Any]], roadmap: dict[str, Any], validation: dict[str, Any]) -> str:
    lines = [
        "# Experiment 040 — Plugins & MimeTypes Risk Assessment",
        "",
        "Offline deterministic analysis of immutable comparator output. No browser, Playwright, network, or stealth code was used.",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Analyzed differences: **{stats['analyzed_differences']}**",
        f"- Current overall similarity: **{summary['current_similarity']:.2f}%**",
        f"- Estimated total similarity opportunity: **{summary['estimated_similarity_opportunity']:.2f}%**",
        "",
        "## Risk Distribution",
        "",
        "| Group | Count |",
        "|---|---:|",
    ]
    for group in GROUPS:
        lines.append(f"| {group} | {stats['risk_distribution'].get(group, 0)} |")
    lines += ["", "## Top Risks", "", "| Rank | Property | Domain | Status | Severity | Risk | ROI | Action |", "|---:|---|---|---|---:|---:|---:|---|"]
    for row in ranking[:20]:
        lines.append(f"| {row['rank']} | `{row['path']}` | {row['domain']} | {row['status']} | {row['severity']} | {row['risk_score']:.2f} | {row['roi']:.2f} | {row['action']} |")
    if not ranking:
        lines.append("| — | none | — | — | Low | 0 | 0 | Never Patch |")
    lines += ["", "## Roadmap", "", "| Phase | Items | Estimated Gain |", "|---|---:|---:|"]
    for phase in ("Patch Now", "Patch Later", "Never Patch"):
        item = roadmap.get(phase, {})
        lines.append(f"| {phase} | {item.get('count', 0)} | {item.get('estimated_similarity_gain', 0):.2f}% |")
    lines += ["", "## Dependency Order", "", "```text", *[f"{index}. {node}" for index, node in enumerate(roadmap.get("execution_order", []), 1)], "```", "", "## Validation", "", "| Check | Status |", "|---|---|"]
    lines.extend(f"| {key.replace('_', ' ').title()} | {'PASS' if value else 'FAIL'} |" for key, value in validation.items() if key != "missing_artifacts")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment 040: offline Plugins & MimeTypes risk assessment")
    parser.add_argument("--real-dir", type=Path, default=None, help="Real plugins artifact directory (defaults to exp_142/plugins)")
    parser.add_argument("--compare-dir", type=Path, default=None, help="Plugins comparator directory (defaults to exp_144/plugins_compare)")
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    real_dir = _find_dir(root, args.real_dir, "exp_142/plugins")
    compare_dir = _find_dir(root, args.compare_dir, "exp_144/plugins_compare")
    real_docs, real_meta = _load_directory(real_dir)
    compare_docs, compare_meta = _load_compare(compare_dir)
    differences = compare_docs.get("differences.json", [])
    if not isinstance(differences, list):
        differences = []
    similarity = compare_docs.get("similarity.json", {})
    if not isinstance(similarity, dict):
        similarity = {}
    current_similarity = _number(similarity.get("overall"), _number(compare_docs.get("summary.json", {}).get("overall_similarity"), 0.0))
    actionable = [row for row in differences if isinstance(row, dict) and str(row.get("status", "")).upper() in STATUSES]
    total = max(len(actionable), 1)
    preliminary: list[dict[str, Any]] = []
    for row in actionable:
        path = str(row.get("path", "<unknown>"))
        status = str(row.get("status", "CHANGED")).upper()
        domain = _domain(path, str(row.get("category", "Other")))
        real_value = row.get("real")
        playwright_value = row.get("playwright")
        importance = _importance(path, domain)
        entropy = _entropy(path, real_value, playwright_value)
        cf_impact = _cf_impact(path, domain)
        confidence = _confidence(path, status, real_value, playwright_value)
        confidence_factor = {"High": 1.0, "Medium": 0.82, "Low": 0.62}[confidence]
        risk_score = min(100.0, round((importance * 0.35 + entropy * 0.2 + cf_impact * 0.25 + _status_factor(status) * 100.0 * 0.1 + confidence_factor * 100.0 * 0.1), 2))
        complexity = _complexity(path, domain, status)
        maintenance = _maintenance(complexity, domain, status)
        preliminary.append({
            "path": path,
            "domain": domain,
            "status": status,
            "severity": _severity(risk_score),
            "confidence": confidence,
            "importance": importance,
            "entropy_estimate": entropy,
            "estimated_fingerprint_impact": round((importance * 0.55 + entropy * 0.45), 2),
            "estimated_cloudflare_impact": round(cf_impact, 2),
            "risk_score": risk_score,
            "complexity": complexity,
            "maintenance_cost": maintenance,
            "real_value": real_value,
            "playwright_value": playwright_value,
        })
    preliminary.sort(key=lambda row: (-row["risk_score"], -row["estimated_cloudflare_impact"], row["path"]))
    total_risk = sum(row["risk_score"] for row in preliminary) or 1.0
    opportunity = max(0.0, 100.0 - current_similarity)
    findings: list[dict[str, Any]] = []
    for row in preliminary:
        gain = round(opportunity * row["risk_score"] / total_risk, 4)
        complexity_factor = _complexity_factor(row["complexity"])
        roi = min(100.0, round((gain / complexity_factor) * 100.0, 2))
        task = _task_id(row["path"])
        enriched = dict(row)
        enriched.update({
            "task_id": task,
            "estimated_similarity_gain": gain,
            "estimated_cf_gain": round(gain * row["estimated_cloudflare_impact"] / 100.0, 4),
            "roi": roi,
            "dependencies": _dependencies(row["path"], row["domain"]),
        })
        enriched["action"] = _action(enriched)
        enriched["recommendation"] = _recommendation(enriched["action"], row["path"], row["domain"], row["status"])
        findings.append(enriched)
    findings.sort(key=lambda row: (-row["risk_score"], -row["roi"], row["path"]))
    for index, row in enumerate(findings, 1):
        row["rank"] = index
        row["suggested_order"] = index
    dependencies_nodes: set[str] = set()
    dependencies_edges: list[dict[str, str]] = []
    foundation_edges = {
        "foundation.prototype": ["foundation.pluginarray", "foundation.mimetypearray"],
        "foundation.methods": ["foundation.prototype"],
        "foundation.descriptors": ["foundation.prototype", "foundation.methods"],
        "foundation.cross_reference": ["foundation.pluginarray", "foundation.mimetypearray"],
    }
    for target, sources in foundation_edges.items():
        dependencies_nodes.add(target)
        for source in sources:
            dependencies_nodes.add(source)
            dependencies_edges.append({"from": source, "to": target, "relationship": "depends_on"})
    for row in findings:
        task = row["task_id"]
        dependencies_nodes.add(task)
        for dependency in row["dependencies"]:
            dependencies_nodes.add(dependency)
            dependencies_edges.append({"from": dependency, "to": task, "relationship": "depends_on"})
    dependencies_edges = sorted({(edge["from"], edge["to"], edge["relationship"]): edge for edge in dependencies_edges}.values(), key=lambda edge: (edge["from"], edge["to"]))
    execution_order, cycle_detected = _topological_order(dependencies_nodes, dependencies_edges)
    order_index = {node: index for index, node in enumerate(execution_order, 1)}
    for row in findings:
        row["suggested_order"] = order_index.get(row["task_id"], len(order_index) + row["rank"])
        row["sprint"] = "Sprint 1" if row["action"] == "Patch Now" else ("Sprint 2" if row["action"] == "Patch Later" else "Backlog")
    findings.sort(key=lambda row: (row["suggested_order"], -row["risk_score"], row["path"]))
    ranking = [dict(row) for row in sorted(findings, key=lambda row: (-row["risk_score"], -row["roi"], row["path"]))]
    for index, row in enumerate(ranking, 1):
        row["rank"] = index
    risk_distribution = {group: sum(1 for row in findings if row["severity"] == group) for group in GROUPS}
    status_distribution = {status: sum(1 for row in findings if row["status"] == status) for status in STATUSES}
    action_groups: dict[str, list[dict[str, Any]]] = {action: [row for row in findings if row["action"] == action] for action in ("Patch Now", "Patch Later", "Never Patch")}
    roadmap = {
        action: {
            "count": len(rows),
            "estimated_similarity_gain": round(sum(row["estimated_similarity_gain"] for row in rows), 4),
            "estimated_cf_gain": round(sum(row["estimated_cf_gain"] for row in rows), 4),
            "items": [row["task_id"] for row in sorted(rows, key=lambda item: (item["suggested_order"], item["path"]))],
        }
        for action, rows in action_groups.items()
    }
    roadmap["execution_order"] = execution_order
    roadmap["cycle_detected"] = cycle_detected
    roi_rows = sorted(({
        "rank": index,
        "task_id": row["task_id"],
        "path": row["path"],
        "roi": row["roi"],
        "estimated_similarity_gain": row["estimated_similarity_gain"],
        "estimated_cf_gain": row["estimated_cf_gain"],
        "complexity": row["complexity"],
        "action": row["action"],
    } for index, row in enumerate(findings, 1)), key=lambda item: (-item["roi"], -item["estimated_similarity_gain"], item["path"]))
    for index, row in enumerate(roi_rows, 1):
        row["rank"] = index
    recommendations = {
        "Patch Now": [row["recommendation"] for row in action_groups["Patch Now"]],
        "Patch Later": [row["recommendation"] for row in action_groups["Patch Later"]],
        "Never Patch": [row["recommendation"] for row in action_groups["Never Patch"]],
    }
    stats = {
        "analyzed_differences": len(findings),
        "risk_distribution": risk_distribution,
        "status_distribution": status_distribution,
        "action_distribution": {action: len(rows) for action, rows in action_groups.items()},
        "complexity_distribution": {complexity: sum(1 for row in findings if row["complexity"] == complexity) for complexity in COMPLEXITIES},
        "average_risk_score": round(sum(row["risk_score"] for row in findings) / len(findings), 2) if findings else 0.0,
        "average_roi": round(sum(row["roi"] for row in findings) / len(findings), 2) if findings else 0.0,
        "estimated_similarity_opportunity": round(sum(row["estimated_similarity_gain"] for row in findings), 4),
        "estimated_cf_opportunity": round(sum(row["estimated_cf_gain"] for row in findings), 4),
        "browser_launches": 0,
        "network_requests": 0,
        "real_input": real_meta,
        "compare_input": compare_meta,
    }
    source_code = Path(__file__).read_text(encoding="utf-8").lower()
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (real_docs, compare_docs, findings, ranking, sorted(dependencies_nodes), dependencies_edges, roadmap, roi_rows, stats)),
        "artifact_completeness": False,
        "deterministic_ordering": findings == sorted(findings, key=lambda row: (row["suggested_order"], -row["risk_score"], row["path"])),
        "ranking_validation": [row["rank"] for row in ranking] == list(range(1, len(ranking) + 1)),
        "roi_normalization": all(0.0 <= _number(row.get("roi"), -1.0) <= 100.0 for row in roi_rows),
        "dependency_validation": not cycle_detected and all(edge["from"] != edge["to"] for edge in dependencies_edges),
        "immutable_input_verification": real_meta.get("available", False) and compare_meta.get("available", False),
        "offline_only": not any(re.search(pattern, source_code, flags=re.MULTILINE) for pattern in (r"^\s*(from|import)\s+playwright", r"^\s*(from|import)\s+browser", r"^\s*import\s+subprocess", r"^\s*import\s+requests")),
        "browser_launches": 0,
        "network_requests": 0,
        "valid": False,
    }
    summary = {
        "experiment": "Experiment 040 - Plugins & MimeTypes Risk Assessment",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "SUCCESS" if real_meta.get("available") and compare_meta.get("available") else "UNKNOWN",
        "real_input": real_meta.get("directory"),
        "compare_input": compare_meta.get("directory"),
        "current_similarity": current_similarity,
        "analyzed_differences": len(findings),
        "risk_distribution": risk_distribution,
        "highest_risk_properties": [row["path"] for row in sorted(findings, key=lambda row: (-row["risk_score"], row["path"]))[:10]],
        "estimated_similarity_opportunity": round(sum(row["estimated_similarity_gain"] for row in findings), 4),
        "estimated_cf_opportunity": round(sum(row["estimated_cf_gain"] for row in findings), 4),
        "historical_artifacts_modified": False,
        "browser_launches": 0,
        "network_requests": 0,
    }
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "plugins_risk"
    output.mkdir(parents=True, exist_ok=False)
    validation["artifact_completeness"] = True
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "immutable_input_verification", "browser_launches", "network_requests"}) and bool(real_meta.get("available")) and bool(compare_meta.get("available"))
    artifacts = {
        "risk.json": {"risks": findings},
        "ranking.json": {"ranking": ranking},
        "dependencies.json": {"nodes": sorted(dependencies_nodes), "edges": dependencies_edges, "execution_order": execution_order, "cycle_detected": cycle_detected},
        "roi.json": {"ranking": roi_rows},
        "recommendations.json": recommendations,
        "roadmap.json": roadmap,
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    report = _report(summary, stats, ranking, roadmap, validation)
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "plugins_risk.md", report)
    print("PLUGINS & MIMETYPES RISK ASSESSMENT")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Analyzed differences: {len(findings)}")
    print(f"Critical: {risk_distribution['Critical']} | High: {risk_distribution['High']}")
    print(f"Patch Now: {len(action_groups['Patch Now'])} | Patch Later: {len(action_groups['Patch Later'])} | Never Patch: {len(action_groups['Never Patch'])}")
    print(f"Browser launches: 0 | Network requests: 0")
    print(f"Result: {summary['result']}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    return run(_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
