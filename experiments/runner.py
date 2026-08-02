"""CLI entry point for repeatable before/after fingerprint experiments."""
from __future__ import annotations

import argparse
import logging
import sys
import traceback

from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.baseline import Baseline, load_baseline, resolve_baseline_path
from experiments.experiment import Experiment, ExperimentConfig
from experiments.metrics import calculate_metrics
from experiments.report import (
    build_summary,
    comparison_document,
    render_console,
    render_markdown,
)
from experiments.utils import (
    active_patch_metadata,
    configure_console_error_handling,
    git_metadata,
    now_iso,
    observed_environment,
    package_version,
    project_root,
    relative_path,
    system_metadata,
)
from tools._shared import setup_logging


log = setup_logging("experiment.runner")


@dataclass(frozen=True)
class CollectionResult:
    document: dict[str, Any]
    browser_version: str | None
    console_messages: list[dict[str, str]]

    @property
    def fingerprint(self) -> dict[str, Any]:
        return self.document["fingerprint"]


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


def _collect_fingerprint(config: ExperimentConfig, *, patched: bool) -> CollectionResult:
    """Launch one isolated browser, optionally apply patches, and collect data."""
    from playwright.sync_api import sync_playwright
    from stealth import apply_generated
    from tools._shared import BrowserConfig, launch_browser
    from tools.fingerprint_dump import collect as collect_before
    from tools.test_stealth import collect as collect_after

    browser_config = BrowserConfig(
        channel=config.channel,
        headless=config.headless,
        profile=str(config.profile) if config.profile else "",
        url=config.url,
        wait_ms=config.wait_ms,
    )
    console_messages: list[dict[str, str]] = []
    phase = "after" if patched else "before"

    with sync_playwright() as playwright:
        handle, page, _ = launch_browser(playwright, browser_config)
        try:
            page.on(
                "console",
                lambda message: console_messages.append(
                    {"type": message.type, "text": message.text}
                ),
            )
            if patched:
                log.info("Apply generated patches before navigation")
                apply_generated(page)
                fingerprint = collect_after(page, config.url, config.wait_ms)
            else:
                fingerprint = collect_before(page, config.url, config.wait_ms)
            version = _browser_version(page)
        finally:
            handle.close()

    document = {
        "_meta": {
            "tool": "experiments.runner",
            "phase": phase,
            "collected_at": now_iso(),
            "url": config.url,
            "channel": config.channel or "chromium (bundled)",
            "headless": config.headless,
            "wait_ms": config.wait_ms,
            "generated_patches_applied": patched,
            "browser_version": version,
        },
        "fingerprint": fingerprint,
    }
    return CollectionResult(document, version, console_messages)


def _base_metadata(
    experiment: Experiment,
    config: ExperimentConfig,
    baseline: Baseline,
    patch: dict[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    git = git_metadata(config.project_root)
    return {
        "experiment_id": experiment.experiment_id,
        "date": experiment.started_at,
        "completed_at": now_iso() if status != "running" else None,
        "status": status,
        "label": config.label or None,
        "os": system_metadata(),
        "browser_version": None,
        "chrome_channel": config.channel or "chromium (bundled)",
        "playwright_version": package_version("playwright"),
        "headless": config.headless,
        "viewport": None,
        "locale": None,
        "timezone": None,
        "url": config.url,
        "patch_version": patch.get("version"),
        "git_commit": git.get("commit"),
        "git_dirty": git.get("dirty"),
        "profile": relative_path(config.profile, config.project_root) if config.profile else None,
        "wait_ms": config.wait_ms,
        "baseline": baseline.provenance(config.project_root),
        "patch": patch,
        "output_directory": relative_path(experiment.directory, config.project_root),
    }


def _complete_metadata(
    experiment: Experiment,
    config: ExperimentConfig,
    baseline: Baseline,
    patch: dict[str, Any],
    before: CollectionResult,
    after: CollectionResult,
) -> dict[str, Any]:
    metadata = _base_metadata(
        experiment, config, baseline, patch, status="completed"
    )
    before_environment = observed_environment(before.fingerprint)
    after_environment = observed_environment(after.fingerprint)
    metadata.update(
        {
            "browser_version": before.browser_version or after.browser_version,
            "viewport": before_environment.get("viewport"),
            "locale": before_environment.get("locale"),
            "timezone": before_environment.get("timezone"),
            "observed_environment": {
                "before": before_environment,
                "after": after_environment,
            },
            "browser_versions": {
                "before": before.browser_version,
                "after": after.browser_version,
            },
            "console": {
                "before_count": len(before.console_messages),
                "after_count": len(after.console_messages),
                "after_patch_failures": [
                    item
                    for item in after.console_messages
                    if "[stealth] patch failed" in item.get("text", "")
                ],
            },
        }
    )
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an immutable before/after browser fingerprint experiment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python experiments/runner.py
  python experiments/runner.py --channel chrome --url about:blank
  python experiments/runner.py --baseline reports/fingerprint/fingerprint_real.json
  python experiments/runner.py --no-headless --label headed-chrome
""",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Reference fingerprint JSON (default: repository real-Chrome baseline)",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=None,
        help="Experiment output root (default: reports/experiments)",
    )
    parser.add_argument(
        "--url",
        default="",
        help="Collection URL (default: baseline URL, then about:blank)",
    )
    parser.add_argument(
        "--channel",
        default="",
        help="Playwright browser channel, for example 'chrome'",
    )
    parser.add_argument("--no-headless", action="store_true", help="Run a visible browser")
    parser.add_argument("--profile", type=Path, default=None, help="Persistent profile path")
    parser.add_argument(
        "--wait",
        type=int,
        default=5_000,
        help="Wait after navigation in milliseconds (default: 5000)",
    )
    parser.add_argument("--label", default="", help="Optional experiment label")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    return parser


def run(config: ExperimentConfig) -> int:
    configure_console_error_handling()
    baseline = load_baseline(config.baseline_path)
    patch = active_patch_metadata(config.project_root)
    experiment = Experiment.create(config.reports_root)
    log.info("Experiment %s -> %s", experiment.experiment_id, experiment.directory)

    try:
        log.info("Step 1/7: collect unpatched Playwright fingerprint")
        before = _collect_fingerprint(config, patched=False)
        experiment.write_json("fingerprint_before.json", before.document)

        log.info("Step 2/7: apply generated patches and collect patched fingerprint")
        after = _collect_fingerprint(config, patched=True)
        experiment.write_json("fingerprint_after.json", after.document)

        from tools.browser_score import score, to_dict
        from tools.compare_fingerprint import compare_flat, flatten
        from tools.patch_validator import compare_scores

        flat_reference = flatten(baseline.fingerprint)
        flat_before = flatten(before.fingerprint)
        flat_after = flatten(after.fingerprint)

        log.info("Step 3/7: compare before and after against baseline")
        before_records = compare_flat(flat_reference, flat_before, False, [])
        after_records = compare_flat(flat_reference, flat_after, False, [])
        comparison = comparison_document(
            before_records,
            after_records,
            baseline_label=baseline.label,
        )
        experiment.write_json("compare.json", comparison)

        log.info("Step 4/7: calculate browser scores")
        score_before = to_dict(score(flat_reference, flat_before))
        score_after = to_dict(score(flat_reference, flat_after))
        experiment.write_json("score_before.json", score_before)
        experiment.write_json("score_after.json", score_after)

        log.info("Step 5/7: validate and calculate experiment metrics")
        validation = compare_scores(flat_reference, flat_before, flat_after)
        metrics = calculate_metrics(
            flat_reference,
            flat_before,
            flat_after,
            score_before,
            score_after,
            patch.get("keys", []),
        )

        metadata = _complete_metadata(
            experiment, config, baseline, patch, before, after
        )
        summary = build_summary(
            metadata=metadata,
            baseline=baseline.provenance(config.project_root),
            patch=patch,
            comparison=comparison,
            score_before=score_before,
            score_after=score_after,
            validation=validation,
            metrics=metrics,
        )

        log.info("Step 6/7: generate JSON, Markdown, and console reports")
        experiment.write_json("summary.json", summary)
        experiment.write_text("summary.md", render_markdown(summary))
        print(render_console(summary))

        log.info("Step 7/7: commit immutable experiment metadata")
        experiment.write_json("metadata.json", metadata)
        return 0
    except Exception as exc:
        log.exception("Experiment %s failed", experiment.experiment_id)
        metadata = _base_metadata(
            experiment, config, baseline, patch, status="failed"
        )
        metadata["error"] = {"type": type(exc).__name__, "message": str(exc)}
        experiment.record_failure(
            metadata,
            {
                "experiment_id": experiment.experiment_id,
                "failed_at": now_iso(),
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        return 1


def main() -> int:
    args = build_parser().parse_args()
    log.setLevel(getattr(logging, args.log_level))
    root = project_root()
    baseline_path = resolve_baseline_path(root, args.baseline)
    baseline = load_baseline(baseline_path)
    reports_root = args.reports_dir or (root / "reports" / "experiments")
    if not reports_root.is_absolute():
        reports_root = root / reports_root
    profile = args.profile
    if profile is not None and not profile.is_absolute():
        profile = root / profile
    if args.wait < 0:
        build_parser().error("--wait must be zero or greater")
    url = args.url or str(baseline.metadata.get("url") or "about:blank")
    config = ExperimentConfig(
        project_root=root,
        reports_root=reports_root.resolve(),
        baseline_path=baseline.path,
        url=url,
        channel=args.channel,
        headless=not args.no_headless,
        profile=profile.resolve() if profile else None,
        wait_ms=max(args.wait, 5_000),
        label=args.label,
    )
    return run(config)


if __name__ == "__main__":
    sys.exit(main())
