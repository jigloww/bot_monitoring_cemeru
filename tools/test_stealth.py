"""
tools/test_stealth.py — Test stealth patches against a live website.

Launches Playwright, applies all generated stealth patches, navigates to the
target URL, collects a full browser fingerprint, and saves the result.

The fingerprint uses EXACTLY the same JS payload as tools/fingerprint_dump.py
so the result can be compared directly with:
    - reports/fingerprint/fingerprint_real.json       (real Chrome)
    - reports/fingerprint/fingerprint.json            (unpatched Playwright)

Using:
    compare_fingerprint.py
    browser_score.py

Usage:
    python tools/test_stealth.py
    python tools/test_stealth.py --url https://bromotenggersemeru.id --wait 8000
    python tools/test_stealth.py --channel chrome --no-headless --output reports/fingerprint/patched.json
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright

from tools._shared import (
    BrowserConfig,
    add_browser_args,
    add_output_arg,
    ensure_output_dir,
    launch_browser,
    save_json,
    setup_logging,
)
# Import the SAME JS payload used by tools/fingerprint_dump.py
# This guarantees fingerprint format compatibility with the rest of the pipeline.
from tools.fingerprint_dump import _JS as _FINGERPRINT_JS
from stealth import apply_generated

log = setup_logging("test_stealth")

# Default output path
_DEFAULT_OUTPUT = Path("reports/fingerprint/fingerprint_playwright_patched.json")


# ══════════════════════════════════════════════════════════════════
# COLLECT
# ══════════════════════════════════════════════════════════════════

def collect(page, url: str, wait_ms: int) -> dict:
    """Navigate to URL, wait, then evaluate the fingerprint payload."""
    log.info("Navigate → %s", url)
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)

    actual_wait = max(wait_ms, 5_000)   # always wait at least 5 s
    log.info("Wait %d ms…", actual_wait)
    page.wait_for_timeout(actual_wait)

    log.info("Collect fingerprint")
    return page.evaluate(_FINGERPRINT_JS)


# ══════════════════════════════════════════════════════════════════
# SAVE
# ══════════════════════════════════════════════════════════════════

def save(data: dict, out_path: Path, cfg: BrowserConfig) -> None:
    """Wrap fingerprint in _meta envelope and write to disk."""
    result = {
        "_meta": {
            "tool":         "test_stealth.py",
            "collected_at": datetime.now().isoformat(),
            "url":          cfg.url,
            "channel":      cfg.channel or "chromium (bundled)",
            "headless":     cfg.headless,
            "stealth":      "stealth/generated/patches_init.js",
        },
        "fingerprint": data,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Save fingerprint → %s", out_path)
    save_json(result, out_path)


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Test stealth patches: launch Playwright, apply patches, collect fingerprint.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Steps:
  1. Launch Playwright browser
  2. Apply stealth/generated/patches_init.js via add_init_script()
  3. Navigate to --url
  4. Wait --wait ms (minimum 5000 ms)
  5. Evaluate fingerprint JS payload (same as tools/fingerprint_dump.py)
  6. Save result to --output

Default output: {_DEFAULT_OUTPUT}

Examples:
  python tools/test_stealth.py
  python tools/test_stealth.py --url https://bromotenggersemeru.id --wait 8000
  python tools/test_stealth.py --channel chrome --no-headless
  python tools/test_stealth.py --output reports/fingerprint/patched_v2.json
""",
    )
    add_browser_args(p)
    add_output_arg(p, default="")
    return p


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def main() -> int:
    args     = build_parser().parse_args()
    headless = not args.no_headless
    cfg      = BrowserConfig(
        channel  = args.channel,
        headless = headless,
        profile  = args.profile,
        url      = args.url,
        wait_ms  = args.wait,
    )
    out_path = Path(args.output) if args.output else _DEFAULT_OUTPUT

    log.info("Channel  : %s", cfg.channel or "chromium (bundled)")
    log.info("Headless : %s", cfg.headless)
    log.info("URL      : %s", cfg.url)
    log.info("Output   : %s", out_path)

    with sync_playwright() as pw:
        log.info("Launch browser")
        handle, page, _ = launch_browser(pw, cfg)
        try:
            log.info("Apply generated stealth patches")
            apply_generated(page)

            data = collect(page, cfg.url, cfg.wait_ms)
        finally:
            handle.close()

    save(data, out_path, cfg)
    log.info("Done → %s", out_path)
    log.info("")
    log.info("Next steps:")
    log.info("  compare_fingerprint.py --ref reports/fingerprint/fingerprint_real.json")
    log.info("                         --test %s", out_path)
    log.info("  browser_score.py       --ref reports/fingerprint/fingerprint_real.json")
    log.info("                         --test %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
