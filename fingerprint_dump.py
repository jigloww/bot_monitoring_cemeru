"""
fingerprint_dump.py — Real Chrome fingerprint collector via Chrome DevTools Protocol (CDP).

STEP 1 of the fingerprint analysis pipeline.

This tool ATTACHES to an already-running Chrome browser using CDP.
It does NOT launch a new browser.

Usage:
    # 1. Launch Chrome manually first:
    #
    #   Windows:
    #     chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\tmp\\chrome_debug
    #
    #   Linux:
    #     google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome_debug
    #
    # 2. Then run this tool:
    python fingerprint_dump.py
    python fingerprint_dump.py --cdp http://127.0.0.1:9222
    python fingerprint_dump.py --cdp http://127.0.0.1:9222 --output reports/fingerprint/custom.json
    python fingerprint_dump.py --url https://bromotenggersemeru.id --wait 8000

Pipeline:
    STEP 1  fingerprint_dump.py (this file)   → reports/fingerprint/fingerprint_real.json
    STEP 2  tools/fingerprint_dump.py         → reports/fingerprint/fingerprint.json
    STEP 3  tools/compare_fingerprint.py
    STEP 4  tools/browser_score.py
    STEP 5  tools/patch_generator.py
    STEP 6  tools/patch_validator.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

# ══════════════════════════════════════════════════════════════════
# DEFAULTS
# ══════════════════════════════════════════════════════════════════

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_OUTPUT  = Path("reports/fingerprint/fingerprint_real.json")

# ══════════════════════════════════════════════════════════════════
# JAVASCRIPT PAYLOAD
# Identical JS payload to tools/fingerprint_dump.py for pipeline
# compatibility. Single async IIFE — Playwright awaits the Promise.
# ══════════════════════════════════════════════════════════════════

_JS = r"""
async () => {
    const S = (fn, fb=null) => { try { return fn(); } catch(e) { return fb; } };
    const A = async (fn, fb=null) => { try { return await fn(); } catch(e) { return fb; } };
    const d = v => (typeof v !== 'undefined' ? v : null);

    // ── Navigator core ────────────────────────────────────────────
    const nav = S(() => ({
        userAgent: navigator.userAgent, appVersion: navigator.appVersion,
        appName: navigator.appName, appCodeName: navigator.appCodeName,
        platform: navigator.platform, vendor: navigator.vendor,
        vendorSub: navigator.vendorSub, product: navigator.product,
        productSub: navigator.productSub, oscpu: d(navigator.oscpu),
        webdriver: navigator.webdriver, language: navigator.language,
        languages: Array.from(navigator.languages),
        hardwareConcurrency: navigator.hardwareConcurrency,
        deviceMemory: d(navigator.deviceMemory),
        maxTouchPoints: navigator.maxTouchPoints,
        cookieEnabled: navigator.cookieEnabled,
        pdfViewerEnabled: d(navigator.pdfViewerEnabled),
        doNotTrack: navigator.doNotTrack, onLine: navigator.onLine,
        javaEnabled: S(() => navigator.javaEnabled(), null),
    }));

    // navigator.userAgentData (User-Agent Client Hints)
    const uad = await A(async () => {
        const u = navigator.userAgentData; if (!u) return null;
        const hi = await u.getHighEntropyValues([
            'architecture','bitness','brands','fullVersionList',
            'mobile','model','platform','platformVersion','uaFullVersion']);
        return { brands: u.brands, mobile: u.mobile, platform: u.platform, high_entropy: hi };
    });

    // navigator sub-objects
    const nav_connection = S(() => {
        const c = navigator.connection||navigator.mozConnection||navigator.webkitConnection;
        return c ? { effectiveType:c.effectiveType, downlink:c.downlink, rtt:c.rtt, saveData:c.saveData, type:d(c.type) } : null;
    });
    const nav_keys = S(() => Object.keys(navigator));
    const nav_own  = S(() => Object.getOwnPropertyNames(Object.getPrototypeOf(navigator)));

    // ── Plugins & MimeTypes ───────────────────────────────────────
    const plugins = S(() => {
        const pl = [], mt = [];
        for (let i=0;i<navigator.plugins.length;i++){
            const p=navigator.plugins[i], ms=[];
            for(let j=0;j<p.length;j++) ms.push({type:p[j].type,suffixes:p[j].suffixes,description:p[j].description});
            pl.push({name:p.name,filename:p.filename,description:p.description,mimes:ms});
        }
        for(let i=0;i<navigator.mimeTypes.length;i++){
            const m=navigator.mimeTypes[i];
            mt.push({type:m.type,suffixes:m.suffixes,description:m.description});
        }
        return {plugin_count:pl.length,plugins:pl,mime_count:mt.length,mime_types:mt};
    });

    // ── Screen / Window ───────────────────────────────────────────
    const scr = S(() => ({
        width:screen.width, height:screen.height,
        availWidth:screen.availWidth, availHeight:screen.availHeight,
        colorDepth:screen.colorDepth, pixelDepth:screen.pixelDepth,
        orientation: S(()=>({type:screen.orientation.type, angle:screen.orientation.angle})),
    }));
    const win = S(() => ({
        innerWidth:window.innerWidth, innerHeight:window.innerHeight,
        outerWidth:window.outerWidth, outerHeight:window.outerHeight,
        devicePixelRatio:window.devicePixelRatio,
        screenX:window.screenX, screenY:window.screenY,
        scrollX:window.scrollX, scrollY:window.scrollY,
    }));

    // ── Intl / Timezone / Locale ──────────────────────────────────
    const tz = S(() => {
        const o=Intl.DateTimeFormat().resolvedOptions();
        return { timeZone:o.timeZone, locale:o.locale, calendar:o.calendar,
                 numberingSystem:o.numberingSystem, hourCycle:o.hourCycle,
                 offset_minutes:-(new Date().getTimezoneOffset()) };
    });
    const intl = S(() => ({
        collator: S(()=>new Intl.Collator().resolvedOptions()),
        numberFormat: S(()=>new Intl.NumberFormat().resolvedOptions()),
        listFormat:   S(()=>new Intl.ListFormat().resolvedOptions()),
    }));

    // ── Permissions ───────────────────────────────────────────────
    const perms = {};
    for (const n of ['notifications','clipboard-read','clipboard-write','camera','microphone','geolocation','speaker-selection']) {
        perms[n] = await A(async () => (await navigator.permissions.query({name:n})).state);
    }

    // ── Storage ───────────────────────────────────────────────────
    const storage = S(() => ({
        localStorage_length:   localStorage.length,
        sessionStorage_length: sessionStorage.length,
        indexedDB_available:   typeof indexedDB !== 'undefined',
        caches_available:      typeof caches    !== 'undefined',
        cookieStore_available: typeof cookieStore !== 'undefined',
    }));
    const idb = await A(async () => {
        const dbs = await indexedDB.databases();
        return { count: dbs.length, databases: dbs.map(d=>d.name) };
    });

    // ── Document / History ────────────────────────────────────────
    const doc = S(() => {
        const raw=document.cookie;
        const names=raw?raw.split(';').map(c=>c.trim().split('=')[0].trim()).filter(Boolean):[];
        return { cookie_count:names.length, cookie_names:names, readyState:document.readyState,
                 referrer:document.referrer, visibilityState:document.visibilityState,
                 characterSet:document.characterSet, compatMode:document.compatMode,
                 domain:document.domain, title:document.title };
    });
    const history_d = S(()=>({ length:history.length }));

    // ── Performance ───────────────────────────────────────────────
    const perf = S(() => {
        const mem = S(()=>{ const m=performance.memory; return m?{jsHeapSizeLimit:m.jsHeapSizeLimit,totalJSHeapSize:m.totalJSHeapSize,usedJSHeapSize:m.usedJSHeapSize}:null; });
        const ne  = performance.getEntriesByType('navigation');
        const nt  = ne.length?{type:ne[0].type,duration:ne[0].duration,domContentLoadedEventEnd:ne[0].domContentLoadedEventEnd,loadEventEnd:ne[0].loadEventEnd}:null;
        return { timeOrigin:performance.timeOrigin, now:performance.now(), memory:mem, navigation_timing:nt,
                 resource_count: performance.getEntriesByType('resource').length };
    });

    // ── WebGL ─────────────────────────────────────────────────────
    const webgl = S(() => {
        const c=document.createElement('canvas');
        const gl=c.getContext('webgl')||c.getContext('experimental-webgl');
        if(!gl) return {supported:false};
        const ext=gl.getExtension('WEBGL_debug_renderer_info');
        const exts=gl.getSupportedExtensions()||[];
        const P=(id)=>{ try{ const v=gl.getParameter(id); return (v instanceof Float32Array||v instanceof Int32Array)?Array.from(v):v; }catch(e){return null;} };
        return {
            supported:true, version:P(gl.VERSION),
            shading_language_version:P(gl.SHADING_LANGUAGE_VERSION),
            vendor:P(gl.VENDOR), renderer:P(gl.RENDERER),
            unmasked_vendor:  ext?P(ext.UNMASKED_VENDOR_WEBGL):null,
            unmasked_renderer:ext?P(ext.UNMASKED_RENDERER_WEBGL):null,
            max_texture_size:P(gl.MAX_TEXTURE_SIZE),
            max_renderbuffer_size:P(gl.MAX_RENDERBUFFER_SIZE),
            max_vertex_attribs:P(gl.MAX_VERTEX_ATTRIBS),
            aliased_line_width_range:P(gl.ALIASED_LINE_WIDTH_RANGE),
            aliased_point_size_range:P(gl.ALIASED_POINT_SIZE_RANGE),
            extension_count:exts.length, extensions:exts,
        };
    });
    const webgl2 = S(() => {
        const c=document.createElement('canvas'),gl=c.getContext('webgl2');
        return gl?{supported:true,version:gl.getParameter(gl.VERSION)}:{supported:false};
    });

    // ── Canvas fingerprint ────────────────────────────────────────
    const canvas = S(() => {
        const c=document.createElement('canvas'); c.width=300; c.height=150;
        const ctx=c.getContext('2d'); if(!ctx) return {supported:false};
        ctx.textBaseline='alphabetic'; ctx.fillStyle='#f60'; ctx.fillRect(125,1,62,20);
        ctx.fillStyle='#069'; ctx.font='11pt no-real,Arial';
        ctx.fillText('Cwm fjordbank glyphs vext quiz, \xe9',2,15);
        ctx.fillStyle='rgba(102,204,0,0.7)'; ctx.font='18pt Arial';
        ctx.fillText('Cwm fjordbank glyphs vext quiz, \xe9',4,45);
        ctx.beginPath(); ctx.arc(50,50,50,0,Math.PI*2,true); ctx.closePath();
        ctx.fillStyle='rgba(255,0,255,0.5)'; ctx.fill();
        const url=c.toDataURL('image/png');
        let hash=0;
        for(let i=0;i<url.length;i++){hash=((hash<<5)-hash)+url.charCodeAt(i);hash|=0;}
        return {supported:true, hash, length:url.length, prefix:url.substring(0,80)};
    });

    // ── Audio fingerprint ─────────────────────────────────────────
    const audio = await A(async () => {
        const ctx=new OfflineAudioContext(1,44100,44100);
        const osc=ctx.createOscillator(), comp=ctx.createDynamicsCompressor();
        osc.type='triangle'; osc.frequency.setValueAtTime(10000,ctx.currentTime);
        comp.threshold.setValueAtTime(-50,ctx.currentTime); comp.knee.setValueAtTime(40,ctx.currentTime);
        comp.ratio.setValueAtTime(12,ctx.currentTime); comp.attack.setValueAtTime(0,ctx.currentTime);
        comp.release.setValueAtTime(0.25,ctx.currentTime);
        osc.connect(comp); comp.connect(ctx.destination); osc.start(0);
        const buf=await ctx.startRendering(), data=buf.getChannelData(0);
        let sum=0; for(let i=0;i<data.length;i++) sum+=Math.abs(data[i]);
        return { sample_sum:sum, samples:Array.from(data.slice(4500,4520)) };
    });

    // ── Fonts (canvas measurement) ────────────────────────────────
    const fonts = S(() => {
        const FONTS=[
            'Arial','Arial Black','Arial Narrow','Calibri','Cambria','Candara',
            'Comic Sans MS','Consolas','Constantia','Corbel','Courier New',
            'Georgia','Helvetica','Impact','Lucida Console','Lucida Sans Unicode',
            'Microsoft Sans Serif','Palatino Linotype','Segoe UI','Symbol',
            'Tahoma','Times New Roman','Trebuchet MS','Verdana','Wingdings',
            'DejaVu Sans','DejaVu Serif','FreeSerif','Liberation Sans','Ubuntu',
            'MS Gothic','MS Mincho','Roboto','Open Sans','Noto Sans','Noto Serif',
        ];
        const c=document.createElement('canvas'), ctx=c.getContext('2d');
        if(!ctx) return null;
        const TEXT='mmmmmmmmmmlli', BASE='monospace';
        ctx.font=`16px ${BASE}`; const bw=ctx.measureText(TEXT).width;
        const detected=[];
        for(const f of FONTS){ ctx.font=`16px '${f}',${BASE}`; if(ctx.measureText(TEXT).width!==bw) detected.push(f); }
        return {count:detected.length, detected};
    });

    // ── CSS features ──────────────────────────────────────────────
    const css = S(() => ({
        supports: {
            grid:S(()=>CSS.supports('display:grid')),
            flex:S(()=>CSS.supports('display:flex')),
            variables:S(()=>CSS.supports('--x:1')),
            'backdrop-filter':S(()=>CSS.supports('backdrop-filter:blur(1px)')),
            'aspect-ratio':S(()=>CSS.supports('aspect-ratio:1')),
            container:S(()=>CSS.supports('container-type:inline-size')),
            'has-selector':S(()=>CSS.supports('selector(:has(a))')),
        },
        touch_support: 'ontouchstart' in window,
        pointer_events: typeof PointerEvent!=='undefined',
        hover_hover: S(()=>matchMedia('(hover:hover)').matches),
        prefers_dark: S(()=>matchMedia('(prefers-color-scheme:dark)').matches),
        reduced_motion: S(()=>matchMedia('(prefers-reduced-motion:reduce)').matches),
        forced_colors: S(()=>matchMedia('(forced-colors:active)').matches),
    }));

    // ── Chrome object ─────────────────────────────────────────────
    const chrome_obj = S(() => {
        if(typeof window.chrome==='undefined') return {present:false};
        const cr=window.chrome;
        return {
            present:true, keys:Object.keys(cr),
            runtime:{present:typeof cr.runtime!=='undefined', id:S(()=>cr.runtime.id,null),
                     has_connect:typeof cr.runtime?.connect==='function',
                     has_send:typeof cr.runtime?.sendMessage==='function'},
            loadTimes:{present:typeof cr.loadTimes==='function',
                       value:S(()=>{const lt=cr.loadTimes();return{requestTime:lt.requestTime,startLoadTime:lt.startLoadTime};},null)},
            csi:{present:typeof cr.csi==='function',
                 value:S(()=>{const c=cr.csi();return{startE:c.startE,onloadT:c.onloadT,pageT:c.pageT};},null)},
            app:{present:typeof cr.app!=='undefined'},
            webstore:{present:typeof cr.webstore!=='undefined'},
        };
    });

    // ── Battery / Speech / RTC / Media ───────────────────────────
    const battery = await A(async () => {
        const b=await navigator.getBattery();
        return {charging:b.charging,level:b.level,chargingTime:b.chargingTime,dischargingTime:b.dischargingTime};
    });
    const speech = S(() => {
        if(typeof speechSynthesis==='undefined') return null;
        const v=speechSynthesis.getVoices();
        return {count:v.length, voices:v.map(x=>({name:x.name,lang:x.lang,local:x.localService}))};
    });
    const rtc = S(() => ({
        RTCPeerConnection:typeof RTCPeerConnection!=='undefined',
        RTCDataChannel:typeof RTCDataChannel!=='undefined',
        RTCSessionDescription:typeof RTCSessionDescription!=='undefined',
    }));
    const media_devs = await A(async () => {
        const ds=await navigator.mediaDevices.enumerateDevices();
        return ds.map(d=>({kind:d.kind,label:d.label,groupId:d.groupId}));
    });
    const media_caps = await A(async () => {
        const r=await navigator.mediaCapabilities.decodingInfo({type:'file',video:{contentType:'video/mp4;codecs=avc1.42E01E',width:1920,height:1080,bitrate:2646242,framerate:30}});
        return {supported:r.supported,smooth:r.smooth,powerEfficient:r.powerEfficient};
    });

    // ── GPU ───────────────────────────────────────────────────────
    const gpu = S(() => ({ available: typeof navigator.gpu !== 'undefined' }));

    // ── Hardware APIs ─────────────────────────────────────────────
    const hw = S(() => ({
        bluetooth:  typeof navigator.bluetooth  !== 'undefined',
        usb:        typeof navigator.usb        !== 'undefined',
        serial:     typeof navigator.serial     !== 'undefined',
        hid:        typeof navigator.hid        !== 'undefined',
        keyboard:   typeof navigator.keyboard   !== 'undefined',
        clipboard:  typeof navigator.clipboard  !== 'undefined',
        gamepad:    S(()=>Array.from(navigator.getGamepads()).filter(Boolean).length, 0),
    }));

    // ── Feature flags ─────────────────────────────────────────────
    const features = S(() => ({
        fetch:typeof fetch!=='undefined',
        Worker:typeof Worker!=='undefined',
        SharedWorker:typeof SharedWorker!=='undefined',
        ServiceWorker:typeof navigator.serviceWorker!=='undefined',
        WebSocket:typeof WebSocket!=='undefined',
        WebAssembly:typeof WebAssembly!=='undefined',
        SharedArrayBuffer:typeof SharedArrayBuffer!=='undefined',
        IntersectionObserver:typeof IntersectionObserver!=='undefined',
        ResizeObserver:typeof ResizeObserver!=='undefined',
        MutationObserver:typeof MutationObserver!=='undefined',
        crypto:typeof crypto!=='undefined',
        crypto_subtle:typeof crypto?.subtle!=='undefined',
        Notification:typeof Notification!=='undefined',
        notification_permission:S(()=>Notification.permission,null),
        BigInt:typeof BigInt!=='undefined',
        Proxy:typeof Proxy!=='undefined',
        AbortController:typeof AbortController!=='undefined',
        structuredClone:typeof structuredClone!=='undefined',
    }));

    // ── window / navigator key inventory ─────────────────────────
    const win_keys  = S(() => Object.keys(window).sort());
    const nav_keys2 = S(() => Object.keys(navigator).sort());
    const nav_own2  = S(() => Object.getOwnPropertyNames(Object.getPrototypeOf(navigator)).sort());

    return {
        navigator: { ...nav, userAgentData:uad, connection:nav_connection,
                     keys:nav_keys, prototype_keys:nav_own },
        plugins, screen:scr, window:win, timezone:tz, intl,
        permissions:perms, storage, indexeddb:idb,
        document:doc, history:history_d, performance:perf,
        webgl, webgl2, canvas, audio, fonts, css,
        chrome:chrome_obj, battery, speech, rtc,
        media_devices:media_devs, media_capabilities:media_caps,
        gpu, hardware_apis:hw, features,
        window_keys:win_keys, navigator_keys:nav_keys2, navigator_own_keys:nav_own2,
    };
}
"""


# ══════════════════════════════════════════════════════════════════
# CDP CONNECT
# ══════════════════════════════════════════════════════════════════

_CDP_ERROR = """\
Cannot connect to Chrome DevTools Protocol.
Please launch Chrome first with:

  Windows:
    chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\tmp\\chrome_debug

  Linux:
    google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome_debug

Then re-run this tool.
"""


def connect_cdp(pw, cdp_url: str):
    """
    Attach to an already-running Chrome via CDP.
    Returns (browser, page).
    Raises SystemExit with a clear message if Chrome is not reachable.
    """
    print(f"[INFO] Connecting to Chrome DevTools at {cdp_url} ...")
    try:
        browser = pw.chromium.connect_over_cdp(cdp_url)
    except Exception as exc:
        print(_CDP_ERROR, file=sys.stderr)
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    contexts = browser.contexts
    if contexts:
        ctx = contexts[0]
        pages = ctx.pages
        page  = pages[0] if pages else ctx.new_page()
        print(f"[INFO] Connected to existing Chrome instance.")
        print(f"[INFO] Using existing Chrome profile.")
    else:
        ctx  = browser.new_context()
        page = ctx.new_page()
        print(f"[INFO] Connected — created new context.")

    return browser, page


# ══════════════════════════════════════════════════════════════════
# COLLECT
# ══════════════════════════════════════════════════════════════════

def collect(page, url: str, wait_ms: int) -> dict:
    """Navigate to URL (if not about:blank), wait, evaluate JS payload."""
    if url and url != "about:blank":
        print(f"[INFO] Navigating to: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    else:
        print(f"[INFO] Using current page: {page.url}")
    if wait_ms > 0:
        print(f"[INFO] Waiting {wait_ms} ms...")
        page.wait_for_timeout(wait_ms)
    print("[INFO] Collecting browser fingerprint...")
    return page.evaluate(_JS)


# ══════════════════════════════════════════════════════════════════
# SAVE
# ══════════════════════════════════════════════════════════════════

def save(data: dict, out_path: Path, cdp_url: str, url: str) -> None:
    """Wrap fingerprint data in _meta envelope and save to JSON."""
    result = {
        "_meta": {
            "tool":         "fingerprint_dump.py (CDP / Real Chrome)",
            "collected_at": datetime.now().isoformat(),
            "cdp_url":      cdp_url,
            "url":          url,
            "channel":      "chrome (real, via CDP)",
            "headless":     False,
        },
        "fingerprint": data,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] Saving fingerprint...")
    out_path.write_text(json.dumps(result, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"[OK]   Fingerprint saved: {out_path}")


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Collect a comprehensive fingerprint from a REAL Chrome browser via CDP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
This tool ATTACHES to a running Chrome instance. It does NOT launch Chrome.

Launch Chrome first:
  Linux  : google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome_debug
  Windows: chrome.exe   --remote-debugging-port=9222 --user-data-dir=C:\\tmp\\chrome_debug

Examples:
  python fingerprint_dump.py
  python fingerprint_dump.py --cdp http://127.0.0.1:9222
  python fingerprint_dump.py --cdp http://127.0.0.1:9222 --output reports/fingerprint/custom.json
  python fingerprint_dump.py --url https://bromotenggersemeru.id --wait 8000

Default output: {DEFAULT_OUTPUT}
""",
    )
    p.add_argument(
        "--cdp", "-c",
        default=DEFAULT_CDP_URL,
        metavar="URL",
        help=f"Chrome DevTools Protocol URL (default: {DEFAULT_CDP_URL})",
    )
    p.add_argument(
        "--output", "-o",
        default="",
        metavar="FILE",
        help=f"Output JSON file path (default: {DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "--url", "-u",
        default="",
        metavar="URL",
        help="Navigate to this URL before collecting fingerprint (optional; uses current page if omitted)",
    )
    p.add_argument(
        "--wait", "-w",
        type=int,
        default=3000,
        metavar="MS",
        help="Milliseconds to wait after navigation before collecting (default: 3000)",
    )
    return p


def main() -> int:
    args     = build_parser().parse_args()
    out_path = Path(args.output) if args.output else DEFAULT_OUTPUT

    print(f"[INFO] CDP URL  : {args.cdp}")
    print(f"[INFO] Output   : {out_path}")
    if args.url:
        print(f"[INFO] Navigate : {args.url}")

    with sync_playwright() as pw:
        browser, page = connect_cdp(pw, args.cdp)
        try:
            data = collect(page, args.url, args.wait)
        finally:
            # disconnect only — do NOT close the real browser
            browser.close()

    save(data, out_path, args.cdp, args.url or page.url if page else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
