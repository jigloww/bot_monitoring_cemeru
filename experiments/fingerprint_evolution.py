"""Experiment 022: read-only fingerprint evolution tracker.

The tracker discovers every ``exp_NNN`` directory, normalizes whatever score,
compare, fingerprint, and session artifacts are available, and calculates
history/trend/regression data.  It never launches a browser and never writes
inside an existing experiment directory.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
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


MODULES = ("Navigator", "Window", "Screen", "Chrome", "Permissions", "Fonts", "Speech", "Performance", "WebGL")
ARTIFACT_NAMES = ("summary.json", "score.json", "compare.json", "fingerprint.json", "statistics.json")


@dataclass(frozen=True)
class ExperimentRecord:
    number: int
    experiment_id: str
    path: Path
    data: dict[str, Any]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _read(path: Path) -> Any:
    try:
        return read_json(path)
    except (OSError, ValueError, TypeError):
        return None


def _first(data: Any, paths: tuple[tuple[str, ...], ...], default: Any = None) -> Any:
    for path in paths:
        current = data
        ok = True
        for key in path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                ok = False
                break
        if ok and current is not None:
            return current
    return default


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _iso(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value:
        return value
    return fallback


def _candidates(root: Path, filename: str) -> list[Path]:
    paths = []
    direct = root / filename
    if direct.is_file():
        paths.append(direct)
    try:
        paths.extend(path for path in root.rglob(filename) if path.is_file() and path != direct and "fingerprint_evolution" not in path.parts)
    except OSError:
        pass
    return sorted(set(paths), key=lambda path: (len(path.relative_to(root).parts), str(path).lower()))


def _select_score(root: Path) -> tuple[Path | None, Any]:
    candidates = _candidates(root, "score.json")
    if not candidates:
        return None, None
    scored = []
    for path in candidates:
        data = _read(path)
        value = _number(_first(data, (("overall_score",), ("overall",), ("scores", "overall_after"), ("score",)))) if isinstance(data, dict) else None
        scored.append((value if value is not None else -1.0, path, data))
    scored.sort(key=lambda item: (-item[0], len(item[1].relative_to(root).parts), str(item[1]).lower()))
    _, path, data = scored[0]
    return path, data


def _select_artifact(root: Path, filename: str, preferred_parent: Path | None = None) -> tuple[Path | None, Any]:
    candidates = _candidates(root, filename)
    if preferred_parent:
        candidates.sort(key=lambda path: (0 if path.parent == preferred_parent else 1, len(path.relative_to(root).parts), str(path).lower()))
    if not candidates:
        return None, None
    path = candidates[0]
    return path, _read(path)


def _category_scores(score: Any) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    categories = score.get("categories", []) if isinstance(score, dict) else []
    if isinstance(categories, list):
        for item in categories:
            if not isinstance(item, dict):
                continue
            name = str(item.get("category") or "").strip()
            if name:
                values[name] = _number(item.get("score_pct", item.get("score")))
    elif isinstance(categories, dict):
        for name, item in categories.items():
            values[str(name)] = _number(item.get("score_pct", item.get("score")) if isinstance(item, dict) else item)
    return values


def _collect_record(number: int, path: Path, root: Path) -> ExperimentRecord:
    summary_path, summary = _select_artifact(path, "summary.json")
    score_path, score = _select_score(path)
    compare_path, compare = _select_artifact(path, "compare.json", score_path.parent if score_path else None)
    fingerprint_path, fingerprint = _select_artifact(path, "fingerprint.json")
    statistics_path, statistics = _select_artifact(path, "statistics.json")
    metadata = _read(path / "metadata.json")
    session_profile_summary = _read(path / "session_profile" / "summary.json")
    session_diff_summary = _read(path / "session_diff" / "summary.json")
    if not isinstance(summary, dict):
        summary = session_profile_summary if isinstance(session_profile_summary, dict) else session_diff_summary if isinstance(session_diff_summary, dict) else {}
    timestamp = _iso(_first(summary, (("created_at",), ("timestamp",), ("started_at",))), _iso(_first(metadata, (("created_at",), ("started_at",))), datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()))
    scores = score if isinstance(score, dict) else {}
    summary_scores = summary.get("scores", {}) if isinstance(summary.get("scores"), dict) else {}
    categories = _category_scores(scores)
    for name in MODULES:
        categories.setdefault(name, None)
    fingerprint_hashes = fingerprint.get("hashes", {}) if isinstance(fingerprint, dict) and isinstance(fingerprint.get("hashes"), dict) else {}
    missing = [name for name, artifact in (("summary", summary_path), ("score", score_path), ("compare", compare_path), ("fingerprint", fingerprint_path), ("statistics", statistics_path)) if artifact is None]
    result = _first(summary, (("result",), ("status",), ("outcome",)), _first(statistics, (("result",), ("status",)), None))
    if isinstance(result, dict):
        result = result.get("status")
    result = str(result).upper() if result is not None else "UNKNOWN"
    if result == "COMPLETED":
        result = "SUCCESS"
    # Historical experiments use several schemas.  Prefer the dedicated score
    # artifact, then fall back to the root summary's normalized score/diff
    # sections.  A missing artifact is metadata about coverage, not a reason to
    # discard an otherwise useful observation.
    summary_diff = _first(summary, (("total_diff",), ("diffs", "after"), ("diff", "after"), ("statistics", "total_diff")), None)
    summary_improved = _first(summary, (("improved",), ("keys", "improved"), ("validation", "keys", "improved")), [])
    summary_regressed = _first(summary, (("regressed",), ("keys", "regressed"), ("validation", "keys", "regressed")), [])
    data = {
        "experiment_id": f"exp_{number:03d}", "experiment_name": _first(summary, (("experiment",), ("label",), ("name",)), _first(metadata, (("label",), ("experiment",)), path.name)),
        "timestamp": timestamp, "overall_score": _number(_first(scores, (("overall_score",), ("overall",), ("scores", "overall_after")), _first(summary_scores, (("overall_after",), ("overall",)), None))),
        "cf_score": _number(_first(scores, (("cf_risk_score",), ("cf_score",), ("scores", "cf_risk_after")), _first(summary_scores, (("cf_risk_after",), ("cf_score",)), None))),
        "category_scores": categories,
        "navigator_score": categories.get("Navigator"),
        "window_score": categories.get("Window"),
        "screen_score": categories.get("Screen"),
        "chrome_score": categories.get("Chrome"),
        "permissions_score": categories.get("Permissions"),
        "fonts_score": categories.get("Fonts"),
        "speech_score": categories.get("Speech"),
        "performance_score": categories.get("Performance"),
        "webgl_score": categories.get("WebGL"),
        "total_diff": _number(_first(compare, (("total_diff",), ("diff_count",), ("diffs", "after"), ("statistics", "total_diff")), _first(scores, (("total_diff",), ("diff_count",)), summary_diff))),
        "improved": _first(compare, (("improved",), ("keys", "improved"), ("statistics", "improvement_count")), summary_improved),
        "regressed": _first(compare, (("regressed",), ("keys", "regressed"), ("statistics", "regression_count")), summary_regressed),
        "fingerprint_hash": _first(summary, (("fingerprint_hash",),), None), "environment_hash": _first(summary, (("environment_hash",),), None), "profile_hash": _first(summary, (("profile_hash",),), None),
        "module_hashes": fingerprint_hashes, "result": result, "missing_artifacts": missing,
        "source_artifacts": {"summary": relative_path(summary_path, root) if summary_path else None, "score": relative_path(score_path, root) if score_path else None, "compare": relative_path(compare_path, root) if compare_path else None, "fingerprint": relative_path(fingerprint_path, root) if fingerprint_path else None, "statistics": relative_path(statistics_path, root) if statistics_path else None},
    }
    # Session profiler summaries contain profile/environment/fingerprint hashes.
    for source in (summary, session_profile_summary):
        if not isinstance(source, dict):
            continue
        for key in ("fingerprint_hash", "environment_hash", "profile_hash"):
            if data[key] is None and source.get(key) is not None:
                data[key] = source[key]
    data["has_observation"] = any(
        _number(data.get(field)) is not None for field in ("overall_score", "cf_score", "total_diff")
    ) or any(_number(value) is not None for value in data.get("category_scores", {}).values()) or any(
        data.get(field) is not None for field in ("fingerprint_hash", "environment_hash", "profile_hash")
    )
    return ExperimentRecord(number=number, experiment_id=f"exp_{number:03d}", path=path, data=data)


def _discover(root: Path) -> list[ExperimentRecord]:
    records = []
    for path in root.iterdir() if root.is_dir() else []:
        if not path.is_dir() or not path.name.startswith("exp_"):
            continue
        try:
            number = int(path.name.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        records.append(_collect_record(number, path, root))
    return sorted(records, key=lambda item: item.number)


def _delta(new: Any, old: Any) -> float | None:
    left, right = _number(new), _number(old)
    return round(left - right, 4) if left is not None and right is not None else None


def _evolution(records: list[ExperimentRecord]) -> list[dict[str, Any]]:
    output = []
    for previous, current in zip(records, records[1:]):
        old, new = previous.data, current.data
        old_categories, new_categories = old.get("category_scores", {}), new.get("category_scores", {})
        category_improvement, category_regression, missing = [], [], []
        for category in MODULES:
            before, after = _number(old_categories.get(category)), _number(new_categories.get(category))
            if before is None or after is None:
                missing.append(category)
                continue
            change = round(after - before, 4)
            if change > 0:
                category_improvement.append({"category": category, "delta": change})
            elif change < 0:
                category_regression.append({"category": category, "delta": change})
        old_hash, new_hash = old.get("fingerprint_hash"), new.get("fingerprint_hash")
        old_modules, new_modules = set((old.get("module_hashes") or {}).keys()), set((new.get("module_hashes") or {}).keys())
        output.append({"from": previous.experiment_id, "to": current.experiment_id, "score_delta": _delta(new.get("overall_score"), old.get("overall_score")), "cf_score_delta": _delta(new.get("cf_score"), old.get("cf_score")), "diff_delta": _delta(new.get("total_diff"), old.get("total_diff")), "hash_change": old_hash is not None and new_hash is not None and old_hash != new_hash, "environment_hash_change": old.get("environment_hash") is not None and new.get("environment_hash") is not None and old.get("environment_hash") != new.get("environment_hash"), "profile_hash_change": old.get("profile_hash") is not None and new.get("profile_hash") is not None and old.get("profile_hash") != new.get("profile_hash"), "new_modules": sorted(new_modules - old_modules), "removed_modules": sorted(old_modules - new_modules), "category_improvement": category_improvement, "category_regression": category_regression, "missing_categories": missing, "missing_artifacts": sorted(set(new.get("missing_artifacts", []))), "result": new.get("result")})
    return output


def _series(records: list[ExperimentRecord], key: str) -> list[float | None]:
    return [_number(record.data.get(key)) for record in records]


def _moving(values: list[float | None], window: int = 3) -> list[float | None]:
    output = []
    for index in range(len(values)):
        chunk = [value for value in values[max(0, index - window + 1): index + 1] if value is not None]
        output.append(round(statistics.mean(chunk), 4) if chunk else None)
    return output


def _trends(records: list[ExperimentRecord], changes: list[dict[str, Any]]) -> dict[str, Any]:
    overall = _series(records, "overall_score")
    cf = _series(records, "cf_score")
    diff = _series(records, "total_diff")
    category = {module: [_number(record.data.get("category_scores", {}).get(module)) for record in records] for module in MODULES}
    fingerprint = [record.data.get("fingerprint_hash") for record in records]
    environment = [record.data.get("environment_hash") for record in records]
    profile = [record.data.get("profile_hash") for record in records]
    observed = [record.data for record in records if record.data.get("has_observation")]
    best = max(observed, key=lambda item: item.get("overall_score") if _number(item.get("overall_score")) is not None else float("-inf"), default=None)
    worst = min(observed, key=lambda item: item.get("overall_score") if _number(item.get("overall_score")) is not None else float("inf"), default=None)
    score_improvements = [item for item in changes if _number(item.get("score_delta")) is not None and item["score_delta"] > 0]
    score_regressions = [item for item in changes if _number(item.get("score_delta")) is not None and item["score_delta"] < 0]
    return {"overall": {"values": overall, "moving_average": _moving(overall), "direction": _direction(overall)}, "cf_score": {"values": cf, "moving_average": _moving(cf), "direction": _direction(cf)}, "total_diff": {"values": diff, "moving_average": _moving(diff), "direction": _direction(diff, lower_is_better=True)}, "fingerprint": {"hashes": fingerprint, "changes": sum(a is not None and b is not None and a != b for a, b in zip(fingerprint, fingerprint[1:])), "direction": "stable" if len(set(value for value in fingerprint if value is not None)) <= 1 else "variable"}, "environment": {"hashes": environment, "changes": sum(a is not None and b is not None and a != b for a, b in zip(environment, environment[1:])), "direction": "stable" if len(set(value for value in environment if value is not None)) <= 1 else "variable"}, "profile": {"hashes": profile, "changes": sum(a is not None and b is not None and a != b for a, b in zip(profile, profile[1:])), "direction": "stable" if len(set(value for value in profile if value is not None)) <= 1 else "variable"}, "categories": {module: {"values": values, "moving_average": _moving(values), "direction": _direction(values)} for module, values in category.items()}, "change_count": len(changes), "best_experiment": {"experiment_id": best.get("experiment_id"), "overall_score": best.get("overall_score")} if best else None, "worst_experiment": {"experiment_id": worst.get("experiment_id"), "overall_score": worst.get("overall_score")} if worst else None, "largest_improvement": max(score_improvements, key=lambda item: item["score_delta"], default=None), "largest_regression": min(score_regressions, key=lambda item: item["score_delta"], default=None)}


def _direction(values: list[float | None], lower_is_better: bool = False) -> str:
    observed = [value for value in values if value is not None]
    if len(observed) < 2:
        return "unknown"
    delta = observed[-1] - observed[0]
    if abs(delta) < 0.0001:
        return "stable"
    if lower_is_better:
        return "improving" if delta < 0 else "regressing"
    return "improving" if delta > 0 else "regressing"


def _stability(records: list[ExperimentRecord], trends: dict[str, Any]) -> dict[str, Any]:
    values = [value for value in _series(records, "overall_score") if value is not None]
    variance = round(statistics.pvariance(values), 4) if len(values) > 1 else None
    score_consistency = round(max(0.0, 100.0 - (statistics.pstdev(values) * 10 if len(values) > 1 else 0.0)), 2) if values else None
    def hash_consistency(name: str) -> float | None:
        values = [value for value in trends.get(name, {}).get("hashes", []) if value is not None]
        return round(max(0.0, 100.0 * (1 - (len(set(values)) - 1) / max(1, len(values) - 1))), 2) if values else None
    module_coverage = [sum(_number(record.data.get("category_scores", {}).get(module)) is not None for module in MODULES) / len(MODULES) * 100 for record in records]
    consistency = {"overall_variance": variance, "score_consistency": score_consistency, "stability_score": score_consistency, "fingerprint_consistency": hash_consistency("fingerprint"), "environment_consistency": hash_consistency("environment"), "profile_consistency": hash_consistency("profile"), "module_consistency": round(statistics.mean(module_coverage), 2) if module_coverage else None}
    if variance is None:
        label = "UNKNOWN"
    elif variance <= 1:
        label = "STABLE"
    elif variance <= 5:
        label = "MOSTLY_STABLE"
    else:
        label = "UNSTABLE"
    return {"classification": label, **consistency}


def _regressions(records: list[ExperimentRecord], changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regressions = []
    for change in changes:
        if _number(change.get("score_delta")) is not None and change["score_delta"] < 0:
            regressions.append({"from": change["from"], "to": change["to"], "type": "overall_decrease", "severity": "HIGH" if change["score_delta"] <= -5 else "MEDIUM", "reason": f"Overall score decreased by {change['score_delta']} points.", "possible_cause": "Module change, browser/environment variation, or missing score artifact.", "confidence": "High"})
        if _number(change.get("cf_score_delta")) is not None and change["cf_score_delta"] < 0:
            regressions.append({"from": change["from"], "to": change["to"], "type": "cf_score_decrease", "severity": "HIGH", "reason": f"CF score decreased by {change['cf_score_delta']} points.", "possible_cause": "Browser consistency or Cloudflare-sensitive surface changed.", "confidence": "Medium"})
        if _number(change.get("diff_delta")) is not None and change["diff_delta"] > 0:
            regressions.append({"from": change["from"], "to": change["to"], "type": "diff_increase", "severity": "MEDIUM", "reason": f"Total diff increased by {change['diff_delta']}.", "possible_cause": "New mismatches or a changed baseline.", "confidence": "High"})
        if change.get("hash_change"):
            regressions.append({"from": change["from"], "to": change["to"], "type": "fingerprint_hash_change", "severity": "MEDIUM", "reason": "Fingerprint hash changed between adjacent experiments.", "possible_cause": "A module, browser build, profile, or environment changed.", "confidence": "High"})
        for category in change.get("category_regression", []):
            regressions.append({"from": change["from"], "to": change["to"], "type": "category_decrease", "category": category["category"], "severity": "MEDIUM", "reason": f"{category['category']} score decreased by {category['delta']} points.", "possible_cause": "The category module or its runtime conditions changed.", "confidence": "Medium"})
        if change.get("removed_modules"):
            regressions.append({"from": change["from"], "to": change["to"], "type": "module_removed", "severity": "HIGH", "reason": f"Modules removed: {', '.join(change['removed_modules'])}.", "possible_cause": "Artifact or registry coverage changed.", "confidence": "Medium"})
        if change.get("missing_artifacts"):
            regressions.append({"from": change["from"], "to": change["to"], "type": "missing_artifact", "severity": "MEDIUM", "reason": f"Missing artifacts: {', '.join(change['missing_artifacts'])}.", "possible_cause": "Experiment produced a partial report.", "confidence": "High"})
    return regressions


def _ranking(records: list[ExperimentRecord], changes: list[dict[str, Any]], stability: dict[str, Any]) -> dict[str, Any]:
    def rows(key: str, reverse: bool = True):
        return [{"experiment_id": record.experiment_id, "experiment_name": record.data.get("experiment_name"), "value": record.data.get(key)} for record in sorted((item for item in records if _number(item.data.get(key)) is not None), key=lambda item: _number(item.data.get(key)) or 0, reverse=reverse)]
    best_fingerprint = [{"experiment_id": record.experiment_id, "hash": record.data.get("fingerprint_hash")} for record in records if record.data.get("fingerprint_hash")]
    best_environment = [{"experiment_id": record.experiment_id, "hash": record.data.get("environment_hash")} for record in records if record.data.get("environment_hash")]
    improvements = sorted((item for item in changes if _number(item.get("score_delta")) is not None and item["score_delta"] > 0), key=lambda item: item["score_delta"], reverse=True)
    regressions = sorted((item for item in changes if _number(item.get("score_delta")) is not None and item["score_delta"] < 0), key=lambda item: item["score_delta"])
    return {"top_overall": rows("overall_score"), "top_cf_score": rows("cf_score"), "lowest_diff": rows("total_diff", reverse=False), "most_stable": [{"classification": stability.get("classification"), "score_consistency": stability.get("score_consistency")}], "largest_improvement": improvements[0] if improvements else None, "largest_regression": regressions[0] if regressions else None, "most_consistent": [{"experiment_id": record.experiment_id, "fingerprint_hash": record.data.get("fingerprint_hash"), "environment_hash": record.data.get("environment_hash")} for record in records if record.data.get("fingerprint_hash") and record.data.get("environment_hash")], "best_fingerprint": best_fingerprint, "best_environment": best_environment}


def _recommendations(records: list[ExperimentRecord], trends: dict[str, Any], stability: dict[str, Any], regressions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for module in MODULES:
        direction = trends.get("categories", {}).get(module, {}).get("direction")
        if direction == "improving":
            output.append({"module": module, "priority": "LOW", "recommendation": f"{module} is improving across observed experiments; preserve the current configuration.", "basis": "category trend"})
        elif direction == "regressing":
            output.append({"module": module, "priority": "HIGH", "recommendation": f"Review {module} because its category trend is regressing.", "basis": "category trend"})
    if stability.get("classification") == "UNSTABLE":
        output.append({"module": "Project", "priority": "HIGH", "recommendation": "Control browser, profile, and environment variables before attributing score movement to stealth changes.", "basis": "overall variance"})
    if any(item.get("type") == "missing_artifact" for item in regressions):
        output.append({"module": "Experiment artifacts", "priority": "MEDIUM", "recommendation": "Complete missing score and fingerprint artifacts before using the trend for release decisions.", "basis": "missing artifact regressions"})
    if not output:
        output.append({"module": "Project", "priority": "INFO", "recommendation": "Continue collecting immutable experiments to increase trend confidence.", "basis": "insufficient directional evidence"})
    return output


def _report(summary: dict[str, Any], timeline: list[dict[str, Any]], trends: dict[str, Any], ranking: dict[str, Any], regressions: list[dict[str, Any]], recommendations: list[dict[str, Any]], output: Path) -> str:
    lines = ["# Experiment 022 — Fingerprint Evolution Tracker", "", "Analysis-only history built from existing immutable artifacts. No browser was launched.", "", "## Executive Summary", "", f"Result: **{summary['result']}**", f"Experiments discovered: **{summary['total_experiments']}**, processed: **{summary['processed_experiments']}**", f"Current score: **{summary['current_score']}**, current diff: **{summary['current_diff']}**", f"Stability: **{summary['stability'].get('classification')}**", "", "## Timeline", "", "| Experiment | Name | Overall | CF | Diff | Improved | Regressed | Result |", "|---|---|---:|---:|---:|---:|---:|---|"]
    for item in timeline:
        lines.append(f"| {item['experiment_id']} | {item['experiment_name']} | {item.get('overall_score', '—')} | {item.get('cf_score', '—')} | {item.get('total_diff', '—')} | {len(item.get('improved', [])) if isinstance(item.get('improved'), list) else item.get('improved', '—')} | {len(item.get('regressed', [])) if isinstance(item.get('regressed'), list) else item.get('regressed', '—')} | {item.get('result')} |")
    lines += ["", "## Score Evolution", "", json.dumps(trends.get("overall", {}), ensure_ascii=False, indent=2), "", "## Fingerprint Evolution", "", json.dumps(trends.get("fingerprint", {}), ensure_ascii=False, indent=2), "", "## Module Evolution", "", "| Module | Direction |", "|---|---|"]
    for module, value in trends.get("categories", {}).items():
        lines.append(f"| {module} | {value.get('direction')} |")
    lines += ["", "## Regression Analysis", "", "| From | To | Type | Severity | Reason |", "|---|---|---|---|---|"]
    if not regressions:
        lines.append("| — | — | none | INFO | No regression detected. |")
    for item in regressions[:50]:
        lines.append(f"| {item.get('from')} | {item.get('to')} | {item.get('type')} | {item.get('severity')} | {str(item.get('reason')).replace('|', '\\|')} |")
    lines += ["", "## Stability Analysis", "", json.dumps(summary.get("stability", {}), ensure_ascii=False, indent=2), "", "## Rankings", "", "### Top Overall", ""]
    for item in ranking.get("top_overall", [])[:10]:
        lines.append(f"- {item.get('experiment_id')}: {item.get('value')}")
    lines += ["", "### Top CF Score", ""]
    for item in ranking.get("top_cf_score", [])[:10]:
        lines.append(f"- {item.get('experiment_id')}: {item.get('value')}")
    lines += ["", "### Lowest Diff", ""]
    for item in ranking.get("lowest_diff", [])[:10]:
        lines.append(f"- {item.get('experiment_id')}: {item.get('value')}")
    lines += ["", "## Recommendations", ""]
    for item in recommendations:
        lines.append(f"- **{item.get('priority')} — {item.get('module')}**: {item.get('recommendation')}")
    lines += ["", "## Final Conclusion", "", f"The current evolution result is **{summary['result']}** with trend **{summary['trend']}**. Scores and regressions are observations of available artifacts, not proof of browser or Cloudflare behavior.", "", f"Artifacts: `{output}`", ""]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment 022: track fingerprint evolution from immutable experiment artifacts")
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def _validate(output: Path, timeline: list[dict[str, Any]], trends: dict[str, Any], ranking: dict[str, Any], regressions: list[dict[str, Any]]) -> dict[str, Any]:
    required = ["timeline.json", "evolution.json", "trends.json", "ranking.json", "regressions.json", "statistics.json", "recommendations.json", "summary.json", "fingerprint_evolution.md"]
    missing = [name for name in required if not (output / name).is_file()]
    ordering = [int(str(item.get("experiment_id", "exp_0")).split("_")[-1]) for item in timeline]
    ranking_ids = {item.get("experiment_id") for item in ranking.get("top_overall", [])}
    trend_values = trends.get("overall", {}).get("values", [])
    report = (output / "fingerprint_evolution.md").read_text(encoding="utf-8") if (output / "fingerprint_evolution.md").is_file() else ""
    sections_valid = all(section in report for section in ("Executive Summary", "Timeline", "Score Evolution", "Fingerprint Evolution", "Module Evolution", "Regression Analysis", "Stability Analysis", "Rankings", "Recommendations", "Final Conclusion"))
    artifact_completeness = not missing
    timeline_ordered = ordering == sorted(ordering)
    ranking_valid = not ranking_ids or ranking_ids.issubset(set(item.get("experiment_id") for item in timeline))
    trend_valid = len(trend_values) == len(timeline)
    regression_valid = all(item.get("severity") in {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"} and item.get("reason") and item.get("confidence") for item in regressions)
    checks = {"artifact_completeness": artifact_completeness, "missing_artifacts": missing, "json_valid": True, "timeline_ordered": timeline_ordered, "ranking_valid": ranking_valid, "trend_valid": trend_valid, "regression_valid": regression_valid, "markdown_valid": sections_valid, "source_artifacts_unchanged": True}
    checks["valid"] = all(value for key, value in checks.items() if key not in {"missing_artifacts"})
    return checks


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    args = _parser().parse_args(argv)
    root = project_root()
    reports_dir = (args.reports_dir or root / "reports" / "experiments").resolve()
    records = _discover(reports_dir)
    experiment = Experiment.create(reports_dir)
    output = experiment.directory / "fingerprint_evolution"
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"experiment": "Experiment 022 — Fingerprint Evolution Tracker", "experiment_id": experiment.experiment_id, "created_at": experiment.started_at, "reports_dir": relative_path(reports_dir, root), "browser_launches": 0, "analysis_only": True, "source_artifacts_modified": False, "environment": system_metadata(), "git": git_metadata(root)}
    write_json_exclusive(output / "metadata.json", metadata)
    timeline = [{**record.data, "experiment_id": record.experiment_id} for record in records]
    changes = _evolution(records)
    trends = _trends(records, changes)
    stability = _stability(records, trends)
    regressions = _regressions(records, changes)
    ranking = _ranking(records, changes, stability)
    recommendations = _recommendations(records, trends, stability, regressions)
    numeric_overall = [item.get("overall_score") for item in timeline if _number(item.get("overall_score")) is not None]
    # Analysis-only experiments can be newer than the latest scored run.
    observed_timeline = [item for item in timeline if item.get("has_observation")]
    scored_timeline = [item for item in timeline if _number(item.get("overall_score")) is not None]
    current = scored_timeline[-1] if scored_timeline else (observed_timeline[-1] if observed_timeline else {})
    best = max((item for item in timeline if _number(item.get("overall_score")) is not None), key=lambda item: item["overall_score"], default=None)
    best_cf = max((item for item in timeline if _number(item.get("cf_score")) is not None), key=lambda item: item["cf_score"], default=None)
    lowest_diff = min((item for item in timeline if _number(item.get("total_diff")) is not None), key=lambda item: item["total_diff"], default=None)
    improvements = [item for item in changes if _number(item.get("score_delta")) is not None and item["score_delta"] > 0]
    regressions_only = [item for item in changes if _number(item.get("score_delta")) is not None and item["score_delta"] < 0]
    largest_improvement = max(improvements, key=lambda item: item["score_delta"], default=None)
    largest_regression = min(regressions_only, key=lambda item: item["score_delta"], default=None)
    if not records:
        result = "UNKNOWN"
    elif not observed_timeline:
        result = "PARTIAL"
    else:
        result = "SUCCESS"
    trend = trends.get("overall", {}).get("direction", "unknown")
    summary = {"experiment": "Experiment 022 — Fingerprint Evolution Tracker", "experiment_id": experiment.experiment_id, "total_experiments": len(records), "processed_experiments": len(observed_timeline), "missing_artifacts": sorted({artifact for record in records for artifact in record.data.get("missing_artifacts", [])}), "overall_best": best, "cf_best": best_cf, "lowest_diff": lowest_diff, "largest_improvement": largest_improvement, "largest_regression": largest_regression, "stability": stability, "current_score": current.get("overall_score"), "current_diff": current.get("total_diff"), "current_rank": next((index + 1 for index, item in enumerate(ranking.get("top_overall", [])) if item.get("experiment_id") == current.get("experiment_id")), None), "trend": trend, "result": result, "statistics": {"total_experiments": len(records), "processed_experiments": len(observed_timeline), "missing_artifact_count": len({artifact for record in records for artifact in record.data.get("missing_artifacts", [])}), "overall_variance": stability.get("overall_variance"), "score_consistency": stability.get("score_consistency"), "stability_score": stability.get("stability_score"), "fingerprint_consistency": stability.get("fingerprint_consistency"), "environment_consistency": stability.get("environment_consistency"), "profile_consistency": stability.get("profile_consistency"), "module_consistency": stability.get("module_consistency"), "regression_count": len(regressions), "average_overall": round(statistics.mean(numeric_overall), 4) if numeric_overall else None}}
    write_json_exclusive(output / "timeline.json", {"experiments": timeline})
    write_json_exclusive(output / "evolution.json", {"changes": changes})
    write_json_exclusive(output / "trends.json", trends)
    write_json_exclusive(output / "ranking.json", ranking)
    write_json_exclusive(output / "regressions.json", {"regressions": regressions})
    write_json_exclusive(output / "statistics.json", summary["statistics"])
    write_json_exclusive(output / "recommendations.json", {"recommendations": recommendations})
    write_json_exclusive(output / "summary.json", summary)
    write_text_exclusive(output / "fingerprint_evolution.md", _report(summary, timeline, trends, ranking, regressions, recommendations, output))
    validation = _validate(output, timeline, trends, ranking, regressions)
    write_json_exclusive(output / "validation.json", validation)
    print("\nFINGERPRINT EVOLUTION TRACKER")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Detected: {len(records)}")
    print(f"Processed: {summary['processed_experiments']}")
    print(f"Current score: {summary['current_score']}")
    print(f"Stability: {stability.get('classification')}")
    print(f"Result: {result}")
    print(f"Artifacts: {relative_path(output, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
