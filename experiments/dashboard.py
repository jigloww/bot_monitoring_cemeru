"""Build a read-only progress dashboard from completed experiment artifacts.

The dashboard deliberately does not import Playwright or launch a browser. It
scans ``reports/experiments/exp_xxx`` folders, tolerates the artifact schema
used by the early Navigator experiments and the later mode-based evaluations,
and writes the dashboard itself under ``reports/dashboard``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.utils import project_root


EXP_PATTERN = re.compile(r"^exp_(\d+)$")
MODULE_ORDER = (
    "navigator",
    "window",
    "screen",
    "chrome",
    "permissions",
    "fonts",
    "speech",
    "performance",
    "webgl",
)
MODULE_LABELS = {
    "navigator": "Navigator",
    "window": "Window",
    "screen": "Screen",
    "chrome": "Chrome",
    "permissions": "Permissions",
    "fonts": "Fonts",
    "speech": "Speech",
    "performance": "Performance",
    "webgl": "WebGL",
}
MODE_RANK = {
    "plain": 0,
    "generated": 1,
    "navigator": 2,
    "navigator_window": 3,
    "navigator_window_screen": 4,
    "navigator_window_screen_chrome": 5,
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _iso(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except ValueError:
        return text


def _timestamp_key(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _integer(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _mode_score_row(summary: dict[str, Any], mode: str | None = None) -> dict[str, Any] | None:
    """Normalize a mode summary or an older before/after summary."""
    scores = summary.get("scores") if isinstance(summary.get("scores"), dict) else {}
    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    overall = _number(_first(scores, "overall_similarity", "overall_score"))
    cf = _number(_first(scores, "weighted_cf_score", "cf_risk_score"))
    total_diff = _integer(_first(metrics, "total_diff", "diff_count"))
    improved = _integer(_first(metrics, "improved", "improved_keys"))
    regressed = _integer(_first(metrics, "regressed", "regressed_keys"))
    # Early Experiment 001 used one top-level before/after summary.
    if overall is None:
        overall = _number(scores.get("overall_after"))
    if cf is None:
        cf = _number(scores.get("cf_risk_after"))
    if total_diff is None:
        diffs = summary.get("diffs") if isinstance(summary.get("diffs"), dict) else {}
        total_diff = _integer(_first(diffs, "after", "diff_count"))
    if improved is None:
        keys = summary.get("keys") if isinstance(summary.get("keys"), dict) else {}
        improved = _integer(keys.get("improved"))
    if regressed is None:
        keys = summary.get("keys") if isinstance(summary.get("keys"), dict) else {}
        regressed = _integer(keys.get("regressed"))
    if all(value is None for value in (overall, cf, total_diff, improved, regressed)):
        return None
    category_scores = {}
    for key, value in scores.items():
        if key.endswith("_category_score"):
            category_scores[key[:-len("_category_score")]] = _number(value)
    return {
        "mode": mode,
        "overall": overall,
        "cf_score": cf,
        "total_diff": total_diff,
        "improved": improved,
        "regressed": regressed,
        "category_scores": category_scores,
        "created_at": _iso(_first(summary, "created_at", "generated_at")),
        "label": summary.get("label") or summary.get("experiment") or mode,
    }


def _collect_mode_rows(experiment_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in experiment_dir.rglob("summary.json"):
        data = _read_json(path)
        if not data:
            continue
        if isinstance(data.get("modes"), dict):
            for mode, mode_summary in data["modes"].items():
                if isinstance(mode_summary, dict):
                    row = _mode_score_row(mode_summary, str(mode))
                    if row:
                        row["created_at"] = row.get("created_at") or _iso(
                            _first(data, "created_at", "generated_at")
                        )
                        rows.append(row)
            continue
        mode = path.parent.name if path.parent != experiment_dir else None
        row = _mode_score_row(data, mode)
        if row:
            rows.append(row)
    # A root summary and mode summaries can both expose the same mode. Keep
    # the most complete/latest row while retaining chronological mode order.
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("mode") or "top-level")
        previous = deduped.get(key)
        if previous is None or _timestamp_key(row.get("created_at")) >= _timestamp_key(previous.get("created_at")):
            deduped[key] = row
    return list(deduped.values())


def _final_mode(rows: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    rows = list(rows)
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            MODE_RANK.get(str(row.get("mode")), -1),
            _timestamp_key(row.get("created_at")),
        ),
    )


def _text_signals(experiment_dir: Path, metadata: dict[str, Any], summaries: list[dict[str, Any]]) -> str:
    values = [experiment_dir.name]
    for key in ("label", "experiment", "description"):
        value = metadata.get(key)
        if isinstance(value, str):
            values.append(value)
    for summary in summaries:
        for key in ("label", "experiment", "mode"):
            value = summary.get(key)
            if isinstance(value, str):
                values.append(value)
    values.extend(path.name for path in experiment_dir.glob("*.json"))
    values.extend(path.name for path in experiment_dir.glob("*.md"))
    return " ".join(values).lower()


def _detect_modules(
    experiment_dir: Path,
    metadata: dict[str, Any],
    summaries: list[dict[str, Any]],
    final_mode: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    # Direct module directories are the strongest signal for evaluation runs.
    direct = [
        path.name.lower()
        for path in experiment_dir.iterdir()
        if path.is_dir() and path.name.lower() in MODULE_ORDER
    ]
    signals = _text_signals(experiment_dir, metadata, summaries)
    detected = [module for module in MODULE_ORDER if module in signals]

    primary: str | None = direct[0] if len(direct) == 1 else None
    if primary is None and detected:
        # Prefer the module explicitly named by the experiment title/label.
        for module in MODULE_ORDER:
            if re.search(rf"\b{re.escape(module)}\b", signals):
                primary = module
                break
        if primary is None:
            primary = detected[0]
    if primary is None and direct:
        primary = direct[-1]
    if primary is None:
        primary = "other"

    involved = list(detected)
    mode = str(final_mode.get("mode")) if final_mode and final_mode.get("mode") else ""
    mode_modules = [module for module in MODULE_ORDER if module in mode]
    if mode_modules:
        involved = list(dict.fromkeys(mode_modules))
    if primary != "other" and primary not in involved:
        involved.insert(0, primary)
    if not involved:
        involved = [primary] if primary != "other" else []
    return primary, involved


def _metadata_for(experiment_dir: Path) -> dict[str, Any]:
    metadata = _read_json(experiment_dir / "metadata.json")
    return metadata or {}


def _experiment_record(experiment_dir: Path) -> dict[str, Any]:
    metadata = _metadata_for(experiment_dir)
    mode_rows = _collect_mode_rows(experiment_dir)
    final_mode = _final_mode(mode_rows)
    summaries = []
    for path in experiment_dir.rglob("summary.json"):
        data = _read_json(path)
        if data:
            summaries.append(data)
    root_artifacts: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(experiment_dir.glob("*.json")):
        if path.name == "metadata.json" or path.name == "summary.json":
            continue
        data = _read_json(path)
        if data:
            root_artifacts.append((path, data))

    primary, involved = _detect_modules(experiment_dir, metadata, summaries, final_mode)
    root_summary = _read_json(experiment_dir / "summary.json") or {}
    experiment_name = (
        root_summary.get("experiment")
        or (summaries[0].get("experiment") if summaries else None)
        or (root_artifacts[0][1].get("experiment") if root_artifacts else None)
        or metadata.get("label")
        or experiment_dir.name
    )
    artifact_generated_at = next(
        (_iso(data.get("generated_at")) for _, data in root_artifacts if data.get("generated_at")),
        None,
    )
    timestamp = (
        _iso(_first(metadata, "completed_at", "date", "created_at"))
        or _iso(_first(root_summary, "created_at", "generated_at"))
        or (final_mode or {}).get("created_at")
        or artifact_generated_at
    )
    if timestamp is None:
        timestamp = datetime.fromtimestamp(experiment_dir.stat().st_mtime, tz=timezone.utc).isoformat()

    status = str(
        _first(metadata, "status")
        or root_summary.get("status")
        or (final_mode or {}).get("status")
        or "completed"
    ).lower()
    if status in {"success", "successful", "done"}:
        status = "completed"
    duration_seconds = None
    start = _first(metadata, "date", "started_at", "created_at")
    end = _first(metadata, "completed_at", "finished_at")
    if isinstance(start, str) and isinstance(end, str):
        try:
            duration_seconds = round((_timestamp_key(end) - _timestamp_key(start)).total_seconds(), 3)
        except Exception:
            duration_seconds = None
    if duration_seconds is None:
        duration_seconds = _number(_first(metadata, "duration_seconds", "duration"))

    record = {
        "experiment_id": experiment_dir.name,
        "timestamp": timestamp,
        "module": primary,
        "module_label": " + ".join(MODULE_LABELS.get(module, module.title()) for module in involved) or "Other",
        "modules": involved,
        "experiment": str(experiment_name),
        "label": str(metadata.get("label") or (final_mode or {}).get("label") or experiment_name),
        "overall": (final_mode or {}).get("overall"),
        "module_score": (final_mode or {}).get("category_scores", {}).get(primary),
        "cf_score": (final_mode or {}).get("cf_score"),
        "total_diff": (final_mode or {}).get("total_diff"),
        "improved": (final_mode or {}).get("improved"),
        "regressed": (final_mode or {}).get("regressed"),
        "status": status,
        "duration_seconds": duration_seconds,
        "duration": f"{duration_seconds:.1f}s" if duration_seconds is not None else "N/A",
        "final_mode": (final_mode or {}).get("mode"),
        "source": str((experiment_dir / "summary.json" if (experiment_dir / "summary.json").exists() else (root_artifacts[0][0] if root_artifacts else experiment_dir)).as_posix()),
    }
    record["target_reached"] = bool(
        status == "completed"
        and primary != "other"
        and (record["regressed"] in (0, None))
        and (record["module_score"] is not None or record["overall"] is not None)
    )
    return record


def scan_experiments(experiments_dir: Path) -> list[dict[str, Any]]:
    records = []
    if not experiments_dir.is_dir():
        return records
    for path in experiments_dir.iterdir():
        if path.is_dir() and EXP_PATTERN.match(path.name):
            records.append(_experiment_record(path))
    return sorted(records, key=lambda record: (_timestamp_key(record.get("timestamp")), record["experiment_id"]))


def _score_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record.get("overall") is not None]


def _trend(records: list[dict[str, Any]]) -> dict[str, Any]:
    scored = _score_records(records)
    points: list[dict[str, Any]] = []
    # Include the first Plain observation as the project starting point. This
    # makes the progression explain the familiar 43.5 -> module milestones.
    first_exp = next((record for record in records if record["experiment_id"] == "exp_001"), None)
    if first_exp:
        root = _read_json(Path(first_exp["source"])) if first_exp.get("source") else None
        # The mode rows are not retained in the compact record; recover the
        # plain score from the experiment folder when available.
        plain_path = Path(first_exp["source"]).parent / "plain" / "summary.json"
        plain_summary = _read_json(plain_path)
        plain = _mode_score_row(plain_summary or {}, "plain")
        if plain and plain.get("overall") is not None:
            points.append({
                "experiment_id": "baseline",
                "module": "baseline",
                "overall": plain["overall"],
                "cf_score": plain["cf_score"],
            })
    for record in scored:
        points.append({
            "experiment_id": record["experiment_id"],
            "module": record["module"],
            "overall": record["overall"],
            "cf_score": record["cf_score"],
        })
    deltas = []
    for before, after in zip(points, points[1:]):
        if before["overall"] is None or after["overall"] is None:
            continue
        deltas.append({
            "from": before["experiment_id"],
            "to": after["experiment_id"],
            "delta": round(after["overall"] - before["overall"], 2),
        })
    improvements = [item for item in deltas if item["delta"] > 0]
    regressions = [item for item in deltas if item["delta"] < 0]
    best_overall = max(scored, key=lambda record: record["overall"]) if scored else None
    best_cf = max((record for record in scored if record.get("cf_score") is not None), key=lambda record: record["cf_score"], default=None)
    lowest_diff = min((record for record in records if record.get("total_diff") is not None), key=lambda record: record["total_diff"], default=None)
    return {
        "points": points,
        "overall_progression": [point["overall"] for point in points],
        "cf_progression": [point["cf_score"] for point in points],
        "deltas": deltas,
        "average_improvement": round(sum(item["delta"] for item in deltas) / len(deltas), 2) if deltas else 0.0,
        "largest_improvement": max(improvements, key=lambda item: item["delta"], default=None),
        "largest_regression": min(regressions, key=lambda item: item["delta"], default=None),
        "current_best_score": best_overall["overall"] if best_overall else None,
        "current_best_cf_score": best_cf["cf_score"] if best_cf else None,
        "lowest_total_diff": lowest_diff["total_diff"] if lowest_diff else None,
    }


def _module_status(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    known = set(MODULE_ORDER)
    for module in MODULE_ORDER:
        candidates = [record for record in records if record.get("module") == module]
        scored_candidates = [record for record in candidates if record.get("overall") is not None]
        latest = max(scored_candidates or candidates, key=lambda record: _timestamp_key(record.get("timestamp")), default=None)
        done = latest is not None and latest.get("status") == "completed" and latest.get("target_reached") is True
        rows.append({
            "module": module,
            "label": MODULE_LABELS[module],
            "status": "DONE" if done else ("IN PROGRESS" if latest else "TODO"),
            "overall": (latest.get("module_score") if latest and latest.get("module_score") is not None else latest.get("overall")) if latest else None,
            "cf_score": latest.get("cf_score") if latest else None,
            "regression": latest.get("regressed") if latest else None,
            "latest_experiment": latest.get("experiment_id") if latest else None,
            "target_reached": done,
        })
    for module in sorted({record.get("module") for record in records} - known - {None, "other"}):
        rows.append({
            "module": module,
            "label": str(module).title(),
            "status": "DONE",
            "overall": None,
            "cf_score": None,
            "regression": None,
            "latest_experiment": None,
            "target_reached": True,
        })
    return rows


def build_dashboard(records: list[dict[str, Any]], generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    modules = _module_status(records)
    completed = [row for row in modules if row["status"] == "DONE"]
    remaining = [row["label"] for row in modules if row["status"] != "DONE"]
    trend = _trend(records)
    scored = _score_records(records)
    latest = records[-1] if records else None
    best = max(scored, key=lambda record: record["overall"], default=None)
    statistics = {
        "experiment_count": len(records),
        "scored_experiment_count": len(scored),
        "audit_or_unscored_count": len(records) - len(scored),
        "module_count": len(modules),
        "modules_completed": len(completed),
        "modules_remaining": len(remaining),
        "completion_pct": round(len(completed) / len(modules) * 100, 1) if modules else 0.0,
        "average_improvement": trend["average_improvement"],
        "largest_improvement": (trend["largest_improvement"] or {}).get("delta", 0.0),
        "largest_regression": (trend["largest_regression"] or {}).get("delta", 0.0),
        "current_best_score": trend["current_best_score"],
        "current_best_cf_score": trend["current_best_cf_score"],
        "lowest_total_diff": trend["lowest_total_diff"],
    }
    return {
        "project_summary": {
            "name": "Stealth Framework",
            "generated_at": generated_at,
            "experiments_detected": len(records),
            "modules_completed": len(completed),
            "modules_total": len(modules),
            "completion_pct": statistics["completion_pct"],
            "remaining_modules": remaining,
        },
        "current_best": deepcopy(best) if best else None,
        "latest_experiment": deepcopy(latest) if latest else None,
        "module_status": modules,
        "experiment_history": records,
        "trend": trend,
        "statistics": statistics,
    }


def _pct(value: Any) -> str:
    return "N/A" if value is None else f"{float(value):.1f}%"


def _cell(value: Any) -> str:
    return "N/A" if value is None else str(value)


def _bar(status: str) -> str:
    return "██████████ DONE" if status == "DONE" else ("█████□□□□□ IN PROGRESS" if status == "IN PROGRESS" else "□□□□□□□□□□ TODO")


def render_dashboard(data: dict[str, Any]) -> str:
    summary = data["project_summary"]
    stats = data["statistics"]
    best = data.get("current_best") or {}
    latest = data.get("latest_experiment") or {}
    lines = [
        "# STEALTH FRAMEWORK DASHBOARD",
        "",
        "## Project Summary",
        "",
        f"- Experiments detected: **{summary['experiments_detected']}**",
        f"- Modules completed: **{summary['modules_completed']} / {summary['modules_total']}** ({summary['completion_pct']:.1f}%)",
        f"- Generated: `{summary['generated_at']}`",
        "",
        "## Current Scores",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Overall | {_pct(latest.get('overall'))} |",
        f"| Best Overall | {_pct(stats['current_best_score'])} |",
        f"| Best CF | {_pct(stats['current_best_cf_score'])} |",
        f"| Current Diff | {_cell(latest.get('total_diff'))} |",
        f"| Latest Experiment | {_cell(latest.get('experiment_id'))} |",
        "",
        "## Project Status",
        "",
        "| Module | Status | Overall | CF Score | Regression | Latest Experiment | Target Reached |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for row in data["module_status"]:
        lines.append(
            f"| {row['label']} | {row['status']} | {_pct(row['overall'])} | {_pct(row['cf_score'])} | "
            f"{_cell(row['regression'])} | {_cell(row['latest_experiment'])} | "
            f"{'YES' if row['target_reached'] else 'NO'} |"
        )
    lines.extend(["", "## Module Progress", ""])
    for row in data["module_status"]:
        lines.append(f"- **{row['label']}**: {_bar(row['status'])}")
    lines.extend([
        "",
        "## Experiment Timeline",
        "",
        "| Experiment | Module | Overall | CF | Diff | Improved | Regressed | Date |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ])
    for record in data["experiment_history"]:
        lines.append(
            f"| {record['experiment_id']} | {record['module_label']} | {_pct(record.get('overall'))} | "
            f"{_pct(record.get('cf_score'))} | {_cell(record.get('total_diff'))} | "
            f"{_cell(record.get('improved'))} | {_cell(record.get('regressed'))} | "
            f"{str(record.get('timestamp', ''))[:19]} |"
        )
    trend = data["trend"]
    progression = " → ".join(_pct(value) for value in trend["overall_progression"]) or "N/A"
    lines.extend([
        "",
        "## Trend",
        "",
        f"Overall progression: **{progression}**",
        f"Average improvement: **{trend['average_improvement']:.2f} points**",
        f"Largest improvement: **{(trend['largest_improvement'] or {}).get('delta', 0.0):.2f} points**",
        f"Largest regression: **{(trend['largest_regression'] or {}).get('delta', 0.0):.2f} points**",
        f"Current best score: **{_pct(trend['current_best_score'])}**",
        f"Current best CF score: **{_pct(trend['current_best_cf_score'])}**",
        f"Lowest total diff: **{_cell(trend['lowest_total_diff'])}**",
        "",
        "## Best Experiment",
        "",
        f"{best.get('experiment_id', 'N/A')} — {best.get('module_label', 'N/A')} — {_pct(best.get('overall'))} overall, {_pct(best.get('cf_score'))} CF.",
        "",
        "## Remaining Modules",
        "",
    ])
    if summary["remaining_modules"]:
        lines.extend(f"- {module}" for module in summary["remaining_modules"])
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def render_history(history: list[dict[str, Any]]) -> str:
    lines = [
        "# Dashboard History",
        "",
        "Chronological log of experiment artifacts detected by the dashboard.",
        "",
        "| Experiment | Module | Overall | CF | Diff | Improved | Regressed | Status | Duration | Date |",
        "|---|---|---:|---:|---:|---:|---:|---|---:|---|",
    ]
    for record in history:
        lines.append(
            f"| {record.get('experiment_id', 'N/A')} | {record.get('module_label', 'Other')} | "
            f"{_pct(record.get('overall'))} | {_pct(record.get('cf_score'))} | "
            f"{_cell(record.get('total_diff'))} | {_cell(record.get('improved'))} | "
            f"{_cell(record.get('regressed'))} | {record.get('status', 'unknown')} | "
            f"{record.get('duration', 'N/A')} | {str(record.get('timestamp', ''))[:19]} |"
        )
    return "\n".join(lines) + "\n"


def _load_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = _read_json(path)
    if data is None:
        raise ValueError(f"Invalid dashboard history JSON: {path}")
    if isinstance(data.get("experiment_history"), list):
        return [item for item in data["experiment_history"] if isinstance(item, dict)]
    if isinstance(data.get("history"), list):
        return [item for item in data["history"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def merge_history(existing: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = [deepcopy(item) for item in existing]
    seen = {str(item.get("experiment_id")) for item in merged if item.get("experiment_id")}
    for record in current:
        if str(record.get("experiment_id")) not in seen:
            merged.append(deepcopy(record))
            seen.add(str(record.get("experiment_id")))
    return sorted(merged, key=lambda record: (_timestamp_key(record.get("timestamp")), str(record.get("experiment_id", ""))))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(root: Path | None = None) -> dict[str, Any]:
    root = (root or project_root()).resolve()
    experiments_dir = root / "reports" / "experiments"
    dashboard_dir = root / "reports" / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    records = scan_experiments(experiments_dir)
    generated_at = datetime.now(timezone.utc).isoformat()
    dashboard = build_dashboard(records, generated_at)
    history_path = dashboard_dir / "dashboard_history.json"
    history = merge_history(_load_history(history_path), records)
    _write_json(dashboard_dir / "dashboard.json", dashboard)
    _write_json(history_path, {
        "updated_at": generated_at,
        "experiment_history": history,
    })
    (dashboard_dir / "dashboard.md").write_text(render_dashboard(dashboard), encoding="utf-8")
    (dashboard_dir / "dashboard_history.md").write_text(render_history(history), encoding="utf-8")
    return dashboard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the Stealth Framework experiment dashboard.")
    parser.add_argument("--root", type=Path, default=None, help="Project root (defaults to repository root).")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    dashboard = run(args.root)
    summary = dashboard["project_summary"]
    stats = dashboard["statistics"]
    latest = dashboard.get("latest_experiment") or {}
    print("STEALTH FRAMEWORK DASHBOARD")
    print("")
    print(f"Overall          {_pct(latest.get('overall'))}")
    print(f"Best Overall     {_pct(stats.get('current_best_score'))}")
    print(f"Best CF          {_pct(stats.get('current_best_cf_score'))}")
    print(f"Current Diff     {_cell(latest.get('total_diff'))}")
    print(f"Modules Completed {summary['modules_completed']} / {summary['modules_total']}")
    remaining = summary.get("remaining_modules") or ["None"]
    print("Remaining        " + ", ".join(remaining))
    print(f"Experiments      {summary['experiments_detected']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
