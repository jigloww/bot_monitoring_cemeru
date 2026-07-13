"""
tools/feature_detector.py — Detect browser feature availability and experimental APIs.

Collects Chrome-specific, deprecated, experimental, and standard APIs.

Usage:
    python tools/feature_detector.py --output tools/output/features.json
    python tools/feature_detector.py --channel chrome --no-headless
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
    const def = v => typeof v !== 'undefined';

    // ── Standard APIs ─────────────────────────────────────────
    const standard = {
        fetch:                def(fetch),
        AbortController:      def(AbortController),
        Worker:               def(Worker),
        SharedWorker:         def(SharedWorker),
        ServiceWorker:        def(navigator.serviceWorker),
        WebSocket:            def(WebSocket),
        EventSource:          def(EventSource),
        WebAssembly:          def(WebAssembly),
        SharedArrayBuffer:    def(SharedArrayBuffer),
        Atomics:              def(Atomics),
        BigInt:               def(BigInt),
        Proxy:                def(Proxy),
        Reflect:              def(Reflect),
        Symbol:               def(Symbol),
        Map:                  def(Map),
        Set:                  def(Set),
        WeakMap:              def(WeakMap),
        WeakSet:              def(WeakSet),
        WeakRef:              def(WeakRef),
        FinalizationRegistry: def(FinalizationRegistry),
        structuredClone:      def(structuredClone),
        queueMicrotask:       def(queueMicrotask),
        requestIdleCallback:  def(requestIdleCallback),
        requestAnimationFrame:def(requestAnimationFrame),
    };

    // ── Observer APIs ─────────────────────────────────────────
    const observers = {
        IntersectionObserver:  def(IntersectionObserver),
        ResizeObserver:        def(ResizeObserver),
        MutationObserver:      def(MutationObserver),
        PerformanceObserver:   def(PerformanceObserver),
        ReportingObserver:     def(ReportingObserver),
    };

    // ── Storage APIs ──────────────────────────────────────────
    const storage_apis = {
        localStorage:       S(()=>{localStorage.setItem('_t','1');localStorage.removeItem('_t');return true;},false),
        sessionStorage:     def(sessionStorage),
        indexedDB:          def(indexedDB),
        caches:             def(caches),
        cookieStore:        def(cookieStore),
        FileSystem:         def(FileSystemHandle),
    };

    // ── Crypto ────────────────────────────────────────────────
    const crypto_apis = {
        crypto:         def(crypto),
        subtle:         def(crypto?.subtle),
        getRandomValues:typeof crypto?.getRandomValues==='function',
        randomUUID:     typeof crypto?.randomUUID==='function',
    };

    // ── Media APIs ────────────────────────────────────────────
    const media_apis = {
        MediaRecorder:         def(MediaRecorder),
        MediaSource:           def(MediaSource),
        ManagedMediaSource:    def(ManagedMediaSource),
        AudioContext:          def(AudioContext),
        OfflineAudioContext:   def(OfflineAudioContext),
        VideoDecoder:          def(VideoDecoder),
        VideoEncoder:          def(VideoEncoder),
        PictureInPicture:      def(document.pictureInPictureEnabled),
        MediaCapabilities:     def(navigator.mediaCapabilities),
        ImageCapture:          def(ImageCapture),
        CanvasCaptureMediaStreamTrack: def(CanvasCaptureMediaStreamTrack),
    };

    // ── Graphics APIs ─────────────────────────────────────────
    const graphics_apis = {
        WebGL:            S(()=>!!document.createElement('canvas').getContext('webgl')),
        WebGL2:           S(()=>!!document.createElement('canvas').getContext('webgl2')),
        WebGPU:           def(navigator.gpu),
        OffscreenCanvas:  def(OffscreenCanvas),
        Path2D:           def(Path2D),
    };

    // ── Chrome-specific APIs ──────────────────────────────────
    const chrome_specific = {
        chrome_present:        def(window.chrome),
        chrome_runtime:        def(window.chrome?.runtime),
        chrome_loadTimes:      typeof window.chrome?.loadTimes==='function',
        chrome_csi:            typeof window.chrome?.csi==='function',
        chrome_app:            def(window.chrome?.app),
        chrome_cast:           def(window.chrome?.cast),
        chrome_webstore:       def(window.chrome?.webstore),
        chrome_accessibilityFeatures: def(window.chrome?.accessibilityFeatures),
        chrome_commands:       def(window.chrome?.commands),
    };

    // ── Hardware APIs ─────────────────────────────────────────
    const hardware = {
        bluetooth:   def(navigator.bluetooth),
        usb:         def(navigator.usb),
        serial:      def(navigator.serial),
        hid:         def(navigator.hid),
        nfc:         def(navigator.nfc),
        keyboard:    def(navigator.keyboard),
        gamepad:     typeof navigator.getGamepads==='function',
        vibrate:     typeof navigator.vibrate==='function',
        clipboard:   def(navigator.clipboard),
        credentials: def(navigator.credentials),
        gpu:         def(navigator.gpu),
    };

    // ── Sensor APIs ───────────────────────────────────────────
    const sensors = {
        Accelerometer:     def(Accelerometer),
        Gyroscope:         def(Gyroscope),
        Magnetometer:      def(Magnetometer),
        AbsoluteOrientationSensor: def(AbsoluteOrientationSensor),
        AmbientLightSensor: def(AmbientLightSensor),
    };

    // ── Communication ─────────────────────────────────────────
    const communication = {
        WebRTC:             def(RTCPeerConnection),
        BroadcastChannel:   def(BroadcastChannel),
        MessageChannel:     def(MessageChannel),
        Notification:       def(Notification),
        Push:               def(PushManager),
        BackgroundFetch:    def(BackgroundFetchManager),
        BackgroundSync:     def(SyncManager),
    };

    // ── Payments ──────────────────────────────────────────────
    const payments = {
        PaymentRequest:     def(PaymentRequest),
        PaymentHandler:     def(PaymentRequestEvent),
    };

    // ── CSS ───────────────────────────────────────────────────
    const css_features = {
        paintWorklet:  def(CSS.paintWorklet),
        highlights:    def(CSS.highlights),
        supports_grid: S(()=>CSS.supports('display:grid')),
        supports_has:  S(()=>CSS.supports('selector(:has(a))')),
        supports_container: S(()=>CSS.supports('container-type:inline-size')),
        supports_subgrid:   S(()=>CSS.supports('grid-template-columns:subgrid')),
        supports_layer:     S(()=>CSS.supports('@layer foo{}')),
    };

    // ── Deprecated / legacy ───────────────────────────────────
    const deprecated = {
        appCache:           def(applicationCache),
        webkitSpeechRec:    def(webkitSpeechRecognition),
        webkitIndexedDB:    def(webkitIndexedDB),
        webkitRequestAnimationFrame: def(webkitRequestAnimationFrame),
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
