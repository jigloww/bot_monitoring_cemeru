"""Comparison serialization and experiment summary rendering."""
from __future__ import annotations

import json

from typing import Any, Iterable

from tools.compare_fingerprint import DiffRecord

from experiments.metrics import ExperimentMetrics
from experiments.utils import json_compatible


FOCUS_CATEGORIES = [
    "Navigator",
    "Window",
    "Chrome",
    "Permissions",
    "Fonts",
    "Speech",
    "Battery",
    "Performance",
    "WebGL",
    "Screen",
]


def serialize_diffs(
    records: Iterable[DiffRecord],
    *,
    baseline_label: str,
    candidate_label: str,
) -> dict[str, Any]:
    """Serialize comparator records while preserving its existing semantics."""
    diffs = [
        {
            "key": record.key,
            "v1": record.v1,
            "v2": record.v2,
            "category": record.category,
            "recommendation": record.recommendation,
            "stars": record.stars,
            "missing_in": record.missing_in,
        }
        for record in records
        if not record.equal
    ]
    return {
        "label1": baseline_label,
        "label2": candidate_label,
        "diff_count": len(diffs),
        "diffs": diffs,
    }


def comparison_document(
    before_records: Iterable[DiffRecord],
    after_records: Iterable[DiffRecord],
    *,
    baseline_label: str,
) -> dict[str, Any]:
    """Combine the two comparator runs into the required compare.json."""
    return {
        "baseline": baseline_label,
        "before": serialize_diffs(
            before_records,
            baseline_label=baseline_label,
            candidate_label="fingerprint_before",
        ),
        "after": serialize_diffs(
            after_records,
            baseline_label=baseline_label,
            candidate_label="fingerprint_after",
        ),
    }


def _category_map(score: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item.get("category"): item
        for item in score.get("categories", [])
        if isinstance(item, dict) and isinstance(item.get("category"), str)
    }


def _focus_categories(
    score_before: dict[str, Any], score_after: dict[str, Any]
) -> list[dict[str, Any]]:
    before_map = _category_map(score_before)
    after_map = _category_map(score_after)
    rows = []
    for name in FOCUS_CATEGORIES:
        before_value = before_map.get(name, {}).get("score_pct")
        after_value = after_map.get(name, {}).get("score_pct")
        delta = None
        if before_value is not None and after_value is not None:
            delta = round(float(after_value) - float(before_value), 2)
        rows.append(
            {
                "category": name,
                "before": before_value,
                "after": after_value,
                "delta": delta,
            }
        )
    return rows


def build_summary(
    *,
    metadata: dict[str, Any],
    baseline: dict[str, Any],
    patch: dict[str, Any],
    comparison: dict[str, Any],
    score_before: dict[str, Any],
    score_after: dict[str, Any],
    validation: dict[str, Any],
    metrics: ExperimentMetrics,
) -> dict[str, Any]:
    """Build the canonical summary consumed by JSON, Markdown, and console views."""
    remaining = sorted(
        comparison["after"]["diffs"],
        key=lambda item: (-int(item.get("stars", 1)), item.get("category", ""), item["key"]),
    )[:20]
    return {
        "experiment_id": metadata["experiment_id"],
        "status": metadata["status"],
        "created_at": metadata["date"],
        "label": metadata.get("label"),
        "baseline": baseline,
        "patch": patch,
        "scores": {
            "overall_before": score_before.get("overall_score"),
            "overall_after": score_after.get("overall_score"),
            "cf_risk_before": score_before.get("cf_risk_score"),
            "cf_risk_after": score_after.get("cf_risk_score"),
        },
        "diffs": {
            "before": metrics.diff_count_before,
            "after": metrics.diff_count_after,
            "reduction": metrics.diff_reduction,
            "reduction_pct": metrics.diff_reduction_pct,
        },
        "patch_outcomes": {
            "targets": metrics.patch_target_count,
            "successful": metrics.patches_successful,
            "failed": metrics.patches_failed,
            "no_effect": metrics.patches_no_effect,
            "successful_keys": metrics.successful_patch_keys,
            "failed_keys": metrics.failed_patch_keys,
            "no_effect_keys": metrics.no_effect_patch_keys,
        },
        "improvement": {
            "overall_points": metrics.overall_improvement,
            "overall_pct": metrics.overall_improvement_pct,
            "cf_risk_points": metrics.cf_risk_improvement,
        },
        "keys": {
            "improved": metrics.improved_keys,
            "regressed": metrics.regressed_keys,
            "unchanged": metrics.unchanged_keys,
            "changed_but_remaining": metrics.changed_remaining_keys,
        },
        "top_20_remaining_differences": remaining,
        "top_categories": _focus_categories(score_before, score_after),
        "validation": validation,
        "metadata": metadata,
        "metric_definitions": metrics.to_dict()["definitions"],
    }


def _number(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return str(value)


def _key_section(title: str, keys: list[str], *, limit: int = 50) -> list[str]:
    lines = [f"## {title}", "", f"Count: **{len(keys)}**", ""]
    if not keys:
        return lines + ["- None", ""]
    lines.extend(f"- `{key}`" for key in keys[:limit])
    if len(keys) > limit:
        lines.extend([f"- ... and {len(keys) - limit} more (available in `summary.json`)", ""])
    else:
        lines.append("")
    return lines


def render_markdown(summary: dict[str, Any]) -> str:
    """Render the complete human-readable summary.md report."""
    scores = summary["scores"]
    diffs = summary["diffs"]
    patches = summary["patch_outcomes"]
    improvement = summary["improvement"]
    metadata = summary["metadata"]
    lines = [
        f"# Fingerprint Experiment {summary['experiment_id']}",
        "",
        f"- **Status:** {summary['status']}",
        f"- **Date:** {summary['created_at']}",
        f"- **Label:** {summary.get('label') or '-'}",
        f"- **URL:** `{metadata.get('url')}`",
        f"- **Baseline:** `{summary['baseline'].get('path')}`",
        f"- **Patch version:** `{summary['patch'].get('version')}`",
        "",
        "## Score Summary",
        "",
        "| Metric | Before | After | Delta |",
        "|---|---:|---:|---:|",
        f"| Overall Score | {_number(scores['overall_before'])}% | {_number(scores['overall_after'])}% | {_number(improvement['overall_points'])} pp |",
        f"| CF Risk | {_number(scores['cf_risk_before'])}% | {_number(scores['cf_risk_after'])}% | {_number(improvement['cf_risk_points'])} pp |",
        f"| Total Diffs | {diffs['before']} | {diffs['after']} | {diffs['reduction']} |",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Patch targets | {patches['targets']} |",
        f"| Patches successful | {patches['successful']} |",
        f"| Patches failed | {patches['failed']} |",
        f"| Patches with no effect | {patches['no_effect']} |",
        f"| Diff reduction | {diffs['reduction']} |",
        f"| Diff reduction percentage | {_number(diffs['reduction_pct'])}% |",
        f"| Overall improvement | {_number(improvement['overall_points'])} percentage points |",
        f"| Relative overall improvement | {_number(improvement['overall_pct'])}% |",
        "",
        "## Top Categories",
        "",
        "| Category | Before | After | Delta |",
        "|---|---:|---:|---:|",
    ]
    for row in summary["top_categories"]:
        lines.append(
            f"| {row['category']} | {_number(row['before'])}% | {_number(row['after'])}% | {_number(row['delta'])} pp |"
        )
    lines.append("")
    lines.extend(_key_section("Improved Keys", summary["keys"]["improved"]))
    lines.extend(_key_section("Regressed Keys", summary["keys"]["regressed"]))
    lines.extend(_key_section("Unchanged Keys", summary["keys"]["unchanged"]))
    lines.extend(["## Top 20 Remaining Differences", ""])
    remaining = summary["top_20_remaining_differences"]
    if not remaining:
        lines.extend(["- None", ""])
    else:
        lines.extend(
            [
                "| Priority | Category | Key | Reference | After |",
                "|---:|---|---|---|---|",
            ]
        )
        for item in remaining:
            ref_value = json.dumps(json_compatible(item.get("v1")), ensure_ascii=False)[:80]
            after_value = json.dumps(json_compatible(item.get("v2")), ensure_ascii=False)[:80]
            lines.append(
                f"| {item.get('stars', 1)} | {item.get('category', 'Other')} | "
                f"`{item['key']}` | `{ref_value}` | `{after_value}` |"
            )
        lines.append("")
    return "\n".join(lines)


def render_console(summary: dict[str, Any]) -> str:
    """Render a compact console report without terminal-specific dependencies."""
    scores = summary["scores"]
    diffs = summary["diffs"]
    patches = summary["patch_outcomes"]
    width = 68
    return "\n".join(
        [
            "=" * width,
            f"FINGERPRINT EXPERIMENT {summary['experiment_id']}",
            "=" * width,
            f"Overall score : {_number(scores['overall_before'])}% -> {_number(scores['overall_after'])}%",
            f"CF risk score  : {_number(scores['cf_risk_before'])}% -> {_number(scores['cf_risk_after'])}%",
            f"Total diffs    : {diffs['before']} -> {diffs['after']} ({diffs['reduction']:+d})",
            f"Improved keys  : {len(summary['keys']['improved'])}",
            f"Regressed keys : {len(summary['keys']['regressed'])}",
            f"Unchanged keys : {len(summary['keys']['unchanged'])}",
            f"Patch outcomes : {patches['successful']} successful / "
            f"{patches['failed']} failed / {patches['no_effect']} no effect",
            f"Output          : {summary['metadata']['output_directory']}",
            "=" * width,
        ]
    )

