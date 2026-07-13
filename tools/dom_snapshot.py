"""
tools/dom_snapshot.py — Save HTML, screenshot, DOM tree, scripts, iframes every N seconds.

Usage:
    python tools/dom_snapshot.py --url https://bromotenggersemeru.id --interval 2 --count 5
"""
from __future__ import annotations
import argparse, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from playwright.sync_api import sync_playwright
from tools._shared import (BrowserConfig, ensure_output_dir, launch_browser,
                            save_json, save_text, setup_logging, add_browser_args)

log = setup_logging("dom_snapshot")

_DOM_JS = """() => {
    const S=(fn,fb=null)=>{try{return fn();}catch(e){return fb;}};
    const scripts = Array.from(document.querySelectorAll('script')).map(s=>({
        src:s.src||null, type:s.type||null,
        inline_len:s.src?0:s.textContent.length,
        inline_snippet:s.src?null:s.textContent.substring(0,200),
    }));
    const styles = Array.from(document.querySelectorAll('link[rel=stylesheet],style')).map(s=>({
        href: s.href||null, inline_len: s.href?0:s.textContent.length,
    }));
    const iframes = Array.from(document.querySelectorAll('iframe')).map(f=>({
        src:f.src, id:f.id, name:f.name, sandbox:f.sandbox.value,
        is_cf: f.src.includes('challenges.cloudflare.com')||f.src.includes('turnstile'),
    }));

    // Visible text (rough)
    const visible_text = S(()=>document.body.innerText.substring(0,1000),'');
    // Hidden elements count
    const hidden_count = document.querySelectorAll('[style*="display:none"],[style*="display: none"],[hidden]').length;
    // Shadow DOM roots
    const shadow_roots = Array.from(document.querySelectorAll('*')).filter(el=>el.shadowRoot).length;

    return {
        title:           document.title,
        url:             location.href,
        readyState:      document.readyState,
        node_count:      document.querySelectorAll('*').length,
        script_count:    scripts.length,
        style_count:     styles.length,
        iframe_count:    iframes.length,
        hidden_count,
        shadow_roots,
        visible_text,
        scripts,
        styles,
        iframes,
    };
}"""


def take_snapshot(page, snap_dir: Path, index: int) -> dict:
    """Take one snapshot: HTML, PNG screenshot, DOM JSON."""
    ts = int(time.time())
    prefix = f"snapshot_{index:03d}_{ts}"

    # DOM info
    try:
        dom_info = page.evaluate(_DOM_JS)
    except Exception as e:
        dom_info = {"error": str(e)}

    # HTML
    try:
        html = page.content()
        save_text(html, snap_dir / f"{prefix}.html")
    except Exception as e:
        log.warning("HTML save failed: %s", e)

    # Screenshot
    try:
        page.screenshot(path=str(snap_dir / f"{prefix}.png"), full_page=True)
    except Exception as e:
        log.warning("Screenshot failed: %s", e)

    log.info("[snap %03d] nodes=%d  scripts=%d  iframes=%d  title=%s",
             index,
             dom_info.get("node_count", 0),
             dom_info.get("script_count", 0),
             dom_info.get("iframe_count", 0),
             dom_info.get("title","?")[:40])

    return {"index": index, "prefix": prefix, **dom_info}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Save DOM snapshots (HTML + screenshot) every N seconds.")
    add_browser_args(p)
    p.add_argument("--interval", type=float, default=2.0, help="Seconds between snapshots (default: 2)")
    p.add_argument("--count",    type=int,   default=5,   help="Number of snapshots to take (default: 5)")
    p.add_argument("--out-dir",  default="")
    return p


def main() -> int:
    args     = build_parser().parse_args()
    headless = not args.no_headless
    cfg      = BrowserConfig(channel=args.channel, headless=headless, profile=args.profile,
                             url=args.url, wait_ms=args.wait)
    out      = Path(args.out_dir) if args.out_dir else ensure_output_dir()
    snap_dir = out / "dom_snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)

    log.info("URL: %s  Interval: %ss  Count: %d", cfg.url, args.interval, args.count)

    snapshots: list[dict] = []
    with sync_playwright() as pw:
        handle, page, _ = launch_browser(pw, cfg)
        try:
            page.goto(cfg.url, wait_until="domcontentloaded", timeout=60_000)
            if cfg.wait_ms:
                page.wait_for_timeout(cfg.wait_ms)

            for i in range(args.count):
                snap = take_snapshot(page, snap_dir, i)
                snapshots.append(snap)
                if i < args.count - 1:
                    time.sleep(args.interval)
        finally:
            handle.close()

    manifest_path = out / "dom_snapshots_manifest.json"
    save_json(snapshots, manifest_path)
    log.info("Manifest saved → %s  (%d snapshots)", manifest_path, len(snapshots))
    log.info("Files saved in → %s", snap_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
