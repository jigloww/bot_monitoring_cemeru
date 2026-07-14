"""
tools/turnstile_analyzer.py — Detect and analyze Cloudflare Turnstile widget.

Extracts: sitekey, widget ID, render/execution/retry/appearance mode,
          iframe presence, hidden inputs, response field, callback names.

Usage:
    python tools/turnstile_analyzer.py --url https://bromotenggersemeru.id --output reports/challenge/turnstile.json
    python tools/turnstile_analyzer.py --url https://target.com --channel chrome --no-headless --output turnstile.json
"""
from __future__ import annotations
import argparse, sys, time
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

log = setup_logging("turnstile_analyzer")

_TS_JS = """() => {
    const S = (fn,fb=null)=>{try{return fn();}catch(e){return fb;}};

    // ── Detect Turnstile script ───────────────────────────────
    const scripts = Array.from(document.querySelectorAll('script[src]')).map(s=>s.src);
    const ts_script = scripts.find(s => s.includes('turnstile') || s.includes('challenges.cloudflare.com/turnstile'));

    // ── Detect Turnstile iframe(s) ────────────────────────────
    const iframes = Array.from(document.querySelectorAll('iframe')).map(f => ({
        src:    f.src,
        id:     f.id,
        name:   f.name,
        width:  f.width,
        height: f.height,
        is_turnstile: f.src.includes('challenges.cloudflare.com') || f.src.includes('turnstile'),
    }));

    // ── Detect widget container ───────────────────────────────
    const containers = Array.from(document.querySelectorAll('[class*=cf-turnstile],[id*=turnstile],[data-sitekey]')).map(el=>({
        tag:      el.tagName,
        id:       el.id,
        class:    el.className,
        sitekey:  el.dataset.sitekey  || el.getAttribute('data-sitekey'),
        action:   el.dataset.action   || null,
        theme:    el.dataset.theme    || null,
        size:     el.dataset.size     || null,
        callback: el.dataset.callback || null,
        'expired-callback':  el.dataset['expired-callback']  || null,
        'error-callback':    el.dataset['error-callback']    || null,
        'execution':         el.dataset.execution  || null,
        'retry':             el.dataset.retry      || null,
        'appearance':        el.dataset.appearance || null,
        'response-field':    el.dataset['response-field'] || null,
        'response-field-name': el.dataset['response-field-name'] || null,
    }));

    // ── Hidden inputs that may hold Turnstile response ────────
    const hidden_inputs = Array.from(document.querySelectorAll('input[type=hidden]')).map(i=>({
        name:  i.name,
        id:    i.id,
        value_length: i.value ? i.value.length : 0,
        value_preview: i.value ? i.value.substring(0,40) : '',
    }));

    // ── window.turnstile object ───────────────────────────────
    const ts_obj = S(()=>{
        if(typeof window.turnstile==='undefined') return null;
        return { present: true, keys: Object.keys(window.turnstile) };
    });

    // ── CF challenge-specific globals ─────────────────────────
    const cf_globals = {
        cf_chl_opt:          S(()=>typeof window._cf_chl_opt !== 'undefined' ? JSON.stringify(window._cf_chl_opt) : null),
        cfRLUnblockHandlers: S(()=>typeof window.__cfRLUnblockHandlers !== 'undefined'),
        turnstileWidget:     S(()=>typeof window.turnstile !== 'undefined'),
        botFightMode:        S(()=>typeof window.__CF_FIGHT_MODE !== 'undefined'),
    };

    // ── Challenge form ────────────────────────────────────────
    const form = S(()=>{
        const f = document.querySelector('#challenge-form,form[action*=challenge]');
        if(!f) return null;
        return {
            action: f.action, method: f.method,
            inputs: Array.from(f.querySelectorAll('input')).map(i=>({name:i.name,type:i.type,value_len:i.value?.length}))
        };
    });

    return { ts_script, iframes, containers, hidden_inputs, ts_obj, cf_globals, form,
             page_title: document.title, page_url: location.href };
}"""


def analyze(page, wait_s: int = 5) -> dict:
    """Navigate, wait, and run Turnstile analysis JS."""
    time.sleep(wait_s)  # Let challenge fully render
    result = page.evaluate(_TS_JS)

    # Log key findings
    ts_iframes = [f for f in result.get("iframes", []) if f["is_turnstile"]]
    log.info("Turnstile script  : %s", result.get("ts_script") or "NOT FOUND")
    log.info("Turnstile iframes : %d", len(ts_iframes))
    log.info("Widget containers : %d", len(result.get("containers", [])))
    log.info("Hidden inputs     : %d", len(result.get("hidden_inputs", [])))
    log.info("window.turnstile  : %s", "PRESENT" if result.get("ts_obj") else "absent")

    for c in result.get("containers", []):
        log.info("  Container sitekey=%s  theme=%s  size=%s  execution=%s",
                 c.get("sitekey","?"), c.get("theme","?"), c.get("size","?"), c.get("execution","?"))

    cf = result.get("cf_globals", {})
    log.info("CF globals: cfRLUnblockHandlers=%s  _cf_chl_opt=%s",
             cf.get("cfRLUnblockHandlers"), bool(cf.get("cf_chl_opt")))

    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Detect and analyze Cloudflare Turnstile widget.")
    add_browser_args(p)
    p.add_argument("--analyze-wait", type=int, default=5, help="Seconds to wait before analyzing (default: 5)")
    add_output_arg(p, default="")  # e.g. --output reports/challenge/turnstile.json
    return p


def main() -> int:
    args     = build_parser().parse_args()
    headless = not args.no_headless
    cfg      = BrowserConfig(channel=args.channel, headless=headless, profile=args.profile,
                             url=args.url, wait_ms=args.wait)
    # out_file resolved below after args parsed

    with sync_playwright() as pw:
        handle, page, _ = launch_browser(pw, cfg)
        try:
            page.goto(cfg.url, wait_until="domcontentloaded", timeout=60_000)
            if cfg.wait_ms:
                page.wait_for_timeout(cfg.wait_ms)
            result = analyze(page, args.analyze_wait)
        finally:
            handle.close()

    out      = Path(args.output) if args.output else ensure_output_dir() / "turnstile.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    path = out
    save_json(result, path)
    log.info("Saved → %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
