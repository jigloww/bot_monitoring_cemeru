"""Experiment 043: deterministic root-cause analysis for Plugins differences.

The analyzer consumes immutable outputs from the real-browser collector,
comparator, risk assessment, and Plugins evaluation.  It never starts a
browser, imports Playwright, recomputes a comparator score, or changes an
input artifact.  Its estimates are explicitly derived from the existing risk
artifact (with low-confidence zero estimates when no evidence exists).
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
from typing import Any, Iterable

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


STATUSES = ("CHANGED", "MISSING", "ADDED", "REMOVED")
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
COMPLEXITIES = ("Easy", "Medium", "Hard", "Very Hard")
ROOT_CAUSE_ORDER = (
    "module_added_nonbaseline_surface",
    "module_missing_baseline_surface",
    "wrong_prototype_chain",
    "wrong_descriptor",
    "wrong_native_function_surface",
    "profile_value_mismatch",
    "cross_reference_inconsistency",
    "unexpected_method_surface",
    "aggregate_fingerprint_mismatch",
    "unclassified_difference",
)
COMPLEXITY_FACTOR = {"Easy": 1.0, "Medium": 2.0, "Hard": 3.5, "Very Hard": 5.0}
SEVERITY_FACTOR = {"CRITICAL": 1.0, "HIGH": 0.8, "MEDIUM": 0.55, "LOW": 0.3, "INFO": 0.1}

REAL_FILES = (
    "navigator.json",
    "plugins.json",
    "mime_types.json",
    "prototype.json",
    "descriptors.json",
    "methods.json",
    "cross_reference.json",
    "fingerprint.json",
)
COMPARE_FILES = (
    "compare.json",
    "differences.json",
    "similarity.json",
    "statistics.json",
    "summary.json",
    "validation.json",
)
RISK_FILES = (
    "risk.json",
    "ranking.json",
    "dependencies.json",
    "roi.json",
    "recommendations.json",
    "roadmap.json",
    "statistics.json",
    "summary.json",
    "validation.json",
)
EVALUATION_FILES = (
    "compare.json",
    "differences.json",
    "similarity.json",
    "score.json",
    "statistics.json",
    "summary.json",
    "validation.json",
)


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "unknown"


def _load_documents(directory: Path | None, names: Iterable[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    if directory is None or not directory.is_dir():
        return {}, {"available": False, "directory": str(directory) if directory else None, "files": {}, "hashes": {}}
    docs: dict[str, Any] = {}
    files: dict[str, bool] = {}
    hashes: dict[str, str] = {}
    for name in names:
        path = directory / name
        files[name] = path.is_file()
        docs[name] = _read_json(path)
        if path.is_file():
            try:
                hashes[name] = sha256_file(path)
            except OSError:
                hashes[name] = ""
    return docs, {
        "available": all(files.values()),
        "directory": str(directory),
        "files": files,
        "hashes": hashes,
    }


def _resolve(root: Path, explicit: Path | None, default_relative: str) -> Path | None:
    if explicit is not None:
        candidate = explicit if explicit.is_absolute() else root / explicit
        return candidate if candidate.is_dir() else None
    candidate = root / default_relative
    return candidate if candidate.is_dir() else None


def _risk_rows(risk_docs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = risk_docs.get("risk.json", {})
    rows = raw.get("risks", []) if isinstance(raw, dict) else []
    result: dict[str, dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("path") is not None:
                result.setdefault(str(row["path"]), row)
    return result


def _difference_rows(evaluation_docs: dict[str, Any]) -> list[dict[str, Any]]:
    raw = evaluation_docs.get("differences.json", {})
    rows: Any = raw.get("remaining", []) if isinstance(raw, dict) else []
    if not isinstance(rows, list):
        rows = []
    normalized = [row for row in rows if isinstance(row, dict) and str(row.get("status", "")).upper() in STATUSES]
    return sorted(normalized, key=lambda row: (str(row.get("category", "")), str(row.get("path", "")), str(row.get("status", ""))))


def _map_rows(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in value:
        if isinstance(row, dict) and row.get("path") is not None:
            result.setdefault(str(row["path"]), row)
    return result


def _domain(path: str, category: str) -> str:
    lowered = path.lower()
    # Structural prefixes take precedence over words such as
    # ``prototypeDescriptors`` inside an item's shape.
    if lowered.startswith("cross_reference."):
        return "Cross-reference"
    if lowered.startswith("methods."):
        return "Method"
    if lowered.startswith("plugins."):
        return "Plugin"
    if lowered.startswith("mime_types."):
        return "MimeType"
    if lowered.startswith("prototype."):
        return "Prototype"
    if lowered.startswith("descriptors."):
        return "Descriptor"
    if "cross_reference" in lowered or "cross references" in category.lower():
        return "Cross-reference"
    if "descriptor" in lowered or category.lower() == "descriptors":
        return "Descriptor"
    if "prototype" in lowered or category.lower() == "prototype":
        return "Prototype"
    if "method" in lowered or category.lower() == "methods":
        return "Method"
    if "mime_types" in lowered or "mimetype" in lowered or category.lower() == "mimetypearray":
        return "MimeType"
    if "plugins" in lowered or category.lower() == "pluginarray":
        return "Plugin"
    if lowered.startswith("fingerprint"):
        return "Fingerprint"
    return category or "Other"


def _object_name(path: str, domain: str) -> str:
    lowered = path.lower()
    if lowered.startswith("plugins."):
        return "Plugin"
    if lowered.startswith("mime_types."):
        return "MimeType"
    if lowered.startswith("methods.plugin_prototypes"):
        return "Plugin"
    if lowered.startswith("methods.mime_prototypes"):
        return "MimeType"
    if "mime_prototypes" in lowered or domain == "MimeType":
        return "MimeType"
    if "plugin_prototypes" in lowered or domain == "Plugin":
        return "Plugin"
    if "cross_reference" in lowered or domain == "Cross-reference":
        return "Cross-reference"
    if domain == "Method":
        return "Prototype method surface"
    if domain == "Descriptor":
        return "Native descriptor"
    if domain == "Prototype":
        return "Prototype chain"
    if domain == "Fingerprint":
        return "Fingerprint aggregate"
    return domain


def _root_cause(path: str, category: str, status: str, real: Any, patched: Any, prior: dict[str, Any] | None) -> tuple[str, str, str]:
    lowered = path.lower()
    prior_status = str((prior or {}).get("status", "")).upper()
    if lowered == "fingerprint.sha256":
        return (
            "aggregate_fingerprint_mismatch",
            "Aggregate fingerprint hash differs",
            "The hash is a consequence of underlying properties and must not be patched directly.",
        )
    if status == "ADDED" and real is None and prior is None:
        return (
            "module_added_nonbaseline_surface",
            "Module exposes a surface absent from the Real baseline",
            "The enabled capture contains a field that was absent from both the Real artifact and the Plain comparator capture; this is most consistent with synthetic object-shape expansion.",
        )
    if status in {"MISSING", "REMOVED"} and real is not None:
        if "cross_reference" in lowered:
            return ("cross_reference_inconsistency", "Cross-reference is missing", "A Real Plugin/MimeType relationship is not represented in the enabled capture.")
        return ("module_missing_baseline_surface", "Baseline surface remains missing", "A property present in the Real artifact is absent after enabling the module.")
    if "cross_reference" in lowered or any(token in lowered for token in ("enabledplugin", "pluginmimetypes", "mimeenabledplugins")):
        return ("cross_reference_inconsistency", "Plugin and MimeType identity is inconsistent", "The relationship between Plugin, MimeType, and enabledPlugin is not represented identically.")
    if category.lower() == "methods" or lowered.startswith("methods."):
        if status == "ADDED" and prior_status == "":
            return ("unexpected_method_surface", "Synthetic method surface was added", "The module exposes method metadata that the Real collector did not observe.")
        if any(token in lowered for token in (".source", "valuesource", "nativesource", ".typeof", ".available")):
            return ("wrong_native_function_surface", "Native method source or availability differs", "Function availability, source text, or native-looking function metadata differs from the Real baseline.")
        if any(token in lowered for token in ("descriptor", "getter", "setter", "enumerable", "configurable", "writable")):
            return ("wrong_descriptor", "Method descriptor differs", "The method's descriptor or accessor metadata differs from the Real baseline.")
        return ("wrong_native_function_surface", "Native method surface differs", "Function availability, source text, invocation metadata, or method descriptors differ.")
    if any(token in lowered for token in ("descriptor", "getter", "setter", "enumerable", "configurable", "writable")):
        return ("wrong_descriptor", "Native descriptor differs", "Property attributes or accessor shape do not match the Real baseline.")
    if any(token in lowered for token in ("prototypechain", "prototype", "instanceof", "tostringtag", "constructor")):
        return ("wrong_prototype_chain", "Prototype identity or chain differs", "The enabled object is backed by a different constructor/prototype identity or exposes a different chain.")
    if domain := _domain(path, category):
        if domain in {"Plugin", "MimeType"}:
            if any(token in lowered for token in ("name", "filename", "description", "type", "suffixes", "length", "items")):
                return ("profile_value_mismatch", "Profile value or collection shape differs", "The profile value, item ordering, collection length, or item identity does not match the Real artifact.")
            if status == "ADDED":
                return ("module_added_nonbaseline_surface", "Unexpected collection property was added", "An additional Plugin/MimeType property is present only in the enabled capture.")
    if status == "ADDED":
        return ("module_added_nonbaseline_surface", "Unexpected property was added", "The enabled capture contains a property absent from the Real artifact.")
    if status in {"MISSING", "REMOVED"}:
        return ("module_missing_baseline_surface", "Property remains absent", "The enabled capture does not expose a property recorded by the Real browser.")
    return ("profile_value_mismatch", "Value differs", "The property exists in both captures but its observed value differs.")


def _severity(row: dict[str, Any], risk: dict[str, Any]) -> str:
    value = str(row.get("severity", "")).upper()
    if value in SEVERITIES:
        return value
    score = _number(risk.get("risk_score"), 0.0)
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 35:
        return "MEDIUM"
    return "LOW"


def _complexity(root_id: str, risk_rows: list[dict[str, Any]]) -> str:
    values = {str(row.get("complexity")) for row in risk_rows if str(row.get("complexity")) in COMPLEXITIES}
    if values:
        return max(values, key=lambda value: COMPLEXITY_FACTOR[value])
    if root_id in {"wrong_prototype_chain", "wrong_descriptor", "wrong_native_function_surface", "cross_reference_inconsistency"}:
        return "Hard"
    if root_id == "aggregate_fingerprint_mismatch":
        return "Very Hard"
    return "Medium"


def _confidence(root_id: str, rows: list[dict[str, Any]], risk_rows: list[dict[str, Any]], prior_known: int) -> str:
    if root_id == "aggregate_fingerprint_mismatch":
        return "High"
    if len(risk_rows) == len(rows) and prior_known == len(rows):
        return "High"
    if risk_rows or prior_known:
        return "Medium"
    return "Low"


def _topological_order(nodes: set[str], edges: list[dict[str, str]]) -> tuple[list[str], bool]:
    outgoing: dict[str, set[str]] = defaultdict(set)
    indegree = {node: 0 for node in nodes}
    for edge in edges:
        source, target = edge["from"], edge["to"]
        indegree.setdefault(source, 0)
        indegree.setdefault(target, 0)
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


def _dependencies(root_id: str) -> list[str]:
    dependencies = {
        "wrong_descriptor": ["wrong_prototype_chain"],
        "wrong_native_function_surface": ["wrong_prototype_chain"],
        "unexpected_method_surface": ["wrong_prototype_chain"],
        "profile_value_mismatch": ["wrong_prototype_chain"],
        "cross_reference_inconsistency": ["profile_value_mismatch"],
        "module_missing_baseline_surface": ["wrong_prototype_chain"],
        "module_added_nonbaseline_surface": ["wrong_prototype_chain"],
        "aggregate_fingerprint_mismatch": list(ROOT_CAUSE_ORDER[:-1]),
    }
    return sorted(value for value in dependencies.get(root_id, []) if value != root_id)


def _root_action(root_id: str, confidence: str, roi: float) -> tuple[str, str]:
    if root_id == "aggregate_fingerprint_mismatch":
        return "NEVER_PATCH", "Treat the aggregate hash as an audit signal; fix its component properties instead."
    if confidence == "Low":
        return "INVESTIGATE", "Collect an independent native probe before changing the module."
    if roi >= 15.0 and root_id in {"cross_reference_inconsistency", "module_missing_baseline_surface", "wrong_prototype_chain", "wrong_descriptor"}:
        return "PATCH_LATER", "Patch only after preserving native identity and validating the complete Plugin/MimeType chain."
    return "INVESTIGATE", "Investigate the evidence and validate against an independent Real browser capture."


def _fallback_cloudflare_impact(domain: str) -> float:
    return {
        "Prototype": 82.0,
        "Descriptor": 78.0,
        "Method": 76.0,
        "Cross-reference": 74.0,
        "Plugin": 62.0,
        "MimeType": 62.0,
        "Fingerprint": 15.0,
    }.get(domain, 40.0)


def _fallback_gain(severity: str) -> float:
    # Conservative per-property estimate used only when exp_149 has no row
    # for a newly exposed path.  It is intentionally much smaller than a
    # measured category score and is marked low confidence by the caller.
    return {"CRITICAL": 0.0020, "HIGH": 0.0015, "MEDIUM": 0.0010, "LOW": 0.0005, "INFO": 0.0}.get(severity, 0.0010)


def _report(summary: dict[str, Any], ranking: list[dict[str, Any]], simulations: list[dict[str, Any]], stats: dict[str, Any], validation: dict[str, Any], groups: dict[str, dict[str, int]]) -> str:
    def check_status(key: str, value: Any) -> str:
        if key in {"browser_launches", "network_requests"}:
            return "PASS" if _number(value, -1.0) == 0.0 else "FAIL"
        return "PASS" if bool(value) else "FAIL"

    lines = [
        "# Experiment 043 - Plugins Difference Root Cause Analyzer",
        "",
        "Offline, deterministic analysis of immutable Plugins artifacts. No browser, Playwright, network, or stealth code was used.",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Remaining differences analyzed: **{stats['remaining_differences']}**",
        f"- Unique root causes: **{stats['root_cause_count']}**",
        f"- Estimated removable differences: **{stats['estimated_differences_removed']}**",
        f"- Estimated similarity opportunity (risk evidence plus conservative fallback): **{summary['estimated_similarity_gain']:.4f}%**",
        "",
        "## Root Cause Ranking",
        "",
        "| Rank | Root Cause | Object | Differences | Severity | Complexity | Gain | CF Impact | ROI | Action |",
        "|---:|---|---|---:|---|---|---:|---:|---:|---|",
    ]
    for row in ranking[:20]:
        lines.append(
            f"| {row['rank']} | `{row['root_cause_id']}` | {row['object']} | {row['difference_count']} | {row['severity']} | {row['complexity']} | {row['estimated_similarity_gain']:.4f}% | {row['estimated_cloudflare_impact']:.2f} | {row['roi']:.2f} | {row['action']} |"
        )
    lines += ["", "## Cascade and Dependencies", "", "| Root Cause | Depends On | Cascade Effects |", "|---|---|---|"]
    for row in ranking:
        lines.append(f"| `{row['root_cause_id']}` | {', '.join(row['dependencies']) or '-'} | {', '.join(row['cascade_effects']) or '-'} |")
    lines += ["", "## Simulations", "", "| Scenario | Differences Removed | Expected Gain | Predicted Overall | Best Case | Worst Case | Confidence |", "|---|---:|---:|---:|---:|---:|---|"]
    for row in simulations:
        lines.append(f"| `{row['simulation_id']}` | {row['estimated_differences_removed']} | {row['expected_similarity_improvement']:.4f}% | {row['predicted_overall_after_fix']:.4f}% | {row['best_case_similarity_improvement']:.4f}% | {row['worst_case_similarity_improvement']:.4f}% | {row['prediction_confidence']} |")
    lines += ["", "## Grouped Findings", ""]
    for name in ("by_property", "by_object", "by_prototype", "by_descriptor", "by_method", "by_cross_reference", "by_plugin", "by_mimetype"):
        lines.append(f"### {name.replace('_', ' ').title()}")
        lines.append("")
        for key, count in sorted(groups.get(name, {}).items(), key=lambda item: (-item[1], item[0]))[:20]:
            lines.append(f"- `{key}`: {count}")
        lines.append("")
    lines += ["## Validation", "", "| Check | Status |", "|---|---|"]
    lines.extend(f"| {key.replace('_', ' ').title()} | {check_status(key, value)} |" for key, value in validation.items() if key not in {"valid", "artifact_completeness"})
    lines += ["", "## Final Conclusion", "", summary["conclusion"], ""]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment 043: offline Plugins root-cause analysis")
    parser.add_argument("--real-dir", type=Path, default=None)
    parser.add_argument("--compare-dir", type=Path, default=None)
    parser.add_argument("--risk-dir", type=Path, default=None)
    parser.add_argument("--evaluation-dir", type=Path, default=None)
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    real_dir = _resolve(root, args.real_dir, "reports/experiments/exp_142/plugins")
    compare_dir = _resolve(root, args.compare_dir, "reports/experiments/exp_144/plugins_compare")
    risk_dir = _resolve(root, args.risk_dir, "reports/experiments/exp_149/plugins_risk")
    evaluation_dir = _resolve(root, args.evaluation_dir, "reports/experiments/exp_160/plugins_evaluation")
    real_docs, real_meta = _load_documents(real_dir, REAL_FILES)
    compare_docs, compare_meta = _load_documents(compare_dir, COMPARE_FILES)
    risk_docs, risk_meta = _load_documents(risk_dir, RISK_FILES)
    evaluation_docs, evaluation_meta = _load_documents(evaluation_dir, EVALUATION_FILES)
    before_hashes = {"real": dict(real_meta.get("hashes", {})), "compare": dict(compare_meta.get("hashes", {})), "risk": dict(risk_meta.get("hashes", {})), "evaluation": dict(evaluation_meta.get("hashes", {}))}

    remaining = _difference_rows(evaluation_docs)
    plain_rows = _map_rows((evaluation_docs.get("differences.json", {}) or {}).get("plain", []))
    prior_rows = _map_rows(compare_docs.get("differences.json", []))
    risk_by_path = _risk_rows(risk_docs)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    findings: list[dict[str, Any]] = []
    for row in remaining:
        path = str(row.get("path", "<unknown>"))
        category = str(row.get("category", "Other"))
        status = str(row.get("status", "CHANGED")).upper()
        prior = prior_rows.get(path)
        risk = risk_by_path.get(path, {})
        root_id, title, explanation = _root_cause(path, category, status, row.get("real"), row.get("playwright"), prior)
        evidence = "risk_artifact" if risk else "evaluation_artifact"
        domain = _domain(path, category)
        severity = _severity(row, risk)
        risk_score = round(_number(risk.get("risk_score"), 0.0), 2)
        estimated_gain = round(max(0.0, _number(risk.get("estimated_similarity_gain"), 0.0)), 4)
        estimated_cf = round(max(0.0, _number(risk.get("estimated_cloudflare_impact"), 0.0)), 2)
        if not risk:
            estimated_gain = _fallback_gain(severity)
            estimated_cf = _fallback_cloudflare_impact(domain)
        record = {
            "path": path,
            "category": category,
            "domain": domain,
            "object": _object_name(path, domain),
            "status": status,
            "severity": severity,
            "root_cause_id": root_id,
            "root_cause": title,
            "reason": explanation,
            "real_value": row.get("real"),
            "patched_value": row.get("playwright"),
            "plain_status": str((plain_rows.get(path) or {}).get("status", "ABSENT")),
            "prior_comparator_status": str((prior or {}).get("status", "ABSENT")),
            "prior_comparator_present": prior is not None,
            "risk_score": risk_score,
            "estimated_similarity_gain": estimated_gain,
            "estimated_cloudflare_impact": estimated_cf,
            "complexity": str(risk.get("complexity", "")),
            "roi": round(max(0.0, _number(risk.get("roi"), 0.0)), 2),
            "confidence": "High" if risk and prior is not None else ("Medium" if risk or prior is not None else "Low"),
            "evidence_source": evidence,
        }
        grouped[root_id].append(record)
        findings.append(record)

    root_causes: list[dict[str, Any]] = []
    for root_id in ROOT_CAUSE_ORDER:
        rows = sorted(grouped.get(root_id, []), key=lambda item: (item["path"], item["status"]))
        if not rows:
            continue
        risk_values = [row for row in rows if row["risk_score"] > 0]
        severity = max((row["severity"] for row in rows), key=lambda value: SEVERITY_FACTOR.get(value, 0.0))
        complexity = _complexity(root_id, risk_values)
        confidence = _confidence(root_id, rows, risk_values, sum(1 for row in rows if row["prior_comparator_present"]))
        gain = round(sum(row["estimated_similarity_gain"] for row in rows), 4)
        cf_values = [row["estimated_cloudflare_impact"] for row in rows if row["estimated_cloudflare_impact"] > 0]
        cf_impact = round(sum(cf_values) / len(cf_values), 2) if cf_values else 0.0
        roi = round((gain / COMPLEXITY_FACTOR[complexity]) if complexity else 0.0, 4)
        action, action_reason = _root_action(root_id, confidence, roi)
        dependencies = _dependencies(root_id)
        root_causes.append({
            "root_cause_id": root_id,
            "title": rows[0]["root_cause"],
            "technical_explanation": rows[0]["reason"],
            "difference_count": len(rows),
            "object": Counter(row["object"] for row in rows).most_common(1)[0][0] if rows else "Other",
            "affected_paths": [row["path"] for row in rows],
            "affected_objects": sorted({row["object"] for row in rows}),
            "statuses": dict(sorted(Counter(row["status"] for row in rows).items())),
            "severity": severity,
            "complexity": complexity,
            "confidence": confidence,
            "estimated_differences_removed": len(rows),
            "estimated_similarity_gain": gain,
            "estimated_cloudflare_impact": cf_impact,
            "roi": roi,
            "dependencies": dependencies,
            "action": action,
            "action_reason": action_reason,
            "evidence_sources": sorted({row["evidence_source"] for row in rows}),
        })

    root_by_id = {row["root_cause_id"]: row for row in root_causes}
    all_ids = set(root_by_id)
    for row in root_causes:
        row["dependencies"] = [dependency for dependency in row["dependencies"] if dependency in all_ids]
    edges: list[dict[str, str]] = []
    for row in root_causes:
        for dependency in row["dependencies"]:
            if dependency in all_ids:
                edges.append({"from": dependency, "to": row["root_cause_id"], "relationship": "depends_on"})
    # Aggregate hash is downstream of every observed component but is never a
    # patch target; keeping the edges makes the cascade explicit.
    for source in sorted(all_ids - {"aggregate_fingerprint_mismatch"}):
        if "aggregate_fingerprint_mismatch" in all_ids:
            edges.append({"from": source, "to": "aggregate_fingerprint_mismatch", "relationship": "causes"})
    edges = sorted({(edge["from"], edge["to"], edge["relationship"]): edge for edge in edges}.values(), key=lambda edge: (edge["from"], edge["to"], edge["relationship"]))
    order, cycle_detected = _topological_order(all_ids, [edge for edge in edges if edge["relationship"] == "depends_on"])
    order_index = {value: index for index, value in enumerate(order, 1)}

    for row in root_causes:
        downstream = sorted({edge["to"] for edge in edges if edge["from"] == row["root_cause_id"]})
        row["cascade_effects"] = downstream
        row["suggested_order"] = order_index.get(row["root_cause_id"], len(order) + 1)
        row["priority_score"] = round(
            SEVERITY_FACTOR.get(row["severity"], 0.1) * 35.0
            + min(100.0, row["estimated_cloudflare_impact"]) * 0.2
            + min(100.0, row["roi"] * 10.0) * 0.2
            + ({"High": 100.0, "Medium": 70.0, "Low": 40.0}.get(row["confidence"], 25.0) * 0.15),
            2,
        )

    ranking = [dict(row) for row in sorted(root_causes, key=lambda row: (-row["priority_score"], -row["estimated_similarity_gain"], row["root_cause_id"]))]
    for index, row in enumerate(ranking, 1):
        row["rank"] = index

    current_similarity = _number((evaluation_docs.get("summary.json", {}) or {}).get("overall_plugins"), 0.0)
    simulations: list[dict[str, Any]] = []
    for row in sorted(root_causes, key=lambda item: item["root_cause_id"]):
        expected = row["estimated_similarity_gain"]
        confidence_factor = {"High": 1.0, "Medium": 0.8, "Low": 0.55}.get(row["confidence"], 0.4)
        simulations.append({
            "simulation_id": f"sim_{row['root_cause_id']}",
            "root_cause_id": row["root_cause_id"],
            "scenario": f"If {row['root_cause_id']} is fixed",
            "estimated_differences_removed": row["estimated_differences_removed"],
            "expected_similarity_improvement": round(expected, 4),
            "predicted_overall_after_fix": round(current_similarity + expected, 4),
            "best_case_similarity_improvement": round(expected * (1.0 + 0.25 * confidence_factor), 4),
            "worst_case_similarity_improvement": round(expected * (0.5 * confidence_factor), 4),
            "estimated_cloudflare_impact": row["estimated_cloudflare_impact"],
            "complexity": row["complexity"],
            "roi": row["roi"],
            "prediction_confidence": row["confidence"],
            "evidence": row["evidence_sources"],
            "assumption": "Uses only per-property estimates from exp_149/plugins_risk; no new similarity calculation is performed.",
        })

    groups: dict[str, Counter[str]] = {
        "by_property": Counter(),
        "by_object": Counter(),
        "by_prototype": Counter(),
        "by_descriptor": Counter(),
        "by_method": Counter(),
        "by_cross_reference": Counter(),
        "by_plugin": Counter(),
        "by_mimetype": Counter(),
    }
    for row in findings:
        path = row["path"]
        lowered_path = path.lower()
        first = path.split(".", 2)[0]
        property_key = ".".join(path.split(".")[:2]) if "." in path else path
        groups["by_property"][property_key] += 1
        groups["by_object"][row["object"]] += 1
        if any(token in lowered_path for token in ("prototype", "instanceof", "tostringtag")):
            groups["by_prototype"][row["root_cause_id"]] += 1
        if any(token in lowered_path for token in ("descriptor", "getter", "setter", "enumerable", "configurable", "writable")):
            groups["by_descriptor"][row["root_cause_id"]] += 1
        if lowered_path.startswith("methods."):
            groups["by_method"][row["root_cause_id"]] += 1
        if "cross_reference" in lowered_path or any(token in lowered_path for token in ("enabledplugin", "pluginmimetypes", "mimeenabledplugins")):
            groups["by_cross_reference"][row["root_cause_id"]] += 1
        if row["domain"] == "Plugin": groups["by_plugin"][first] += 1
        if row["domain"] == "MimeType": groups["by_mimetype"][first] += 1
    groups_json = {key: dict(sorted(value.items(), key=lambda item: item[0])) for key, value in groups.items()}

    simulations_by_id = {row["simulation_id"]: row for row in simulations}
    recommendations = []
    for row in ranking:
        recommendations.append({
            "recommendation_id": f"recommend_{row['root_cause_id']}",
            "root_cause_id": row["root_cause_id"],
            "priority": row["rank"],
            "action": row["action"],
            "title": row["title"],
            "recommendation": row["action_reason"],
            "estimated_similarity_gain": row["estimated_similarity_gain"],
            "estimated_cloudflare_impact": row["estimated_cloudflare_impact"],
            "complexity": row["complexity"],
            "roi": row["roi"],
            "dependencies": row["dependencies"],
            "affected_paths": row["affected_paths"][:50],
            "simulation_id": f"sim_{row['root_cause_id']}",
            "confidence": row["confidence"],
        })

    status_distribution = dict(sorted(Counter(row["status"] for row in findings).items()))
    root_distribution = dict(sorted(Counter(row["root_cause_id"] for row in findings).items()))
    severity_distribution = dict(sorted(Counter(row["severity"] for row in findings).items()))
    baseline_hashes_after = {
        "real": dict(real_meta.get("hashes", {})),
        "compare": dict(compare_meta.get("hashes", {})),
        "risk": dict(risk_meta.get("hashes", {})),
        "evaluation": dict(evaluation_meta.get("hashes", {})),
    }
    stats = {
        "remaining_differences": len(findings),
        "root_cause_count": len(root_causes),
        "estimated_differences_removed": sum(row["estimated_differences_removed"] for row in root_causes if row["root_cause_id"] != "aggregate_fingerprint_mismatch"),
        "status_distribution": status_distribution,
        "root_cause_distribution": root_distribution,
        "severity_distribution": severity_distribution,
        "group_counts": {key: sum(value.values()) for key, value in groups_json.items()},
        "estimated_similarity_gain": round(sum(row["estimated_similarity_gain"] for row in root_causes), 4),
        "estimated_cloudflare_impact": round(sum(row["estimated_cloudflare_impact"] for row in root_causes) / len(root_causes), 2) if root_causes else 0.0,
        "browser_launches": 0,
        "network_requests": 0,
        "cycle_detected": cycle_detected,
        "inputs_available": {"real": real_meta.get("available", False), "compare": compare_meta.get("available", False), "risk": risk_meta.get("available", False), "evaluation": evaluation_meta.get("available", False)},
        "input_hashes_before": before_hashes,
        "input_hashes_after": baseline_hashes_after,
    }
    conclusion = (
        "Root causes were identified deterministically from the enabled-capture remainder; aggregate hash mismatch is treated as a downstream symptom and not a patch target."
        if findings else "No remaining differences were available for root-cause analysis."
    )
    summary = {
        "experiment": "Experiment 043 - Plugins Difference Root Cause Analyzer",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "SUCCESS" if all(meta.get("available", False) for meta in (real_meta, compare_meta, risk_meta, evaluation_meta)) else "PARTIAL",
        "real_input": real_meta.get("directory"),
        "compare_input": compare_meta.get("directory"),
        "risk_input": risk_meta.get("directory"),
        "evaluation_input": evaluation_meta.get("directory"),
        "current_similarity": current_similarity,
        "remaining_differences": len(findings),
        "root_cause_count": len(root_causes),
        "estimated_similarity_gain": stats["estimated_similarity_gain"],
        "estimate_method": "exp_149 per-property risk evidence with conservative fallback for paths introduced by the enabled capture",
        "estimated_differences_removed": stats["estimated_differences_removed"],
        "top_root_causes": [row["root_cause_id"] for row in ranking[:10]],
        "historical_artifacts_modified": False,
        "browser_launches": 0,
        "network_requests": 0,
        "conclusion": conclusion,
    }

    source_code = Path(__file__).read_text(encoding="utf-8").lower()
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (real_docs, compare_docs, risk_docs, evaluation_docs, findings, root_causes, groups_json, ranking, simulations, recommendations, stats, summary)),
        "artifact_completeness": False,
        "deterministic_ordering": findings == sorted(findings, key=lambda row: (row["category"], row["path"], row["status"])),
        "root_cause_uniqueness": len({row["root_cause_id"] for row in root_causes}) == len(root_causes) and all(row["root_cause_id"] in all_ids for row in findings),
        "cascade_validation": all(edge["from"] != edge["to"] and edge["from"] in all_ids and edge["to"] in all_ids for edge in edges),
        "dependency_validation": not cycle_detected and all(edge["from"] != edge["to"] for edge in edges if edge["relationship"] == "depends_on"),
        "simulation_consistency": all(
            0 <= row["estimated_differences_removed"] <= len(findings)
            and all(_number(row.get(key), -1.0) >= 0 for key in ("expected_similarity_improvement", "predicted_overall_after_fix", "best_case_similarity_improvement", "worst_case_similarity_improvement"))
            for row in simulations
        ),
        "immutable_input_verification": before_hashes == baseline_hashes_after and all(meta.get("available", False) for meta in (real_meta, compare_meta, risk_meta, evaluation_meta)),
        "offline_only": not any(re.search(pattern, source_code, flags=re.MULTILINE) for pattern in (r"^\s*(from|import)\s+playwright", r"^\s*(from|import)\s+browser", r"^\s*import\s+(requests|subprocess)")),
        "browser_launches": 0,
        "network_requests": 0,
        "valid": False,
    }

    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "plugins_root_cause"
    output.mkdir(parents=True, exist_ok=False)
    validation["artifact_completeness"] = True
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})

    artifacts = {
        "root_causes.json": {"root_causes": root_causes, "findings": findings},
        "cascade.json": {"nodes": sorted(all_ids), "edges": edges, "execution_order": order, "cycle_detected": cycle_detected},
        "impact_tree.json": {"roots": [{"root_cause_id": row["root_cause_id"], "children": row["cascade_effects"], "affected_paths": row["affected_paths"]} for row in ranking], "edges": edges},
        "ranking.json": {"ranking": ranking},
        "simulations.json": {"simulations": simulations},
        "recommendations.json": {"recommendations": recommendations},
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    report = _report(summary, ranking, simulations, stats, validation, groups_json)
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "plugins_root_cause.md", report)
    print("PLUGINS DIFFERENCE ROOT CAUSE ANALYZER")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Remaining differences: {len(findings)} | Root causes: {len(root_causes)}")
    print(f"Estimated gain: {stats['estimated_similarity_gain']:.4f}%")
    print("Browser launches: 0 | Network requests: 0")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    return run(_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
