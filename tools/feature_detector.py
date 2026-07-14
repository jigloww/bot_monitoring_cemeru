"""
tools/feature_detector.py — Detect browser feature availability and experimental APIs.

Collects Chrome-specific, deprecated, experimental, and standard APIs.

Usage:
    python tools/feature_detector.py --output reports/features/features.json
    python tools/feature_detector.py --channel chrome --no-headless --output features.json
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from playwright.sync_api import sync_playwright
from tools._shared import (BrowserConfig, ensure_output_dir, launch_browser,
                            navigate, save_json, setup_logging, add_browser_args, add_output_arg)

log = setup_logging("feature_detector")

_FEATURES_JS = """async () => {
    const S  = (fn,fb=null)=>{try{return fn();}catch(e){return fb;}};
    const A  = async(fn,fb=null)=>{try{return await fn();}catch(e){return fb;}};

    // exists(fn) — safe API availability check via arrow-function wrapper.
    // Catches both ReferenceError (API undefined globally) and TypeError.
    // Usage: exists(()=>Worker)  exists(()=>navigator.bluetooth)
    const exists = (fn) => { try { return typeof fn() !== 'undefined'; } catch(e) { return false; } };

    // ── Standard APIs ─────────────────────────────────────────
    const standard = {
        fetch:                exists(()=>fetch),
        AbortController:      exists(()=>AbortController),
        Worker:               exists(()=>Worker),
        SharedWorker:         exists(()=>SharedWorker),
        ServiceWorker:        exists(()=>navigator.serviceWorker),
        WebSocket:            exists(()=>WebSocket),
        EventSource:          exists(()=>EventSource),
        WebAssembly:          exists(()=>WebAssembly),
        SharedArrayBuffer:    exists(()=>SharedArrayBuffer),
        Atomics:              exists(()=>Atomics),
        BigInt:               exists(()=>BigInt),
        Proxy:                exists(()=>Proxy),
        Reflect:              exists(()=>Reflect),
        Symbol:               exists(()=>Symbol),
        Map:                  exists(()=>Map),
        Set:                  exists(()=>Set),
        WeakMap:              exists(()=>WeakMap),
        WeakSet:              exists(()=>WeakSet),
        WeakRef:              exists(()=>WeakRef),
        FinalizationRegistry: exists(()=>FinalizationRegistry),
        structuredClone:      exists(()=>structuredClone),
        queueMicrotask:       exists(()=>queueMicrotask),
        requestIdleCallback:  exists(()=>requestIdleCallback),
        requestAnimationFrame:exists(()=>requestAnimationFrame),
    };

    // ── Observer APIs ─────────────────────────────────────────
    const observers = {
        IntersectionObserver:  exists(()=>IntersectionObserver),
        ResizeObserver:        exists(()=>ResizeObserver),
        MutationObserver:      exists(()=>MutationObserver),
        PerformanceObserver:   exists(()=>PerformanceObserver),
        ReportingObserver:     exists(()=>ReportingObserver),
    };

    // ── Storage APIs ──────────────────────────────────────────
    const storage_apis = {
        localStorage:       S(()=>{localStorage.setItem('_t','1');localStorage.removeItem('_t');return true;},false),
        sessionStorage:     exists(()=>sessionStorage),
        indexedDB:          exists(()=>indexedDB),
        caches:             exists(()=>caches),
        cookieStore:        exists(()=>cookieStore),
        FileSystem:         exists(()=>FileSystemHandle),
    };

    // ── Crypto ────────────────────────────────────────────────
    const crypto_apis = {
        crypto:         exists(()=>crypto),
        subtle:         exists(()=>crypto.subtle),
        getRandomValues:typeof crypto?.getRandomValues==='function',
        randomUUID:     typeof crypto?.randomUUID==='function',
    };

    // ── Media APIs ────────────────────────────────────────────
    const media_apis = {
        MediaRecorder:         exists(()=>MediaRecorder),
        MediaSource:           exists(()=>MediaSource),
        ManagedMediaSource:    exists(()=>ManagedMediaSource),
        AudioContext:          exists(()=>AudioContext),
        OfflineAudioContext:   exists(()=>OfflineAudioContext),
        VideoDecoder:          exists(()=>VideoDecoder),
        VideoEncoder:          exists(()=>VideoEncoder),
        PictureInPicture:      S(()=>document.pictureInPictureEnabled, false),
        MediaCapabilities:     exists(()=>navigator.mediaCapabilities),
        ImageCapture:          exists(()=>ImageCapture),
        CanvasCaptureMediaStreamTrack: exists(()=>CanvasCaptureMediaStreamTrack),
    };

    // ── Graphics APIs ─────────────────────────────────────────
    const graphics_apis = {
        WebGL:            S(()=>!!document.createElement('canvas').getContext('webgl')),
        WebGL2:           S(()=>!!document.createElement('canvas').getContext('webgl2')),
        WebGPU:           exists(()=>navigator.gpu),
        OffscreenCanvas:  exists(()=>OffscreenCanvas),
        Path2D:           exists(()=>Path2D),
    };

    // ── Chrome-specific APIs ──────────────────────────────────
    const chrome_specific = {
        chrome_present:        exists(()=>window.chrome),
        chrome_runtime:        exists(()=>window.chrome.runtime),
        chrome_loadTimes:      typeof window.chrome?.loadTimes==='function',
        chrome_csi:            typeof window.chrome?.csi==='function',
        chrome_app:            exists(()=>window.chrome.app),
        chrome_cast:           exists(()=>window.chrome.cast),
        chrome_webstore:       exists(()=>window.chrome.webstore),
        chrome_accessibilityFeatures: exists(()=>window.chrome.accessibilityFeatures),
        chrome_commands:       exists(()=>window.chrome.commands),
    };

    // ── Hardware APIs ─────────────────────────────────────────
    const hardware = {
        bluetooth:   exists(()=>navigator.bluetooth),
        usb:         exists(()=>navigator.usb),
        serial:      exists(()=>navigator.serial),
        hid:         exists(()=>navigator.hid),
        nfc:         exists(()=>navigator.nfc),
        keyboard:    exists(()=>navigator.keyboard),
        gamepad:     typeof navigator.getGamepads==='function',
        vibrate:     typeof navigator.vibrate==='function',
        clipboard:   exists(()=>navigator.clipboard),
        credentials: exists(()=>navigator.credentials),
        gpu:         exists(()=>navigator.gpu),
    };

    // ── Sensor APIs ───────────────────────────────────────────
    const sensors = {
        Accelerometer:     exists(()=>Accelerometer),
        Gyroscope:         exists(()=>Gyroscope),
        Magnetometer:      exists(()=>Magnetometer),
        AbsoluteOrientationSensor: exists(()=>AbsoluteOrientationSensor),
        AmbientLightSensor: exists(()=>AmbientLightSensor),
    };

    // ── Communication ─────────────────────────────────────────
    const communication = {
        WebRTC:             exists(()=>RTCPeerConnection),
        BroadcastChannel:   exists(()=>BroadcastChannel),
        MessageChannel:     exists(()=>MessageChannel),
        Notification:       exists(()=>Notification),
        Push:               exists(()=>PushManager),
        BackgroundFetch:    exists(()=>BackgroundFetchManager),
        BackgroundSync:     exists(()=>SyncManager),
    };

    // ── Payments ──────────────────────────────────────────────
    const payments = {
        PaymentRequest:     exists(()=>PaymentRequest),
        PaymentHandler:     exists(()=>PaymentRequestEvent),
    };

    // ── CSS ───────────────────────────────────────────────────
    const css_features = {
        paintWorklet:  exists(()=>CSS.paintWorklet),
        highlights:    exists(()=>CSS.highlights),
        supports_grid: S(()=>CSS.supports('display:grid')),
        supports_has:  S(()=>CSS.supports('selector(:has(a))')),
        supports_container: S(()=>CSS.supports('container-type:inline-size')),
        supports_subgrid:   S(()=>CSS.supports('grid-template-columns:subgrid')),
        supports_layer:     S(()=>CSS.supports('@layer foo{}')),
    };

    // ── Deprecated / legacy (all wrapped in exists to avoid ReferenceError) ─
    const deprecated = {
        appCache:           exists(()=>applicationCache),
        webkitSpeechRec:    exists(()=>webkitSpeechRecognition),
        webkitIndexedDB:    exists(()=>webkitIndexedDB),
        webkitRequestAnimationFrame: exists(()=>webkitRequestAnimationFrame),
    };

    // ── Permission states ─────────────────────────────────────
    const perm_names = ['notifications','camera','microphone','clipboard-read','clipboard-write','geolocation'];
    const permissions = {};
    for(const n of perm_names) {
        permissions[n] = await A(async()=>(await navigator.permissions.query({name:n})).state);
    }

    // ── window key count ──────────────────────────────────────
    const win_key_count    = Object.keys(window).length;
    const nav_key_count    = Object.keys(navigator).length;
    const win_own_count    = Object.getOwnPropertyNames(window).length;
    const nav_own_count    = Object.getOwnPropertyNames(Object.getPrototypeOf(navigator)).length;

    return {
        standard, observers, storage:storage_apis, crypto:crypto_apis,
        media:media_apis, graphics:graphics_apis, chrome:chrome_specific,
        hardware, sensors, communication, payments, css:css_features,
        deprecated, permissions,
        counts: { window_keys:win_key_count, navigator_keys:nav_key_count,
                  window_own:win_own_count, navigator_own:nav_own_count },
    };
}"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Detect browser feature availability across all API categories.")
    add_browser_args(p)
    add_output_arg(p, default="")
    return p


def main() -> int:
    from datetime import datetime
    args     = build_parser().parse_args()
    headless = not args.no_headless
    cfg      = BrowserConfig(channel=args.channel, headless=headless, profile=args.profile,
                             url=args.url, wait_ms=args.wait)
    out_path = Path(args.output) if args.output else ensure_output_dir() / "features.json"

    log.info("Channel: %s  URL: %s", cfg.channel or "chromium", cfg.url)

    with sync_playwright() as pw:
        handle, page, _ = launch_browser(pw, cfg)
        try:
            navigate(page, cfg.url, wait_ms=cfg.wait_ms)
            log.info("Evaluating feature detection payload…")
            data = page.evaluate(_FEATURES_JS)
        finally:
            handle.close()

    result = {
        "_meta": {"tool": "feature_detector.py", "collected_at": datetime.now().isoformat(),
                  "channel": cfg.channel or "chromium", "url": cfg.url},
        "features": data,
    }
    save_json(result, out_path)
    log.info("Saved → %s", out_path)

    # Print quick summary
    counts = data.get("counts", {})
    log.info("Window keys: %d  Navigator keys: %d", counts.get("window_keys", 0), counts.get("navigator_keys", 0))
    chrome = data.get("chrome", {})
    log.info("chrome object: present=%s  loadTimes=%s  csi=%s",
             chrome.get("chrome_present"), chrome.get("chrome_loadTimes"), chrome.get("chrome_csi"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
