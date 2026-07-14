"""
tools/cookie_timeline.py — Monitor cookies continuously, detect CF cookie lifecycle.

Tracks cf_clearance, __cf_bm, cf_chl_* — creation, deletion, expiration.

Usage:
    python tools/cookie_timeline.py --url https://bromotenggersemeru.id --output reports/cookies/cookies_timeline.json
    python tools/cookie_timeline.py --url https://target.com --duration 120 --output timeline.json
"""
from __future__ import annotations
import argparse, sys, time
from dataclasses import dataclass
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from playwright.sync_api import sync_playwright
from tools._shared import (
    BrowserConfig,
    OUTPUT_DIR,
    ensure_output_dir,
    launch_browser,
    navigate,
    save_json,
    setup_logging,
    add_browser_args,
    add_output_arg
)

log = setup_logging("cookie_timeline")

CF_PREFIXES = ("cf_", "__cf", "cf-")

@dataclass
class CookieEvent:
    elapsed_ms:  int
    timestamp:   float
    event:       str        # "added" | "removed" | "changed" | "snapshot"
    name:        str
    value:       str
    domain:      str
    expires:     float | None
    is_cf:       bool


def is_cf_cookie(name: str) -> bool:
    return any(name.startswith(p) for p in CF_PREFIXES) or name in CF_COOKIES


def monitor_cookies(page, context, duration_s: int, interval_ms: int = 1000) -> list[CookieEvent]:
    events: list[CookieEvent] = []
    t_start = time.monotonic()
    prev: dict[str, dict] = {}

    log.info("Monitoring cookies for %ds…", duration_s)

    while True:
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        ts = time.time()

        try:
            current_list = context.cookies()
            current = {c["name"]: c for c in current_list}
        except Exception as e:
            log.warning("Cookie fetch failed: %s", e)
            current = {}

        # Detect new / changed
        for name, c in current.items():
            cf = is_cf_cookie(name)
            if name not in prev:
                evt = CookieEvent(elapsed_ms=elapsed_ms, timestamp=ts, event="added",
                                  name=name, value=c.get("value",""), domain=c.get("domain",""),
                                  expires=c.get("expires"), is_cf=cf)
                events.append(evt)
                if cf:
                    log.info("[%5dms] ★ CF COOKIE ADDED   : %s", elapsed_ms, name)
                else:
                    log.debug("[%5dms] + cookie added      : %s", elapsed_ms, name)
            elif c.get("value") != prev[name].get("value"):
                evt = CookieEvent(elapsed_ms=elapsed_ms, timestamp=ts, event="changed",
                                  name=name, value=c.get("value",""), domain=c.get("domain",""),
                                  expires=c.get("expires"), is_cf=cf)
                events.append(evt)
                if cf:
                    log.info("[%5dms] ★ CF COOKIE CHANGED : %s", elapsed_ms, name)

        # Detect removed
        for name in prev:
            if name not in current:
                cf = is_cf_cookie(name)
                evt = CookieEvent(elapsed_ms=elapsed_ms, timestamp=ts, event="removed",
                                  name=name, value="", domain="", expires=None, is_cf=cf)
                events.append(evt)
                if cf:
                    log.warning("[%5dms] ✗ CF COOKIE REMOVED : %s", elapsed_ms, name)

        # Snapshot CF cookies
        cf_present = {n: c for n, c in current.items() if is_cf_cookie(n)}
        if cf_present:
            log.info("[%5dms] CF cookies present: %s", elapsed_ms, list(cf_present.keys()))

        prev = current

        if elapsed_ms >= duration_s * 1000:
            break
        time.sleep(interval_ms / 1000)

    return events


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Monitor cookie lifecycle during Cloudflare challenge.")
    add_browser_args(p)
    p.add_argument("--duration", type=int, default=60, help="Monitoring duration in seconds")
    p.add_argument("--interval", type=int, default=1000, help="Poll interval in ms (default: 1000)")
    add_output_arg(p, default="")  # e.g. --output reports/cookies/cookies_timeline.json
    return p


def main() -> int:
    import dataclasses
    args     = build_parser().parse_args()
    headless = not args.no_headless
    cfg      = BrowserConfig(channel=args.channel, headless=headless, profile=args.profile, url=args.url, wait_ms=0)
    out_file = Path(args.output) if args.output else ensure_output_dir() / "cookies_timeline.json"

    with sync_playwright() as pw:
        handle, page, is_persistent = launch_browser(pw, cfg)
        context = handle if is_persistent else page.context
        try:
            page.goto(cfg.url, wait_until="domcontentloaded", timeout=60_000)
            events = monitor_cookies(page, context, args.duration, args.interval)
        finally:
            handle.close()

    path = out_file
    path.parent.mkdir(parents=True, exist_ok=True)
    save_json([dataclasses.asdict(e) for e in events], path)
    log.info("Saved → %s  (%d events)", path, len(events))

    cf_events = [e for e in events if e.is_cf]
    clearance  = any(e.name == "cf_clearance" and e.event == "added" for e in events)
    log.info("CF cookie events  : %d", len(cf_events))
    log.info("cf_clearance      : %s", "ACQUIRED ✓" if clearance else "NOT acquired ✗")
    return 0


if __name__ == "__main__":
    sys.exit(main())
