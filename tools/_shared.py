"""
tools/_shared.py — Shared utilities for the Browser Analysis Framework.

All tools import from here to avoid code duplication.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# ── Output directory (all tools write here by default) ────────────
TOOLS_DIR  = Path(__file__).parent
OUTPUT_DIR = TOOLS_DIR / "output"


# ══════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════

def setup_logging(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a logger with a consistent format."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(name)s] %(levelname)s  %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


# ══════════════════════════════════════════════════════════════════
# FILE I/O
# ══════════════════════════════════════════════════════════════════

def ensure_output_dir(path: Path | None = None) -> Path:
    """Create output directory if it does not exist. Returns the path."""
    p = path or OUTPUT_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_json(data: Any, path: Path, indent: int = 4) -> None:
    """Serialize data to JSON and write to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=indent, ensure_ascii=False, default=str), encoding="utf-8")


def save_text(text: str, path: Path) -> None:
    """Write a text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_json(path: Path) -> Any:
    """Load and parse a JSON file. Raises SystemExit on error."""
    if not path.exists():
        print(f"[ERROR] File not found: {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def timestamped(stem: str, suffix: str) -> str:
    """Return a filename like 'stem_20260713_040500.suffix'."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stem}_{ts}.{suffix}"


# ══════════════════════════════════════════════════════════════════
# BROWSER LAUNCH
# ══════════════════════════════════════════════════════════════════

@dataclass
class BrowserConfig:
    channel:   str   = ""               # "chrome", "msedge", or "" for bundled Chromium
    headless:  bool  = True
    profile:   str   = ""               # path to persistent profile directory
    url:       str   = "about:blank"
    wait_ms:   int   = 3000
    timeout:   int   = 60_000
    args:      list[str] = field(default_factory=lambda: [
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ])


def launch_browser(pw, cfg: BrowserConfig):
    """
    Launch browser with Chrome-first strategy.

    Returns:
        (handle, page, is_persistent)
        - handle   : BrowserContext (persistent) or Browser (ephemeral)
        - page     : Page
        - is_persistent : bool
    """
    kwargs: dict = dict(headless=cfg.headless, args=cfg.args)
    if cfg.channel:
        kwargs["channel"] = cfg.channel

    if cfg.profile:
        Path(cfg.profile).mkdir(parents=True, exist_ok=True)
        ctx  = pw.chromium.launch_persistent_context(str(cfg.profile), **kwargs)
        page = ctx.new_page()
        return ctx, page, True

    browser = pw.chromium.launch(**kwargs)
    ctx     = browser.new_context()
    page    = ctx.new_page()
    return browser, page, False


def navigate(page, url: str, timeout: int = 60_000, wait_ms: int = 0) -> None:
    """Navigate to URL and optionally wait."""
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)


# ══════════════════════════════════════════════════════════════════
# SAFE JS EVALUATION
# ══════════════════════════════════════════════════════════════════

def eval_safe(page, js: str, fallback: Any = None) -> Any:
    """Evaluate JS in page; return fallback on any error."""
    try:
        return page.evaluate(js)
    except Exception:
        return fallback


# ══════════════════════════════════════════════════════════════════
# COMMON ARGPARSE ARGUMENTS
# ══════════════════════════════════════════════════════════════════

def add_browser_args(parser) -> None:
    """Add standard browser launch arguments to an ArgumentParser."""
    g = parser.add_argument_group("Browser")
    g.add_argument("--channel",     default="",          help="'chrome', 'msedge', or empty for bundled Chromium")
    g.add_argument("--no-headless", action="store_true", help="Run in visible mode")
    g.add_argument("--profile",     default="",          help="Persistent browser profile directory")
    g.add_argument("--url",         default="about:blank", help="URL to open")
    g.add_argument("--wait",        type=int, default=3000, help="ms to wait after page load")


def add_output_arg(parser, default: str = "") -> None:
    """Add --output argument."""
    parser.add_argument("--output", "-o", default=default, help="Output file path")


# ══════════════════════════════════════════════════════════════════
# CLOUDFLARE DETECTION HELPERS
# ══════════════════════════════════════════════════════════════════

CF_COOKIES   = {"cf_clearance", "__cf_bm", "cf_chl_2", "cf_chl_prog", "cf_chl_rc_ni"}
CF_CHALLENGE_TITLES = ("Just a moment", "Tunggu sebentar", "Verify you are human",
                        "Checking your browser", "Please wait", "Security Check")


def is_cf_challenge(page) -> bool:
    """Return True if the current page shows a Cloudflare challenge."""
    try:
        title = page.title()
        url   = page.url
        html  = page.content()
        return (
            "__cf_chl" in url
            or any(t in title for t in CF_CHALLENGE_TITLES)
            or "challenges.cloudflare.com" in html
        )
    except Exception:
        return False


def get_cf_cookies(context) -> dict[str, str]:
    """Return dict of CF-related cookies present in context."""
    try:
        return {c["name"]: c["value"] for c in context.cookies() if c["name"] in CF_COOKIES}
    except Exception:
        return {}
