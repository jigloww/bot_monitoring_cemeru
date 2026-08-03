"""Experiment 014: evaluate the profile-aware WebGL compatibility module.

The experiment deliberately keeps the previous stack immutable.  The
``previous_stack`` row reads the completed Experiment 012 artifact, while the
final row launches a fresh context with the same stack plus WebGL.  Every
browser observation is compared with the existing baseline and all artifacts
are write-once under a new ``exp_xxx/webgl`` directory.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.baseline import Baseline, load_baseline, resolve_baseline_path
from experiments.experiment import Experiment
from experiments.metrics import calculate_metrics
from experiments.report import serialize_diffs
from experiments.screen_evaluation import _reported_regressions
from experiments.utils import (
    active_patch_metadata,
    configure_console_error_handling,
    now_iso,
    project_root,
    read_json,
    relative_path,
    write_json_exclusive,
    write_text_exclusive,
)
from tools._shared import setup_logging


log = setup_logging("experiment.webgl_evaluation")
MODE_ORDER = ("plain", "generated", "full_stack", "previous_stack", "previous_stack_webgl")
MODE_LABELS = {
    "plain": "Plain",
    "generated": "Generated",
    "full_stack": "Navigator + Window + Screen + Chrome + Permissions + Fonts + Speech + Performance",
    "previous_stack": "Previous Stack",
    "previous_stack_webgl": "Previous Stack + WebGL",
}
PREVIOUS_MODULES = [
    "navigator", "window", "screen", "chrome", "permissions", "fonts", "speech", "performance",
]


@dataclass(frozen=True)
class Settings:
    root: Path
    output: Path
    baseline: Baseline
    url: str
    channel: str
    headless: bool
    profile: Path | None
    wait_ms: int
    label: str


@dataclass(frozen=True)
class Collected:
    mode: str
    document: dict[str, Any]
    browser_version: str | None
    console_messages: list[dict[str, str]]

    @property
    def fingerprint(self) -> dict[str, Any]:
        value = self.document.get("fingerprint")
        if not isinstance(value, dict):
            raise ValueError(f"Missing fingerprint for mode {self.mode}")
        return value


def _section(baseline: Baseline, name: str) -> dict[str, Any]:
    value = baseline.fingerprint.get(name)
    return dict(value) if isinstance(value, dict) else {}


def _speech_profile(baseline: Baseline) -> dict[str, Any]:
    profile = _section(baseline, "speech")
    voices: list[dict[str, Any]] = []
    for voice in profile.get("voices", []):
        if not isinstance(voice, dict):
            continue
        item = dict(voice)
        if "localService" not in item and "local" in item:
            item["localService"] = item["local"]
        voices.append(item)
    profile["voices"] = voices
    return profile


def _profiles(baseline: Baseline, include_webgl: bool) -> dict[str, Any]:
    profiles: dict[str, Any] = {
        "windowProfile": _section(baseline, "window"),
        "screenProfile": _section(baseline, "screen"),
        "chromeProfile": _section(baseline, "chrome"),
        "permissionsProfile": _section(baseline, "permissions"),
        "fontProfile": _section(baseline, "fonts"),
        "speechProfile": _speech_profile(baseline),
        "performanceProfile": _section(baseline, "performance"),
    }
    if include_webgl:
        profiles["webglProfile"] = {
            "webgl": _section(baseline, "webgl"),
            "webgl2": _section(baseline, "webgl2"),
        }
    return profiles


def _browser_version(page: Any) -> str | None:
    try:
        browser = page.context.browser
        if browser is not None:
            return browser.version
    except Exception:
        pass
    try:
        return page.evaluate("() => navigator.userAgent")
    except Exception:
        return None


def _previous_stack_path(root: Path) -> Path:
    return root / "reports" / "experiments" / "exp_012" / "performance" / "performance" / "fingerprint.json"


def _load_previous_stack(root: Path) -> Collected:
    path = _previous_stack_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"Previous stack artifact not found: {path}")
    document = read_json(path)
    if not isinstance(document, dict):
        raise ValueError(f"Previous stack artifact is not an object: {path}")
    if not isinstance(document.get("fingerprint"), dict):
        raise ValueError(f"Previous stack artifact has no fingerprint: {path}")
    metadata = document.get("_meta", {}) if isinstance(document.get("_meta"), dict) else {}
    return Collected(
        mode="previous_stack",
        document={"_meta": metadata, "fingerprint": document["fingerprint"]},
        browser_version=metadata.get("browser_version"),
        console_messages=[],
    )


def collect_mode(settings: Settings, mode: str) -> Collected:
    if mode not in MODE_ORDER:
        raise ValueError(f"Unknown mode: {mode}")
    if mode == "previous_stack":
        return _load_previous_stack(settings.root)

    from playwright.sync_api import sync_playwright

    from stealth import apply_generated
    from stealth.apply import apply_modules
    from tools._shared import BrowserConfig, launch_browser
    from tools.fingerprint_dump import collect as collect_plain
    from tools.test_stealth import collect as collect_patched

    config = BrowserConfig(
        channel=settings.channel,
        headless=settings.headless,
        profile=str(settings.profile) if settings.profile else "",
        url=settings.url,
        wait_ms=settings.wait_ms,
    )
    modules = [] if mode in {"plain", "generated"} else list(PREVIOUS_MODULES)
    include_webgl = mode == "previous_stack_webgl"
    if include_webgl:
        modules.append("webgl")
    messages: list[dict[str, str]] = []
    with sync_playwright() as playwright:
        handle, page, _ = launch_browser(playwright, config)
        try:
            page.on(
                "console",
                lambda message: messages.append({"type": message.type, "text": message.text}),
            )
            if mode == "plain":
                fingerprint = collect_plain(page, settings.url, settings.wait_ms)
            else:
                profiles = _profiles(settings.baseline, include_webgl)
                serialized = json.dumps(profiles, ensure_ascii=False, separators=(",", ":"))
                page.add_init_script(
                    "globalThis.__stealth=globalThis.__stealth||{};"
                    f"Object.assign(globalThis.__stealth,{serialized});"
                )
                apply_generated(page)
                apply_modules(page, modules)
                fingerprint = collect_patched(page, settings.url, settings.wait_ms)
            version = _browser_version(page)
        finally:
            handle.close()

    return Collected(
        mode=mode,
        document={
            "_meta": {
                "experiment": "Experiment 014 - WebGL Evaluation",
                "mode": mode,
                "label": MODE_LABELS[mode],
                "collected_at": now_iso(),
                "url": settings.url,
                "channel": settings.channel or "chromium (bundled)",
                "headless": settings.headless,
                "wait_ms": settings.wait_ms,
                "generated_patches_applied": mode != "plain",
                "modules_applied": modules,
                "webgl_profile_source": "baseline.webgl + baseline.webgl2" if include_webgl else None,
                "browser_version": version,
            },
            "fingerprint": fingerprint,
        },
        browser_version=version,
        console_messages=messages,
    )


def _category_score(score_document: dict[str, Any], category: str) -> float | None:
    for row in score_document.get("categories", []):
        if isinstance(row, dict) and row.get("category") == category:
            value = row.get("score_pct")
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _mode_result(
    settings: Settings,
    baseline: Baseline,
    current: Collected,
    previous: Collected | None,
    previous_score: dict[str, Any] | None,
    patch: dict[str, Any],
) -> dict[str, Any]:
    from tools.browser_score import score, to_dict
    from tools.compare_fingerprint import compare_flat, flatten
    from tools.patch_validator import compare_scores

    reference_flat = flatten(baseline.fingerprint)
    current_flat = flatten(current.fingerprint)
    current_score = to_dict(score(reference_flat, current_flat))
    current_records = compare_flat(reference_flat, current_flat, False, [])
    previous_flat = flatten(previous.fingerprint) if previous else reference_flat
    before_score = previous_score or to_dict(score(reference_flat, reference_flat))
    metrics = calculate_metrics(
        reference_flat,
        previous_flat,
        current_flat,
        before_score,
        current_score,
        patch.get("keys", []) if current.mode == "generated" else (),
    )
    stable_regressions, environmental_regressions = _reported_regressions(metrics.regressed_keys)
    validation = compare_scores(reference_flat, previous_flat, current_flat)
    if isinstance(validation.get("keys"), dict):
        validation = dict(validation)
        keys = dict(validation["keys"])
        keys["regressed"] = stable_regressions
        validation["keys"] = keys
        if isinstance(validation.get("counts"), dict):
            counts = dict(validation["counts"])
            counts["regressed"] = len(stable_regressions)
            validation["counts"] = counts

    comparison = {
        "mode": current.mode,
        "label": MODE_LABELS[current.mode],
        "baseline": baseline.provenance(settings.root),
        "candidate": current.document["_meta"],
        "diff_count": len(current_records),
        "diffs": serialize_diffs(
            current_records,
            baseline_label=baseline.label,
            candidate_label=current.mode,
        )["diffs"],
    }
    summary = {
        "mode": current.mode,
        "label": MODE_LABELS[current.mode],
        "transition_from": previous.mode if previous else "baseline",
        "scores": {
            "overall_similarity": current_score.get("overall_score"),
            "weighted_cf_score": current_score.get("cf_risk_score"),
            "webgl_category_score": _category_score(current_score, "WebGL"),
            "navigator_category_score": _category_score(current_score, "Navigator"),
            "window_category_score": _category_score(current_score, "Window"),
            "screen_category_score": _category_score(current_score, "Screen"),
            "chrome_category_score": _category_score(current_score, "Chrome"),
            "permissions_category_score": _category_score(current_score, "Permissions"),
            "fonts_category_score": _category_score(current_score, "Fonts"),
            "speech_category_score": _category_score(current_score, "Speech"),
            "performance_category_score": _category_score(current_score, "Performance"),
        },
        "metrics": {
            "total_diff": len(current_records),
            "improved": len(metrics.improved_keys),
            "regressed": len(stable_regressions),
            "unchanged": len(metrics.unchanged_keys),
            "improved_keys": metrics.improved_keys,
            "regressed_keys": stable_regressions,
            "environmental_regressions": environmental_regressions,
            "unchanged_keys": metrics.unchanged_keys,
            "diff_reduction_from_previous": metrics.diff_reduction,
        },
        "validation": validation,
        "environment": {
            "browser_version": current.browser_version,
            "console_message_count": len(current.console_messages),
            "console_messages": current.console_messages,
        },
    }
    return {"fingerprint": current.document, "comparison": comparison, "score": current_score, "summary": summary}


def _number(value: Any) -> str:
    return "N/A" if value is None else f"{float(value):.1f}%"


def _conclusion(rows: dict[str, dict[str, Any]]) -> str:
    before = rows["previous_stack"]["summary"]
    after = rows["previous_stack_webgl"]["summary"]
    before_scores, after_scores = before["scores"], after["scores"]
    regressions = int(after["metrics"]["regressed"])
    webgl_before = float(before_scores.get("webgl_category_score") or 0)
    webgl_after = float(after_scores.get("webgl_category_score") or 0)
    overall_before = float(before_scores.get("overall_similarity") or 0)
    overall_after = float(after_scores.get("overall_similarity") or 0)
    cf_before = float(before_scores.get("weighted_cf_score") or 0)
    cf_after = float(after_scores.get("weighted_cf_score") or 0)
    diff_reduced = int(after["metrics"]["total_diff"]) < int(before["metrics"]["total_diff"])
    if regressions:
        return f"WebGL Module memperkenalkan {regressions} stable regression; hasil perlu diaudit sebelum diaktifkan lebih luas."
    if webgl_after > webgl_before and overall_after > overall_before and cf_after > cf_before and diff_reduced:
        return "WebGL Module meningkatkan WebGL dan similarity keseluruhan tanpa stable regression."
    if webgl_after > webgl_before and regressions == 0:
        return "WebGL Module meningkatkan category WebGL tanpa stable regression, tetapi perubahan global belum memenuhi seluruh indikator."
    if webgl_after == webgl_before:
        return "WebGL Module tidak mengubah category WebGL pada sampel ini; native fallback tetap konsisten."
    return "WebGL Module belum meningkatkan fingerprint secara keseluruhan dibanding Previous Stack."


def render_report(rows: dict[str, dict[str, Any]], output: Path) -> str:
    lines = [
        "# Experiment 014 - WebGL Evaluation",
        "",
        f"Output: `{output}`",
        "",
        "| Mode | Overall | CF Score | WebGL Score | Total Diff | Improved | Regressed |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in MODE_ORDER:
        summary = rows[mode]["summary"]
        scores, metrics = summary["scores"], summary["metrics"]
        lines.append(
            f"| {MODE_LABELS[mode]} | {_number(scores['overall_similarity'])} | "
            f"{_number(scores['weighted_cf_score'])} | {_number(scores['webgl_category_score'])} | "
            f"{metrics['total_diff']} | {metrics['improved']} | {metrics['regressed']} |"
        )
    before = rows["previous_stack"]["summary"]["scores"]
    after = rows["previous_stack_webgl"]["summary"]["scores"]
    lines.extend([
        "",
        "Delta vs Previous Stack: "
        f"Overall {float(after['overall_similarity']) - float(before['overall_similarity']):+.1f} pp, "
        f"CF {float(after['weighted_cf_score']) - float(before['weighted_cf_score']):+.1f} pp, "
        f"WebGL {float(after['webgl_category_score'] or 0) - float(before['webgl_category_score'] or 0):+.1f} pp.",
        "",
        "Environmental note: network-sampled Navigator connection values are excluded from stable regression counts.",
        "",
        "## Conclusion",
        "",
        _conclusion(rows),
        "",
    ])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Experiment 014: WebGL Evaluation.")
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--reports-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--url", default="")
    parser.add_argument("--channel", default="")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--wait", type=int, default=5_000)
    parser.add_argument("--label", default="webgl-evaluation")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    return parser


def run(settings: Settings) -> int:
    patch = active_patch_metadata(settings.root)
    experiment = Experiment.create(settings.output)
    output = experiment.directory / "webgl"
    output.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}
    previous: Collected | None = None
    previous_score: dict[str, Any] | None = None

    for mode in MODE_ORDER:
        current = collect_mode(settings, mode)
        result = _mode_result(settings, settings.baseline, current, previous, previous_score, patch)
        mode_dir = output / mode
        mode_dir.mkdir(parents=True, exist_ok=True)
        write_json_exclusive(mode_dir / "fingerprint.json", result["fingerprint"])
        write_json_exclusive(mode_dir / "compare.json", result["comparison"])
        write_json_exclusive(mode_dir / "score.json", result["score"])
        write_json_exclusive(mode_dir / "summary.json", result["summary"])
        results[mode] = result
        previous, previous_score = current, result["score"]

    compare_document = {
        "experiment": "Experiment 014 - WebGL Evaluation",
        "experiment_id": experiment.experiment_id,
        "baseline": settings.baseline.provenance(settings.root),
        "modes": {mode: results[mode]["comparison"] for mode in MODE_ORDER},
    }
    score_document = {
        "experiment": "Experiment 014 - WebGL Evaluation",
        "experiment_id": experiment.experiment_id,
        "modes": {mode: results[mode]["score"] for mode in MODE_ORDER},
    }
    summary_document = {
        "experiment": "Experiment 014 - WebGL Evaluation",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "inputs": {
            "baseline": relative_path(settings.baseline.path, settings.root),
            "webgl_profile_source": "baseline.webgl + baseline.webgl2",
            "previous_stack_source": relative_path(_previous_stack_path(settings.root), settings.root),
        },
        "patch": patch,
        "modes": {mode: results[mode]["summary"] for mode in MODE_ORDER},
        "conclusion": _conclusion(results),
    }
    fingerprint_document = {
        "experiment": "Experiment 014 - WebGL Evaluation",
        "experiment_id": experiment.experiment_id,
        "modes": {mode: results[mode]["fingerprint"] for mode in MODE_ORDER},
    }
    write_json_exclusive(output / "fingerprint.json", fingerprint_document)
    write_json_exclusive(output / "compare.json", compare_document)
    write_json_exclusive(output / "score.json", score_document)
    write_json_exclusive(output / "summary.json", summary_document)
    report = render_report(results, output)
    write_text_exclusive(output / "webgl_report.md", report)
    print(report)
    return 0


def main() -> int:
    args = build_parser().parse_args()
    configure_console_error_handling()
    log.setLevel(getattr(logging, args.log_level))
    root = project_root()
    baseline = load_baseline(resolve_baseline_path(root, args.baseline))
    reports_dir = args.reports_dir or root / "reports/experiments"
    if not reports_dir.is_absolute():
        reports_dir = root / reports_dir
    output = args.output or reports_dir
    if not output.is_absolute():
        output = root / output
    profile = args.profile
    if profile is not None and not profile.is_absolute():
        profile = root / profile
    if args.wait < 0:
        raise SystemExit("--wait must be zero or greater")
    settings = Settings(
        root=root,
        output=output.resolve(),
        baseline=baseline,
        url=args.url or str(baseline.metadata.get("url") or "about:blank"),
        channel=args.channel,
        headless=not args.no_headless,
        profile=profile.resolve() if profile else None,
        wait_ms=max(args.wait, 5_000),
        label=args.label,
    )
    return run(settings)


if __name__ == "__main__":
    raise SystemExit(main())
