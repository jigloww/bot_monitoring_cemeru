"""
fingerprint_dump.py — Production-grade browser fingerprint collector.

Usage:
    python fingerprint_dump.py --channel chrome --no-headless --output fingerprint_real.json
    python fingerprint_dump.py --output fingerprint_playwright.json
    python fingerprint_dump.py --url https://bromotenggersemeru.id --wait 8000 --output fp_cf.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

# ══════════════════════════════════════════════════════════════════
# JAVASCRIPT PAYLOAD
# Runs inside the browser via page.evaluate().
# Single async IIFE — Playwright resolves the returned Promise.
# ══════════════════════════════════════════════════════════════════

_JS = r"""
async () => {
    // ── helpers ──────────────────────────────────────────────────
    const S = (fn, fb = null) => { try { return fn();       } catch(e) { return fb; } };
    const A = async (fn, fb = null) => { try { return await fn(); } catch(e) { return fb; } };
    const def = v => (typeof v !== 'undefined' ? v : null);

    // ── 1. NAVIGATOR ─────────────────────────────────────────────
    const nav = S(() => {
        const n = navigator;
        return {
            userAgent:           n.userAgent,
            appVersion:          n.appVersion,
            appName:             n.appName,
            appCodeName:         n.appCodeName,
            platform:            n.platform,
            vendor:              n.vendor,
            vendorSub:           n.vendorSub,
            product:             n.product,
            productSub:          n.productSub,
            oscpu:               def(n.oscpu),
            webdriver:           n.webdriver,
            language:            n.language,
            languages:           Array.from(n.languages),
            hardwareConcurrency: n.hardwareConcurrency,
            deviceMemory:        def(n.deviceMemory),
            maxTouchPoints:      n.maxTouchPoints,
            cookieEnabled:       n.cookieEnabled,
            pdfViewerEnabled:    def(n.pdfViewerEnabled),
            doNotTrack:          n.doNotTrack,
            onLine:              n.onLine,
        };
    });

    // navigator.userAgentData (User-Agent Client Hints)
    const uad = await A(async () => {
        const ua = navigator.userAgentData;
        if (!ua) return null;
        const hi = await ua.getHighEntropyValues([
            'architecture','bitness','brands','fullVersionList',
            'mobile','model','platform','platformVersion','uaFullVersion',
        ]);
        return { brands: ua.brands, mobile: ua.mobile, platform: ua.platform, high_entropy: hi };
    });

    // navigator.connection
    const connection = S(() => {
        const c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
        if (!c) return null;
        return { effectiveType: c.effectiveType, downlink: c.downlink, rtt: c.rtt, saveData: c.saveData, type: def(c.type) };
    });

    // ── 2. PLUGINS & MIME TYPES ──────────────────────────────────
    const plugins = S(() => {
        const plist = [];
        for (let i = 0; i < navigator.plugins.length; i++) {
            const p  = navigator.plugins[i];
            const ms = [];
            for (let j = 0; j < p.length; j++) {
                ms.push({ type: p[j].type, suffixes: p[j].suffixes, description: p[j].description });
            }
            plist.push({ name: p.name, filename: p.filename, description: p.description, mimes: ms });
        }
        const mlist = [];
        for (let i = 0; i < navigator.mimeTypes.length; i++) {
            const m = navigator.mimeTypes[i];
            mlist.push({ type: m.type, suffixes: m.suffixes, description: m.description });
        }
        return { plugin_count: plist.length, plugins: plist, mime_count: mlist.length, mime_types: mlist };
    });

    // ── 3. SCREEN ────────────────────────────────────────────────
    const scr = S(() => ({
        width:       screen.width,
        height:      screen.height,
        availWidth:  screen.availWidth,
        availHeight: screen.availHeight,
        colorDepth:  screen.colorDepth,
        pixelDepth:  screen.pixelDepth,
        orientation: S(() => ({ type: screen.orientation.type, angle: screen.orientation.angle })),
    }));

    // ── 4. WINDOW ────────────────────────────────────────────────
    const win = S(() => ({
        innerWidth:       window.innerWidth,
        innerHeight:      window.innerHeight,
        outerWidth:       window.outerWidth,
        outerHeight:      window.outerHeight,
        devicePixelRatio: window.devicePixelRatio,
        screenX:          window.screenX,
        screenY:          window.screenY,
    }));

    // ── 5. TIMEZONE ──────────────────────────────────────────────
    const tz = S(() => {
        const o = Intl.DateTimeFormat().resolvedOptions();
        return {
            timeZone:         o.timeZone,
            locale:           o.locale,
            calendar:         o.calendar,
            numberingSystem:  o.numberingSystem,
            hourCycle:        o.hourCycle,
            offset_minutes:   -(new Date().getTimezoneOffset()),
        };
    });

    // ── 6. PERMISSIONS ───────────────────────────────────────────
    const perms = {};
    for (const name of ['notifications','clipboard-read','clipboard-write','camera','microphone','geolocation']) {
        perms[name] = await A(async () => (await navigator.permissions.query({ name })).state);
    }

    // ── 7. STORAGE ───────────────────────────────────────────────
    const storage = S(() => ({
        localStorage_length:   localStorage.length,
        sessionStorage_length: sessionStorage.length,
        indexedDB_available:   typeof indexedDB !== 'undefined',
        caches_available:      typeof caches    !== 'undefined',
    }));

    // ── 8. WEBGL ─────────────────────────────────────────────────
    const webgl = S(() => {
        const c  = document.createElement('canvas');
        const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
        if (!gl) return { supported: false };
        const ext  = gl.getExtension('WEBGL_debug_renderer_info');
        const exts = gl.getSupportedExtensions() || [];
        const GP = (id) => {
            try { const v = gl.getParameter(id); return (v instanceof Float32Array || v instanceof Int32Array) ? Array.from(v) : v; }
            catch(e) { return null; }
        };
        return {
            supported:                true,
            version:                  GP(gl.VERSION),
            shading_language_version: GP(gl.SHADING_LANGUAGE_VERSION),
            vendor:                   GP(gl.VENDOR),
            renderer:                 GP(gl.RENDERER),
            unmasked_vendor:          ext ? GP(ext.UNMASKED_VENDOR_WEBGL)   : null,
            unmasked_renderer:        ext ? GP(ext.UNMASKED_RENDERER_WEBGL) : null,
            max_texture_size:         GP(gl.MAX_TEXTURE_SIZE),
            max_renderbuffer_size:    GP(gl.MAX_RENDERBUFFER_SIZE),
            max_vertex_attribs:       GP(gl.MAX_VERTEX_ATTRIBS),
            aliased_line_width_range: GP(gl.ALIASED_LINE_WIDTH_RANGE),
            aliased_point_size_range: GP(gl.ALIASED_POINT_SIZE_RANGE),
            extension_count:          exts.length,
            extensions:               exts,
        };
    });

    // WebGL2
    const webgl2 = S(() => {
        const c  = document.createElement('canvas');
        const gl = c.getContext('webgl2');
        if (!gl) return { supported: false };
        return { supported: true, version: gl.getParameter(gl.VERSION) };
    });

    // ── 9. CANVAS FINGERPRINT ────────────────────────────────────
    const canvas = S(() => {
        const c   = document.createElement('canvas');
        c.width   = 300; c.height = 150;
        const ctx = c.getContext('2d');
        if (!ctx) return { supported: false };

        ctx.textBaseline = 'alphabetic';
        ctx.fillStyle    = '#f60';
        ctx.fillRect(125, 1, 62, 20);
        ctx.fillStyle = '#069';
        ctx.font      = '11pt no-real-font,Arial';
        ctx.fillText('Cwm fjordbank glyphs vext quiz, \xe9', 2, 15);
        ctx.fillStyle = 'rgba(102,204,0,0.7)';
        ctx.font      = '18pt Arial';
        ctx.fillText('Cwm fjordbank glyphs vext quiz, \xe9', 4, 45);
        ctx.beginPath();
        ctx.arc(50, 50, 50, 0, Math.PI * 2, true);
        ctx.closePath();
        ctx.fillStyle = 'rgba(255,0,255,0.5)';
        ctx.fill();

        const url = c.toDataURL('image/png');
        let hash  = 0;
        for (let i = 0; i < url.length; i++) { hash = ((hash << 5) - hash) + url.charCodeAt(i); hash |= 0; }
        return { supported: true, hash, length: url.length, prefix: url.substring(0, 80) };
    });

    // ── 10. AUDIO FINGERPRINT ────────────────────────────────────
    const audio = await A(async () => {
        const ctx  = new OfflineAudioContext(1, 44100, 44100);
        const osc  = ctx.createOscillator();
        const comp = ctx.createDynamicsCompressor();
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(10000, ctx.currentTime);
        comp.threshold.setValueAtTime(-50, ctx.currentTime);
        comp.knee.setValueAtTime(40, ctx.currentTime);
        comp.ratio.setValueAtTime(12, ctx.currentTime);
        comp.attack.setValueAtTime(0, ctx.currentTime);
        comp.release.setValueAtTime(0.25, ctx.currentTime);
        osc.connect(comp);
        comp.connect(ctx.destination);
        osc.start(0);
        const buf  = await ctx.startRendering();
        const data = buf.getChannelData(0);
        let   sum  = 0;
        for (let i = 0; i < data.length; i++) sum += Math.abs(data[i]);
        const samples = Array.from(data.slice(4500, 4520));
        return { sample_sum: sum, samples_4500_4520: samples };
    });

    // ── 11. FONTS (canvas measurement) ───────────────────────────
    const fonts = S(() => {
        const TEST_FONTS = [
            'Arial','Arial Black','Arial Narrow','Calibri','Cambria','Candara',
            'Comic Sans MS','Consolas','Constantia','Corbel','Courier New',
            'Georgia','Helvetica','Impact','Lucida Console','Lucida Sans Unicode',
            'Microsoft Sans Serif','Palatino Linotype','Segoe UI','Symbol',
            'Tahoma','Times New Roman','Trebuchet MS','Verdana','Wingdings',
            'DejaVu Sans','DejaVu Serif','FreeSerif','Liberation Sans','Ubuntu',
            'MS Gothic','MS Mincho','Osaka','Roboto','Open Sans','Noto Sans',
        ];
        const c   = document.createElement('canvas');
        const ctx = c.getContext('2d');
        if (!ctx) return null;
        const TEXT     = 'mmmmmmmmmmlli';
        const BASELINE = 'monospace';
        ctx.font       = `16px ${BASELINE}`;
        const baseW    = ctx.measureText(TEXT).width;
        const detected = [];
        for (const f of TEST_FONTS) {
            ctx.font = `16px '${f}',${BASELINE}`;
            if (ctx.measureText(TEXT).width !== baseW) detected.push(f);
        }
        return { count: detected.length, detected };
    });

    // ── 12. CSS FEATURE DETECTION ────────────────────────────────
    const css = S(() => {
        const sup = (v) => S(() => CSS.supports(v), null);
        return {
            supports: {
                grid:               sup('display:grid'),
                flex:               sup('display:flex'),
                variables:          sup('--x:1'),
                animation:          sup('animation-name:foo'),
                transition:         sup('transition:all 0s'),
                transform:          sup('transform:rotate(0deg)'),
                'backdrop-filter':  sup('backdrop-filter:blur(1px)'),
                'aspect-ratio':     sup('aspect-ratio:1'),
                container:          sup('container-type:inline-size'),
            },
            touch_support:    'ontouchstart' in window,
            pointer_events:   typeof PointerEvent !== 'undefined',
            hover_hover:      S(() => matchMedia('(hover:hover)').matches, null),
            prefers_dark:     S(() => matchMedia('(prefers-color-scheme:dark)').matches, null),
            reduced_motion:   S(() => matchMedia('(prefers-reduced-motion:reduce)').matches, null),
        };
    });

    // ── 13. CHROME OBJECT ────────────────────────────────────────
    const chrome_obj = S(() => {
        if (typeof window.chrome === 'undefined') return { present: false };
        const cr = window.chrome;
        return {
            present:       true,
            keys:          Object.keys(cr),
            runtime: {
                present:     typeof cr.runtime         !== 'undefined',
                id:          S(() => cr.runtime.id,    null),
                has_connect: typeof cr.runtime?.connect     === 'function',
                has_send:    typeof cr.runtime?.sendMessage === 'function',
            },
            loadTimes: {
                present: typeof cr.loadTimes === 'function',
                value:   S(() => { const lt = cr.loadTimes(); return { requestTime: lt.requestTime, startLoadTime: lt.startLoadTime }; }, null),
            },
            csi: {
                present: typeof cr.csi === 'function',
                value:   S(() => { const c = cr.csi(); return { startE: c.startE, onloadT: c.onloadT, pageT: c.pageT }; }, null),
            },
            app:      { present: typeof cr.app      !== 'undefined' },
            webstore: { present: typeof cr.webstore !== 'undefined' },
        };
    });

    // ── 14. PERFORMANCE ──────────────────────────────────────────
    const perf = S(() => {
        const mem = S(() => {
            const m = performance.memory;
            return m ? { jsHeapSizeLimit: m.jsHeapSizeLimit, totalJSHeapSize: m.totalJSHeapSize, usedJSHeapSize: m.usedJSHeapSize } : null;
        });
        const nav_e = performance.getEntriesByType('navigation');
        const nav_t = nav_e.length ? {
            type:                     nav_e[0].type,
            domContentLoadedEventEnd: nav_e[0].domContentLoadedEventEnd,
            loadEventEnd:             nav_e[0].loadEventEnd,
            duration:                 nav_e[0].duration,
        } : null;
        return { timeOrigin: performance.timeOrigin, now: performance.now(), memory: mem, navigation_timing: nav_t };
    });

    // ── 15. HISTORY / DOCUMENT / BATTERY / SPEECH / RTC ─────────
    const history_d  = S(() => ({ length: history.length }));
    const battery_d  = await A(async () => {
        const b = await navigator.getBattery();
        return { charging: b.charging, level: b.level, chargingTime: b.chargingTime, dischargingTime: b.dischargingTime };
    });
    const speech_d   = S(() => {
        if (typeof speechSynthesis === 'undefined') return null;
        const v = speechSynthesis.getVoices();
        return { count: v.length, voices: v.map(x => ({ name: x.name, lang: x.lang, local: x.localService })) };
    });
    const rtc_d      = S(() => ({
        RTCPeerConnection:    typeof RTCPeerConnection    !== 'undefined',
        RTCSessionDescription: typeof RTCSessionDescription !== 'undefined',
        RTCIceCandidate:      typeof RTCIceCandidate      !== 'undefined',
    }));
    const media_devs = await A(async () => {
        const ds = await navigator.mediaDevices.enumerateDevices();
        return ds.map(d => ({ kind: d.kind, label: d.label, groupId: d.groupId }));
    });

    // ── 16. DOCUMENT / COOKIES ───────────────────────────────────
    const doc_d = S(() => {
        const raw   = document.cookie;
        const names = raw ? raw.split(';').map(c => c.trim().split('=')[0].trim()).filter(Boolean) : [];
        return { cookie_count: names.length, cookie_names: names, readyState: document.readyState,
                 referrer: document.referrer, visibilityState: document.visibilityState, characterSet: document.characterSet };
    });

    // ── 17. FEATURE FLAGS ────────────────────────────────────────
    const features = S(() => ({
        fetch:                typeof fetch               !== 'undefined',
        AbortController:      typeof AbortController    !== 'undefined',
        Worker:               typeof Worker             !== 'undefined',
        SharedWorker:         typeof SharedWorker       !== 'undefined',
        ServiceWorker:        typeof navigator.serviceWorker !== 'undefined',
        WebSocket:            typeof WebSocket          !== 'undefined',
        WebAssembly:          typeof WebAssembly        !== 'undefined',
        SharedArrayBuffer:    typeof SharedArrayBuffer  !== 'undefined',
        IntersectionObserver: typeof IntersectionObserver !== 'undefined',
        ResizeObserver:       typeof ResizeObserver     !== 'undefined',
        MutationObserver:     typeof MutationObserver   !== 'undefined',
        crypto:               typeof crypto             !== 'undefined',
        crypto_subtle:        typeof crypto?.subtle     !== 'undefined',
        Notification:         typeof Notification       !== 'undefined',
        notification_permission: S(() => Notification.permission, null),
        navigator_usb:        typeof navigator.usb      !== 'undefined',
        navigator_serial:     typeof navigator.serial   !== 'undefined',
        navigator_hid:        typeof navigator.hid      !== 'undefined',
        navigator_bluetooth:  typeof navigator.bluetooth !== 'undefined',
        navigator_gpu:        typeof navigator.gpu      !== 'undefined',
        navigator_keyboard:   typeof navigator.keyboard !== 'undefined',
        BigInt:               typeof BigInt             !== 'undefined',
        Proxy:                typeof Proxy              !== 'undefined',
    }));

    return {
        navigator: {
            ...nav,
            userAgentData: uad,
            connection,
            keyboard_available:    typeof navigator.keyboard    !== 'undefined',
            bluetooth_available:   typeof navigator.bluetooth   !== 'undefined',
            media_devices: media_devs,
        },
        plugins,
        screen:      scr,
        window:      win,
        timezone:    tz,
        permissions: perms,
        storage,
        webgl,
        webgl2,
        canvas,
        audio,
        fonts,
        css,
        chrome:      chrome_obj,
        performance: perf,
        history:     history_d,
        battery:     battery_d,
        speech:      speech_d,
        rtc:         rtc_d,
        document:    doc_d,
        features,
    };
}
"""


# ══════════════════════════════════════════════════════════════════
# BROWSER LAUNCH
# ══════════════════════════════════════════════════════════════════

def launch_browser(pw, channel: str, headless: bool, profile: str | None):
    """
    Launch browser — persistent profile if --profile given, else ephemeral.
    Returns (closeable_handle, page, is_persistent).
    """
    kwargs: dict = dict(
        headless = headless,
        args     = ["--no-sandbox", "--disable-dev-shm-usage"],
    )
    if channel:
        kwargs["channel"] = channel

    if profile:
        Path(profile).mkdir(parents=True, exist_ok=True)
        print(f"[INFO] Persistent profile : {profile}")
        ctx  = pw.chromium.launch_persistent_context(str(profile), **kwargs)
        page = ctx.new_page()
        return ctx, page, True

    browser = pw.chromium.launch(**kwargs)
    ctx     = browser.new_context()
    page    = ctx.new_page()
    return browser, page, False


# ══════════════════════════════════════════════════════════════════
# COLLECT
# ══════════════════════════════════════════════════════════════════

def collect(page, url: str, wait_ms: int) -> dict:
    """Navigate, wait, evaluate JS fingerprint payload."""
    print(f"[INFO] Opening : {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    if wait_ms > 0:
        print(f"[INFO] Waiting : {wait_ms} ms")
        page.wait_for_timeout(wait_ms)
    print("[INFO] Collecting fingerprint...")
    return page.evaluate(_JS)


# ══════════════════════════════════════════════════════════════════
# SAVE
# ══════════════════════════════════════════════════════════════════

def save(data: dict, path: str, url: str, channel: str, headless: bool) -> None:
    out = {
        "_meta": {
            "tool":         "fingerprint_dump.py",
            "collected_at": datetime.now().isoformat(),
            "url":          url,
            "channel":      channel or "chromium (bundled)",
            "headless":     headless,
        },
        "fingerprint": data,
    }
    Path(path).write_text(json.dumps(out, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"[OK]  Saved    : {path}")


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Collect a comprehensive browser fingerprint using Playwright.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Real Chrome (non-headless, on machine with Chrome installed):
  python fingerprint_dump.py --channel chrome --no-headless --output fingerprint_real.json

  # Playwright Chromium (headless, server):
  python fingerprint_dump.py --output fingerprint_playwright.json

  # Visit actual target site and wait 10 seconds:
  python fingerprint_dump.py --channel chrome --url https://bromotenggersemeru.id --wait 10000 --output fp_cf.json
""",
    )
    p.add_argument("--output",    "-o", default="fingerprint.json", help="Output JSON file (default: fingerprint.json)")
    p.add_argument("--url",       "-u", default="about:blank",      help="URL to visit (default: about:blank)")
    p.add_argument("--channel",         default="",                  help="Browser channel: 'chrome', 'msedge', or empty for bundled Chromium")
    p.add_argument("--no-headless",     action="store_true",         help="Run in visible (non-headless) mode")
    p.add_argument("--wait",            type=int, default=3000,      help="Milliseconds to wait after page load (default: 3000)")
    p.add_argument("--profile",         default="",                  help="Path to persistent browser profile directory (optional)")
    return p


def main() -> int:
    args     = build_parser().parse_args()
    headless = not args.no_headless

    print(f"[INFO] Channel  : {args.channel or 'chromium (bundled)'}")
    print(f"[INFO] Headless : {headless}")
    print(f"[INFO] URL      : {args.url}")
    print(f"[INFO] Output   : {args.output}")

    with sync_playwright() as pw:
        handle, page, is_persistent = launch_browser(
            pw, args.channel, headless, args.profile or None
        )
        try:
            data = collect(page, args.url, args.wait)
        finally:
            handle.close()

    save(data, args.output, args.url, args.channel, headless)
    return 0


if __name__ == "__main__":
    sys.exit(main())
