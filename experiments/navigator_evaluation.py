"""Experiment 001: evaluate the navigator stealth module.

This is an experiment consumer of the existing framework. It intentionally
does not modify the framework runners or any of the comparison/scoring tools.

Modes are collected in fresh browser instances:

* plain: no init script
* generated: ``apply_generated()``
* navigator: ``apply_generated()`` followed by the navigator module

Run from the repository root with::

    python experiments/navigator_evaluation.py
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.baseline import Baseline, load_baseline, resolve_baseline_path
from experiments.metrics import ExperimentMetrics, calculate_metrics
from experiments.report import serialize_diffs
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


log = setup_logging("experiment.navigator_evaluation")


MODE_ORDER = ("plain", "generated", "navigator")
NAVIGATOR_PATCH_KEYS = (
    "navigator.webdriver",
    "navigator.languages",
    "navigator.language",
    "navigator.platform",
    "navigator.vendor",
    "navigator.deviceMemory",
    "navigator.hardwareConcurrency",
    "navigator.userAgentData",
    "navigator.plugins",
    "navigator.mimeTypes",
    "navigator.pdfViewerEnabled",
    "navigator.maxTouchPoints",
    "navigator.cookieEnabled",
    "navigator.onLine",
    "navigator.doNotTrack",
    "plugins.plugin_count",
    "plugins.mime_count",
)


@dataclass(frozen=True)
class ExperimentSettings:
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
class Collection:
    mode: str
    document: dict[str, Any]
    browser_version: str | None
    console_messages: list[dict[str, str]]

    @property
    def fingerprint(self) -> dict[str, Any]:
        value = self.document.get("fingerprint")
        if not isinstance(value, dict):
            raise ValueError(f"{self.mode} collection has no fingerprint object")
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


def collect_mode(settings: ExperimentSettings, mode: str) -> Collection:
    """Collect one mode in a clean Playwright browser instance."""
    if mode not in MODE_ORDER:
        raise ValueError(f"Unknown mode: {mode}")

    from playwright.sync_api import sync_playwright

    from tools._shared import BrowserConfig, launch_browser
    from tools.fingerprint_dump import collect as collect_plain
    from tools.test_stealth import collect as collect_patched
    from stealth import apply_generated
    from stealth.apply import apply_modules

    browser_config = BrowserConfig(
        channel=settings.channel,
        headless=settings.headless,
        profile=str(settings.profile) if settings.profile else "",
        url=settings.url,
        wait_ms=settings.wait_ms,
    )
    console_messages: list[dict[str, str]] = []
    log.info("Collect mode=%s", mode)

    with sync_playwright() as playwright:
        handle, page, _ = launch_browser(playwright, browser_config)
        try:
            page.on(
                "console",
                lambda message: console_messages.append(
                    {"type": message.type, "text": message.text}
                ),
            )
            if mode == "plain":
                fingerprint = collect_plain(page, settings.url, settings.wait_ms)
            else:
                apply_generated(page)
                if mode == "navigator":
                    # This is deliberately appended after generated patches so
                    # Navigator module accessors are the final page-layer.
                    apply_modules(page, ["navigator"])
                fingerprint = collect_patched(page, settings.url, settings.wait_ms)
            version = _browser_version(page)
        finally:
            handle.close()

    document = {
        "_meta": {
            "experiment": "Experiment 001 - Navigator Evaluation",
            "mode": mode,
            "collected_at": now_iso(),
            "url": settings.url,
            "channel": settings.channel or "chromium (bundled)",
            "headless": settings.headless,
            "wait_ms": settings.wait_ms,
            "generated_patches_applied": mode != "plain",
            "navigator_module_applied": mode == "navigator",
            "browser_version": version,
        },
        "fingerprint": fingerprint,
    }
    return Collection(mode, document, version, console_messages)


def _category_score(score_document: dict[str, Any], category: str) -> float | None:
    for item in score_document.get("categories", []):
        if isinstance(item, dict) and item.get("category") == category:
            value = item.get("score_pct")
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _metrics_document(
    metrics: ExperimentMetrics,
    *,
    total_diff: int,
    overall_similarity: float,
    weighted_cf_score: float,
    navigator_category_score: float | None,
    transition_from: str,
) -> dict[str, Any]:
    return {
        "transition_from": transition_from,
        "total_diff": total_diff,
        "improved_keys": len(metrics.improved_keys),
        "regressed_keys": len(metrics.regressed_keys),
        "unchanged_keys": len(metrics.unchanged_keys),
        "improved_key_names": metrics.improved_keys,
        "regressed_key_names": metrics.regressed_keys,
        "unchanged_key_names": metrics.unchanged_keys,
        "changed_but_remaining_keys": metrics.changed_remaining_keys,
        "overall_similarity": overall_similarity,
        "weighted_cf_score": weighted_cf_score,
        "navigator_category_score": navigator_category_score,
        "diff_reduction_from_previous": metrics.diff_reduction,
        "diff_reduction_pct_from_previous": metrics.diff_reduction_pct,
    }


def build_mode_artifacts(
    settings: ExperimentSettings,
    baseline: Baseline,
    collection: Collection,
    previous: Collection | None,
    previous_score: dict[str, Any] | None,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Build all JSON documents for one mode without writing them."""
    from tools.browser_score import score, to_dict
    from tools.compare_fingerprint import compare_flat, flatten
    from tools.patch_validator import compare_scores

    reference_flat = flatten(baseline.fingerprint)
    candidate_flat = flatten(collection.fingerprint)
    candidate_score = to_dict(score(reference_flat, candidate_flat))
    candidate_records = compare_flat(reference_flat, candidate_flat, False, [])

    previous_flat = flatten(previous.fingerprint) if previous else reference_flat
    previous_score_document = previous_score or to_dict(score(reference_flat, reference_flat))
    transition = "baseline" if previous is None else previous.mode
    patch_keys = ()
    if collection.mode == "generated":
        patch_keys = patch.get("keys", [])
    elif collection.mode == "navigator":
        patch_keys = NAVIGATOR_PATCH_KEYS

    metrics = calculate_metrics(
        reference_flat,
        previous_flat,
        candidate_flat,
        previous_score_document,
        candidate_score,
        patch_keys,
    )
    validation = compare_scores(reference_flat, previous_flat, candidate_flat)
    diff_count = len(candidate_records)
    navigator_score = _category_score(candidate_score, "Navigator")

    comparison = {
        "experiment": "Experiment 001 - Navigator Evaluation",
        "mode": collection.mode,
        "baseline": baseline.provenance(settings.root),
        "candidate": collection.document["_meta"],
        "diff_count": diff_count,
        "diffs": serialize_diffs(
            candidate_records,
            baseline_label=baseline.label,
            candidate_label=collection.mode,
        )["diffs"],
    }

    summary = {
        "experiment": "Experiment 001 - Navigator Evaluation",
        "mode": collection.mode,
        "status": "completed",
        "created_at": collection.document["_meta"]["collected_at"],
        "baseline": baseline.provenance(settings.root),
        "scores": {
            "overall_similarity": candidate_score.get("overall_score"),
            "weighted_cf_score": candidate_score.get("cf_risk_score"),
            "navigator_category_score": navigator_score,
        },
        "metrics": _metrics_document(
            metrics,
            total_diff=diff_count,
            overall_similarity=float(candidate_score.get("overall_score", 0.0)),
            weighted_cf_score=float(candidate_score.get("cf_risk_score", 0.0)),
            navigator_category_score=navigator_score,
            transition_from=transition,
        ),
        "validation": validation,
        "patch": {
            "generated": collection.mode != "plain",
            "navigator_module": collection.mode == "navigator",
            "generated_metadata": patch,
            "target_keys": list(patch_keys),
        },
        "environment": {
            "browser_version": collection.browser_version,
            "console_message_count": len(collection.console_messages),
            "console_messages": collection.console_messages,
        },
    }
    return {
        "fingerprint": collection.document,
        "compare": comparison,
        "score": candidate_score,
        "summary": summary,
    }


def _write_mode(output: Path, mode: str, artifacts: dict[str, Any]) -> None:
    mode_dir = output / mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    write_json_exclusive(mode_dir / "fingerprint.json", artifacts["fingerprint"])
    write_json_exclusive(mode_dir / "compare.json", artifacts["compare"])
    write_json_exclusive(mode_dir / "score.json", artifacts["score"])
    write_json_exclusive(mode_dir / "summary.json", artifacts["summary"])


def _number(value: Any) -> str:
    return "N/A" if value is None else f"{float(value):.1f}%"


def _conclusion(rows: dict[str, dict[str, Any]]) -> tuple[str, str]:
    generated = rows["generated"]["scores"]
    navigator = rows["navigator"]["scores"]
    generated_diff = rows["generated"]["metrics"]["total_diff"]
    navigator_diff = rows["navigator"]["metrics"]["total_diff"]

    better = 0
    worse = 0
    comparisons = [
        (navigator.get("overall_similarity"), generated.get("overall_similarity"), True),
        (navigator.get("weighted_cf_score"), generated.get("weighted_cf_score"), True),
        (navigator.get("navigator_category_score"), generated.get("navigator_category_score"), True),
        (navigator_diff, generated_diff, False),
    ]
    for current, reference, higher_is_better in comparisons:
        if current is None or reference is None:
            continue
        if higher_is_better:
            delta = float(current) - float(reference)
        else:
            delta = float(reference) - float(current)
        if delta > 1e-9:
            better += 1
        elif delta < -1e-9:
            worse += 1

    if better > worse:
        verdict = "lebih baik"
    elif worse > better:
        verdict = "lebih buruk"
    else:
        verdict = "sama"
    detail = (
        f"Navigator module {verdict} dibanding generated patch "
        f"(indikator lebih baik: {better}, lebih buruk: {worse})."
    )
    return verdict, detail


def render_report(
    settings: ExperimentSettings,
    rows: dict[str, dict[str, Any]],
) -> str:
    verdict, detail = _conclusion(rows)
    lines = [
        "# Experiment 001 — Navigator Evaluation",
        "",
        f"- Baseline: `{relative_path(settings.baseline.path, settings.root)}`",
        f"- URL: `{settings.url}`",
        f"- Headless: `{settings.headless}`",
        "",
        "| Mode | Overall | CF Score | Navigator % | Total Diff | Improved | Regressed |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {"plain": "Plain", "generated": "Generated", "navigator": "Navigator"}
    for mode in MODE_ORDER:
        row = rows[mode]
        metrics = row["metrics"]
        scores = row["scores"]
        lines.append(
            f"| {labels[mode]} | {_number(scores['overall_similarity'])} | "
            f"{_number(scores['weighted_cf_score'])} | "
            f"{_number(scores['navigator_category_score'])} | "
            f"{metrics['total_diff']} | {metrics['improved_keys']} | "
            f"{metrics['regressed_keys']} |"
        )
    lines.extend(
        [
            "",
            "## Unchanged Keys",
            "",
            "| Mode | Unchanged | Transition from |",
            "|---|---:|---|",
        ]
    )
    for mode in MODE_ORDER:
        metrics = rows[mode]["metrics"]
        lines.append(
            f"| {labels[mode]} | {metrics['unchanged_keys']} | {metrics['transition_from']} |"
        )
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            detail,
            "",
            "The conclusion votes on overall similarity, weighted CF score, "
            "Navigator category score, and total diff count.",
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Experiment 001: Plain vs Generated vs Navigator stealth.",
    )
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--reports-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None,
                        help="Experiment directory (default: reports/experiments/exp_001)")
    parser.add_argument("--url", default="")
    parser.add_argument("--channel", default="")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--wait", type=int, default=5_000)
    parser.add_argument("--label", default="navigator-evaluation")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    return parser


def run(settings: ExperimentSettings) -> int:
    expected = [
        settings.output / mode / filename
        for mode in MODE_ORDER
        for filename in ("fingerprint.json", "compare.json", "score.json", "summary.json")
    ]
    report_path = settings.output / "navigator_report.md"
    if all(path.is_file() for path in expected) and report_path.is_file():
        # Experiment artifacts are write-once. A completed run can be
        # inspected/reported again without launching browsers or overwriting
        # any existing artifact.
        print(report_path.read_text(encoding="utf-8"))
        return 0
    if any(path.exists() for path in expected) or report_path.exists():
        raise FileExistsError(
            f"Partial Experiment 001 artifacts already exist under {settings.output}"
        )

    patch = active_patch_metadata(settings.root)
    settings.output.mkdir(parents=True, exist_ok=True)
    collections: dict[str, Collection] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    previous: Collection | None = None
    previous_score: dict[str, Any] | None = None

    for mode in MODE_ORDER:
        collection = collect_mode(settings, mode)
        collections[mode] = collection
        mode_artifacts = build_mode_artifacts(
            settings,
            settings.baseline,
            collection,
            previous,
            previous_score,
            patch,
        )
        _write_mode(settings.output, mode, mode_artifacts)
        artifacts[mode] = mode_artifacts["summary"]
        previous = collection
        previous_score = mode_artifacts["score"]

    report = render_report(settings, artifacts)
    write_text_exclusive(settings.output / "navigator_report.md", report)

    print(report)
    return 0


def main() -> int:
    args = build_parser().parse_args()
    configure_console_error_handling()
    log.setLevel(getattr(logging, args.log_level))
    root = project_root()
    baseline_path = resolve_baseline_path(root, args.baseline)
    baseline = load_baseline(baseline_path)
    reports_dir = args.reports_dir or (root / "reports" / "experiments")
    if not reports_dir.is_absolute():
        reports_dir = root / reports_dir
    output = args.output or (reports_dir / "exp_001")
    if not output.is_absolute():
        output = root / output
    profile = args.profile
    if profile is not None and not profile.is_absolute():
        profile = root / profile
    if args.wait < 0:
        raise SystemExit("--wait must be zero or greater")
    url = args.url or str(baseline.metadata.get("url") or "about:blank")
    settings = ExperimentSettings(
        root=root,
        output=output.resolve(),
        baseline=baseline,
        url=url,
        channel=args.channel,
        headless=not args.no_headless,
        profile=profile.resolve() if profile else None,
        wait_ms=max(args.wait, 5_000),
        label=args.label,
    )
    return run(settings)


if __name__ == "__main__":
    raise SystemExit(main())
