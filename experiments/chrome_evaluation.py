"""Experiment 008: evaluate the Chrome runtime compatibility module.

The experiment reuses the repository's collectors, comparator, scorer,
validator, metrics, and immutable experiment-directory allocator.  Each mode
uses a fresh browser instance and the final mode adds only ``chrome.js`` on top
of the already evaluated Navigator, Window, and Screen modules.
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
from experiments.screen_evaluation import (
    _reported_regressions,
    _screen_profile,
    _window_profile,
)
from experiments.utils import (
    active_patch_metadata,
    configure_console_error_handling,
    now_iso,
    project_root,
    relative_path,
    write_json_exclusive,
    write_text_exclusive,
)
from tools._shared import setup_logging


log = setup_logging("experiment.chrome_evaluation")
MODE_ORDER = (
    "plain",
    "generated",
    "navigator",
    "navigator_window",
    "navigator_window_screen",
    "navigator_window_screen_chrome",
)
MODE_LABELS = {
    "plain": "Plain",
    "generated": "Generated",
    "navigator": "Navigator",
    "navigator_window": "Navigator + Window",
    "navigator_window_screen": "Navigator + Window + Screen",
    "navigator_window_screen_chrome": "Navigator + Window + Screen + Chrome",
}


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


def _chrome_profile(baseline: Baseline) -> dict[str, Any]:
    source = baseline.fingerprint.get("chrome")
    return dict(source) if isinstance(source, dict) else {}


def collect_mode(settings: Settings, mode: str) -> Collected:
    if mode not in MODE_ORDER:
        raise ValueError(f"Unknown mode: {mode}")

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
                profiles: dict[str, Any] = {}
                if mode in {"navigator_window", "navigator_window_screen", "navigator_window_screen_chrome"}:
                    profiles["windowProfile"] = _window_profile(settings.baseline)
                if mode in {"navigator_window_screen", "navigator_window_screen_chrome"}:
                    profiles["screenProfile"] = _screen_profile(settings.baseline)
                if mode == "navigator_window_screen_chrome":
                    profiles["chromeProfile"] = _chrome_profile(settings.baseline)
                if profiles:
                    serialized = json.dumps(profiles, ensure_ascii=False, separators=(",", ":"))
                    page.add_init_script(
                        "globalThis.__stealth=globalThis.__stealth||{};"
                        f"Object.assign(globalThis.__stealth,{serialized});"
                    )

                apply_generated(page)
                if mode in {"navigator", "navigator_window", "navigator_window_screen", "navigator_window_screen_chrome"}:
                    apply_modules(page, ["navigator"])
                if mode in {"navigator_window", "navigator_window_screen", "navigator_window_screen_chrome"}:
                    apply_modules(page, ["window"])
                if mode in {"navigator_window_screen", "navigator_window_screen_chrome"}:
                    apply_modules(page, ["screen"])
                if mode == "navigator_window_screen_chrome":
                    apply_modules(page, ["chrome"])
                fingerprint = collect_patched(page, settings.url, settings.wait_ms)
            version = _browser_version(page)
        finally:
            handle.close()

    return Collected(
        mode=mode,
        document={
            "_meta": {
                "experiment": "Experiment 008 - Chrome Runtime Evaluation",
                "mode": mode,
                "collected_at": now_iso(),
                "url": settings.url,
                "channel": settings.channel or "chromium (bundled)",
                "headless": settings.headless,
                "wait_ms": settings.wait_ms,
                "generated_patches_applied": mode != "plain",
                "navigator_module_applied": mode in {"navigator", "navigator_window", "navigator_window_screen", "navigator_window_screen_chrome"},
                "window_module_applied": mode in {"navigator_window", "navigator_window_screen", "navigator_window_screen_chrome"},
                "screen_module_applied": mode in {"navigator_window_screen", "navigator_window_screen_chrome"},
                "chrome_module_applied": mode == "navigator_window_screen_chrome",
                "window_profile_source": "baseline.window" if mode in {"navigator_window", "navigator_window_screen", "navigator_window_screen_chrome"} else None,
                "screen_profile_source": "baseline.screen" if mode in {"navigator_window_screen", "navigator_window_screen_chrome"} else None,
                "chrome_profile_source": "baseline.chrome" if mode == "navigator_window_screen_chrome" else None,
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
    transition = previous.mode if previous else "baseline"
    metrics = calculate_metrics(
        reference_flat,
        previous_flat,
        current_flat,
        before_score,
        current_score,
        patch.get("keys", []) if current.mode == "generated" else (),
    )
    validation = compare_scores(reference_flat, previous_flat, current_flat)
    reported_regressions, environmental_regressions = _reported_regressions(metrics.regressed_keys)
    if isinstance(validation.get("keys"), dict):
        validation = dict(validation)
        validation_keys = dict(validation["keys"])
        validation_keys["regressed"] = reported_regressions
        validation["keys"] = validation_keys
        if isinstance(validation.get("counts"), dict):
            validation_counts = dict(validation["counts"])
            validation_counts["regressed"] = len(reported_regressions)
            validation["counts"] = validation_counts

    comparison = {
        "mode": current.mode,
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
        "transition_from": transition,
        "scores": {
            "overall_similarity": current_score.get("overall_score"),
            "weighted_cf_score": current_score.get("cf_risk_score"),
            "chrome_category_score": _category_score(current_score, "Chrome"),
            "navigator_category_score": _category_score(current_score, "Navigator"),
            "window_category_score": _category_score(current_score, "Window"),
            "screen_category_score": _category_score(current_score, "Screen"),
        },
        "metrics": {
            "total_diff": len(current_records),
            "improved": len(metrics.improved_keys),
            "regressed": len(reported_regressions),
            "unchanged": len(metrics.unchanged_keys),
            "improved_keys": metrics.improved_keys,
            "regressed_keys": reported_regressions,
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
    before = rows["navigator_window_screen"]["summary"]
    after = rows["navigator_window_screen_chrome"]["summary"]
    before_scores = before["scores"]
    after_scores = after["scores"]
    indicators = (
        "overall_similarity",
        "weighted_cf_score",
        "chrome_category_score",
        "navigator_category_score",
        "window_category_score",
        "screen_category_score",
    )
    improvements = sum(
        float(after_scores.get(key) or 0) > float(before_scores.get(key) or 0)
        for key in indicators
    )
    regressions = int(after["metrics"]["regressed"])
    chrome_score = float(after_scores.get("chrome_category_score") or 0)
    if regressions == 0 and improvements >= 2 and chrome_score >= 90:
        return "Chrome Runtime meningkatkan fingerprint dibanding Navigator + Window + Screen tanpa stable regression."
    if regressions:
        return f"Chrome Runtime menghasilkan {regressions} stable regression; module perlu diaudit sebelum dianggap aman."
    return "Chrome Runtime belum mencapai peningkatan yang cukup dibanding Navigator + Window + Screen."


def render_report(rows: dict[str, dict[str, Any]], output: Path) -> str:
    lines = [
        "# Experiment 008 — Chrome Runtime Evaluation",
        "",
        f"Output: `{output}`",
        "",
        "| Mode | Overall | CF Score | Chrome | Navigator | Window | Screen | Total Diff | Improved | Regressed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in MODE_ORDER:
        row = rows[mode]["summary"]
        scores = row["scores"]
        metrics = row["metrics"]
        lines.append(
            f"| {MODE_LABELS[mode]} | {_number(scores['overall_similarity'])} | "
            f"{_number(scores['weighted_cf_score'])} | {_number(scores['chrome_category_score'])} | "
            f"{_number(scores['navigator_category_score'])} | {_number(scores['window_category_score'])} | "
            f"{_number(scores['screen_category_score'])} | {metrics['total_diff']} | "
            f"{metrics['improved']} | {metrics['regressed']} |"
        )
    lines.extend(
        [
            "",
            "Environmental note: network-sampled Navigator connection values are "
            "listed separately and excluded from stable regression counts.",
            "",
            "## Conclusion",
            "",
            _conclusion(rows),
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Experiment 008: Chrome Runtime Evaluation.")
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--reports-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--url", default="")
    parser.add_argument("--channel", default="")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--wait", type=int, default=5_000)
    parser.add_argument("--label", default="chrome-evaluation")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    return parser


def run(settings: Settings) -> int:
    patch = active_patch_metadata(settings.root)
    experiment = Experiment.create(settings.output)
    output = experiment.directory / "chrome"
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
        previous = current
        previous_score = result["score"]

    compare_document = {
        "experiment": "Experiment 008 - Chrome Runtime Evaluation",
        "experiment_id": experiment.experiment_id,
        "baseline": settings.baseline.provenance(settings.root),
        "modes": {mode: results[mode]["comparison"] for mode in MODE_ORDER},
    }
    score_document = {
        "experiment": "Experiment 008 - Chrome Runtime Evaluation",
        "experiment_id": experiment.experiment_id,
        "modes": {mode: results[mode]["score"] for mode in MODE_ORDER},
    }
    summary_document = {
        "experiment": "Experiment 008 - Chrome Runtime Evaluation",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "inputs": {
            "baseline": relative_path(settings.baseline.path, settings.root),
            "window_profile_source": "baseline.window",
            "screen_profile_source": "baseline.screen",
            "chrome_profile_source": "baseline.chrome",
        },
        "patch": patch,
        "modes": {mode: results[mode]["summary"] for mode in MODE_ORDER},
        "conclusion": _conclusion(results),
    }
    fingerprint_document = {
        "experiment": "Experiment 008 - Chrome Runtime Evaluation",
        "experiment_id": experiment.experiment_id,
        "modes": {mode: results[mode]["fingerprint"] for mode in MODE_ORDER},
    }
    write_json_exclusive(output / "fingerprint.json", fingerprint_document)
    write_json_exclusive(output / "compare.json", compare_document)
    write_json_exclusive(output / "score.json", score_document)
    write_json_exclusive(output / "summary.json", summary_document)
    report = render_report(results, output)
    write_text_exclusive(output / "chrome_report.md", report)
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
