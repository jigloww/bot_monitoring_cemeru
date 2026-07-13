"""
tools/challenge_timeline.py — Poll page state every 500 ms during Cloudflare challenge.

Captures: title, URL, readyState, cookies, CF status, DOM size, body snippet,
          Turnstile presence, challenge resolution status.

Output: tools/output/timeline.json + timeline.csv

Usage:
    python tools/challenge_timeline.py --url https://bromotenggersemeru.id --duration 60
    python tools/challenge_timeline.py --url https://target.com --channel chrome --no-headless
"""
from __future__ import annotations
import argparse, csv, sys, time
from dataclasses import dataclass, field, asdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from playwright.sync_api import sync_playwright
from tools._shared import (BrowserConfig, CF_CHALLENGE_TITLES, CF_COOKIES,
                            OUTPUT_DIR, ensure_output_dir, get_cf_cookies,
                            launch_browser, navigate, save_json, setup_logging, add_browser_args)

log = setup_logging("challenge_timeline")

# ══════════════════════════════════════════════════════════════════
# DATA STRUCTURE
# ══════════════════════════════════════════════════════════════════

@dataclass
class TimelineFrame:
    elapsed_ms:       int
    timestamp:        float
    title:            str
    url:              str
    ready_state:      str
    cookie_names:     list[str]
    cf_clearance:     bool
    cf_bm:            bool
    cf_challenge:     bool
    turnstile_iframe: bool
    dom_node_count:   int
    body_text_snippet: str
    visible_inputs:   int
    hidden_inputs:    int
    challenge_solved: bool


# ══════════════════════════════════════════════════════════════════
# COLLECT ONE FRAME
# ══════════════════════════════════════════════════════════════════

_STATE_JS = """() => {
    const S = (fn,fb=null)=>{try{return fn();}catch(e){return fb;}};
    const title      = S(()=>document.title,'');
    const url        = location.href;
    const readyState = document.readyState;
    const nodeCount  = document.querySelectorAll('*').length;
    const bodySnip   = S(()=>document.body.innerText.substring(0,200),'');
    const visInputs  = document.querySelectorAll('input:not([type=hidden])').length;
    const hidInputs  = document.querySelectorAll('input[type=hidden]').length;
    const cfChallenge = (
        url.includes('__cf_chl') ||
        ['Just a moment','Verify you are human','Tunggu sebentar'].some(t=>title.includes(t)) ||
        document.documentElement.innerHTML.includes('challenges.cloudflare.com')
    );
    const tsIframe = !!document.querySelector(
        'iframe[src*="challenges.cloudflare.com"],iframe[src*="cdn-cgi/challenge"]');
    return {title,url,readyState,nodeCount,bodySnip,visInputs,hidInputs,cfChallenge,tsIframe};
}"""


def collect_frame(page, context, elapsed_ms: int) -> TimelineFrame:
    try:
        js = page.evaluate(_STATE_JS)
    except Exception as e:
        log.warning("JS eval failed at %dms: %s", elapsed_ms, e)
        js = {"title":"?","url":"?","readyState":"?","nodeCount":0,
              "bodySnip":"","visInputs":0,"hidInputs":0,"cfChallenge":False,"tsIframe":False}

    cf_cooks = get_cf_cookies(context)
    cookie_names = list(cf_cooks.keys())
    try:
        all_cookies = context.cookies()
        cookie_names = [c["name"] for c in all_cookies]
    except Exception:
        pass

    solved = not js["cfChallenge"] and "cf_clearance" in (c["name"] for c in (context.cookies() if context else []))

    return TimelineFrame(
        elapsed_ms        = elapsed_ms,
        timestamp         = time.time(),
        title             = js["title"],
        url               = js["url"],
        ready_state       = js["readyState"],
        cookie_names      = cookie_names,
        cf_clearance      = "cf_clearance" in cookie_names,
        cf_bm             = "__cf_bm" in cookie_names,
        cf_challenge      = js["cfChallenge"],
        turnstile_iframe  = js["tsIframe"],
        dom_node_count    = js["nodeCount"],
        body_text_snippet = js["bodySnip"],
        visible_inputs    = js["visInputs"],
        hidden_inputs     = js["hidInputs"],
        challenge_solved  = solved,
    )


# ══════════════════════════════════════════════════════════════════
# POLL LOOP
# ══════════════════════════════════════════════════════════════════

def poll_timeline(page, context, duration_s: int, interval_ms: int = 500) -> list[TimelineFrame]:
    """Poll page state every interval_ms until duration_s seconds elapsed or challenge solved."""
    frames: list[TimelineFrame] = []
    t_start = time.monotonic()
    log.info("Polling every %dms for %ds…", interval_ms, duration_s)

    while True:
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        frame = collect_frame(page, context, elapsed_ms)
        frames.append(frame)

        status = "SOLVED" if frame.challenge_solved else ("CF" if frame.cf_challenge else "OK")
        log.info("[%5ds] %-8s  title=%-30s  cookies=%d  nodes=%d",
                 elapsed_ms // 1000, status, frame.title[:30], len(frame.cookie_names), frame.dom_node_count)

        if frame.challenge_solved:
            log.info("Challenge SOLVED at %dms!", elapsed_ms)
            break

        if elapsed_ms >= duration_s * 1000:
            log.warning("Duration %ds reached — challenge NOT solved.", duration_s)
            break

        time.sleep(interval_ms / 1000)

    return frames


# ══════════════════════════════════════════════════════════════════
# EXPORT
# ══════════════════════════════════════════════════════════════════

def save_csv(frames: list[TimelineFrame], path: Path) -> None:
    if not frames:
        return
    fieldnames = list(asdict(frames[0]).keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for frame in frames:
            d = asdict(frame)
            d["cookie_names"] = "|".join(d["cookie_names"])
            writer.writerow(d)


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Poll challenge page state every 500ms and record timeline.")
    add_browser_args(p)
    p.add_argument("--duration", type=int, default=60, help="Max monitoring duration in seconds (default: 60)")
    p.add_argument("--interval", type=int, default=500, help="Poll interval in ms (default: 500)")
    p.add_argument("--out-dir",  default="", help="Output directory")
    return p


def main() -> int:
    import dataclasses
    args     = build_parser().parse_args()
    headless = not args.no_headless
    cfg      = BrowserConfig(channel=args.channel, headless=headless, profile=args.profile,
                             url=args.url, wait_ms=0)
    out      = Path(args.out_dir) if args.out_dir else ensure_output_dir()

    log.info("Target: %s  Duration: %ds", cfg.url, args.duration)

    with sync_playwright() as pw:
        handle, page, is_persistent = launch_browser(pw, cfg)
        # Get context ref for cookie access
        context = handle if is_persistent else page.context
        try:
            log.info("Navigating (domcontentloaded)…")
            page.goto(cfg.url, wait_until="domcontentloaded", timeout=60_000)
            frames = poll_timeline(page, context, args.duration, args.interval)
        finally:
            handle.close()

    # Save JSON
    json_path = out / "timeline.json"
    save_json([dataclasses.asdict(f) for f in frames], json_path)
    log.info("Saved JSON → %s  (%d frames)", json_path, len(frames))

    # Save CSV
    csv_path = out / "timeline.csv"
    save_csv(frames, csv_path)
    log.info("Saved CSV  → %s", csv_path)

    # Summary
    solved_frames = [f for f in frames if f.challenge_solved]
    cf_frames     = [f for f in frames if f.cf_challenge]
    log.info("CF challenge frames : %d / %d", len(cf_frames), len(frames))
    log.info("Solved              : %s", "YES" if solved_frames else "NO")
    if solved_frames:
        log.info("Solve time          : %dms", solved_frames[0].elapsed_ms)
    return 0


if __name__ == "__main__":
    sys.exit(main())
