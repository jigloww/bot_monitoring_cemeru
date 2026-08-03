"""Experiment 020: read-only browser session profiler.

The profiler records browser state without installing init scripts, stealth
patches, or API wrappers.  It is deliberately a snapshot tool: values are
read from the live page/context and sensitive contents (cookie/storage values,
extension files) are never persisted.  Artifact allocation and writes are
delegated to the existing immutable experiment helpers.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import sys
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    git_metadata,
    now_iso,
    package_version,
    project_root,
    sha256_file,
    relative_path,
    system_metadata,
    write_json_exclusive,
    write_text_exclusive,
)


PERMISSION_NAMES = (
    "camera", "microphone", "clipboard-read", "clipboard-write", "notifications",
    "geolocation", "background-sync", "persistent-storage", "midi", "accelerometer",
    "gyroscope", "magnetometer", "payment-handler",
)
DOMAIN_ARTIFACTS = {
    "navigator": "navigator.json", "window": "window.json", "screen": "screen.json",
    "permissions": "permissions.json", "fonts": "profile.json", "speech": "profile.json",
    "webgl": "webgl.json", "performance": "performance.json", "storage": "storage.json",
    "environment": "environment.json",
}


@dataclass(frozen=True)
class Settings:
    root: Path
    reports_dir: Path
    url: str
    runs: int
    timeout_ms: int
    headless: bool
    channel: str
    profile: Path | None


def _safe(value: Any, fallback: Any = None) -> Any:
    return value if value is not None else fallback


def _page_eval(page: Any, script: str, *, arg: Any = None, fallback: Any = None) -> Any:
    try:
        result = page.evaluate(script, arg) if arg is not None else page.evaluate(script)
        return result if result is not None else fallback
    except Exception as exc:
        return {"error": str(exc)} if fallback is None else fallback


def _cookie_metadata(context: Any) -> dict[str, Any]:
    try:
        cookies = context.cookies()
    except Exception as exc:
        return {"count": 0, "cookies": [], "error": str(exc)}
    redacted = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        value = str(cookie.get("value") or "")
        redacted.append({
            "name": cookie.get("name"), "domain": cookie.get("domain"), "path": cookie.get("path"),
            "secure": cookie.get("secure"), "httpOnly": cookie.get("httpOnly"),
            "sameSite": cookie.get("sameSite"), "expires": cookie.get("expires"),
            "value_present": bool(value), "value_length": len(value),
            "cf_cookie": cookie.get("name") in {"cf_clearance", "__cf_bm"} or str(cookie.get("name", "")).startswith("cf_chl_"),
        })
    return {"count": len(redacted), "cookies": redacted, "values_persisted": False}


def _navigator(page: Any) -> dict[str, Any]:
    return _page_eval(page, """async () => {
      const plugin = (item) => ({name: item.name || '', filename: item.filename || '', description: item.description || '', length: Number(item.length || 0)});
      const mime = (item) => ({type: item.type || '', suffixes: item.suffixes || '', description: item.description || ''});
      let uaData = null;
      try {
        if (navigator.userAgentData) {
          uaData = {brands: Array.from(navigator.userAgentData.brands || []), mobile: !!navigator.userAgentData.mobile, platform: navigator.userAgentData.platform || null};
          if (navigator.userAgentData.getHighEntropyValues) {
            const high = await navigator.userAgentData.getHighEntropyValues(['architecture','bitness','model','platformVersion','uaFullVersion','fullVersionList','wow64']);
            uaData = {...uaData, ...high};
          }
        }
      } catch (error) { uaData = {error: String(error)}; }
      return {
        userAgent: navigator.userAgent || null, platform: navigator.platform || null,
        languages: Array.from(navigator.languages || []), language: navigator.language || null,
        vendor: navigator.vendor || null, hardwareConcurrency: navigator.hardwareConcurrency || null,
        deviceMemory: navigator.deviceMemory || null, webdriver: navigator.webdriver,
        pdfViewerEnabled: navigator.pdfViewerEnabled, plugins: Array.from(navigator.plugins || [], plugin),
        mimeTypes: Array.from(navigator.mimeTypes || [], mime), userAgentData: uaData,
        brands: uaData ? uaData.brands || [] : [], mobile: uaData ? uaData.mobile : null,
        platformVersion: uaData ? uaData.platformVersion || null : null,
        architecture: uaData ? uaData.architecture || null : null,
        bitness: uaData ? uaData.bitness || null : null,
        wow64: uaData ? uaData.wow64 || null : null,
        fullVersionList: uaData ? uaData.fullVersionList || null : null
      };
    }""", fallback={"error": "navigator evaluation unavailable"})


def _window(page: Any) -> dict[str, Any]:
    return _page_eval(page, """() => {
      const vv = window.visualViewport;
      return {
        innerWidth: window.innerWidth, innerHeight: window.innerHeight,
        outerWidth: window.outerWidth, outerHeight: window.outerHeight,
        devicePixelRatio: window.devicePixelRatio, screenX: window.screenX, screenY: window.screenY,
        scrollX: window.scrollX, scrollY: window.scrollY,
        visualViewport: vv ? {width: vv.width, height: vv.height, offsetLeft: vv.offsetLeft, offsetTop: vv.offsetTop, scale: vv.scale} : null,
        name: window.name, hasFocus: document.hasFocus(), fullscreen: !!document.fullscreenElement
      };
    }""", fallback={"error": "window evaluation unavailable"})


def _screen(page: Any) -> dict[str, Any]:
    return _page_eval(page, """() => {
      const value = window.screen;
      const orientation = value && value.orientation ? {type: value.orientation.type, angle: value.orientation.angle} : null;
      return {width: value.width, height: value.height, availWidth: value.availWidth, availHeight: value.availHeight,
        availLeft: value.availLeft, availTop: value.availTop, colorDepth: value.colorDepth, pixelDepth: value.pixelDepth,
        orientation, isExtended: value.isExtended === undefined ? null : value.isExtended};
    }""", fallback={"error": "screen evaluation unavailable"})


def _storage(page: Any, context: Any) -> dict[str, Any]:
    cookies = _cookie_metadata(context)
    value = _page_eval(page, """async () => {
      let indexedDBNames = [], cacheNames = [], estimate = null;
      try { if (indexedDB.databases) indexedDBNames = (await indexedDB.databases()).map(item => item.name).filter(Boolean); } catch (_) {}
      try { if (window.caches) cacheNames = await caches.keys(); } catch (_) {}
      try { if (navigator.storage && navigator.storage.estimate) estimate = await navigator.storage.estimate(); } catch (_) {}
      return {localStorageKeys: Object.keys(localStorage), sessionStorageKeys: Object.keys(sessionStorage), indexedDBNames, cacheNames,
        storageEstimate: estimate ? {quota: estimate.quota || null, usage: estimate.usage || null, usageDetails: estimate.usageDetails || null} : null};
    }""", fallback={"localStorageKeys": [], "sessionStorageKeys": [], "indexedDBNames": [], "cacheNames": [], "storageEstimate": None})
    return {"cookies": cookies, **(value if isinstance(value, dict) else {})}


def _permissions(page: Any) -> dict[str, Any]:
    value = _page_eval(page, """async (names) => {
      const output = {};
      for (const name of names) {
        try {
          if (!navigator.permissions || !navigator.permissions.query) { output[name] = {state: null, supported: false, source: 'missing'}; continue; }
          const status = await navigator.permissions.query({name});
          output[name] = {state: status.state || null, supported: true, source: 'native'};
        } catch (error) { output[name] = {state: null, supported: false, source: 'native', error: String(error)}; }
      }
      return output;
    }""", arg=list(PERMISSION_NAMES), fallback={})
    return {"permissions": value if isinstance(value, dict) else {}, "requested": list(PERMISSION_NAMES)}


def _fonts(page: Any) -> dict[str, Any]:
    return _page_eval(page, """async () => {
      try {
        const set = document.fonts;
        const values = set ? Array.from(set).slice(0, 500).map(font => ({family: font.family, style: font.style, weight: font.weight, stretch: font.stretch, status: font.status})) : [];
        return {supported: !!set, status: set ? set.status : null, count: set ? set.size : 0, faces: values};
      } catch (error) { return {supported: false, count: 0, faces: [], error: String(error)}; }
    }""", fallback={"supported": False, "count": 0, "faces": []})


def _speech(page: Any) -> dict[str, Any]:
    return _page_eval(page, """() => {
      try {
        if (!window.speechSynthesis || !speechSynthesis.getVoices) return {supported: false, count: 0, voices: []};
        const voices = speechSynthesis.getVoices().map(voice => ({voiceURI: voice.voiceURI, name: voice.name, lang: voice.lang, localService: !!voice.localService, default: !!voice.default}));
        return {supported: true, count: voices.length, voices};
      } catch (error) { return {supported: false, count: 0, voices: [], error: String(error)}; }
    }""", fallback={"supported": False, "count": 0, "voices": []})


def _extensions() -> dict[str, Any]:
    # Web pages cannot enumerate installed extensions without privileged APIs.
    return {"supported": False, "count": 0, "ids": [], "origins": [], "manifest_versions": [], "source": "not_exposed_to_web_context", "contents_read": False}


def _webgl(page: Any) -> dict[str, Any]:
    return _page_eval(page, """() => {
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('webgl2') || canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
      if (!context) return {available: false, webgl2: false, supportedExtensions: []};
      const debug = context.getExtension('WEBGL_debug_renderer_info');
      const anisotropic = context.getExtension('EXT_texture_filter_anisotropic') || context.getExtension('MOZ_EXT_texture_filter_anisotropic') || context.getExtension('WEBKIT_EXT_texture_filter_anisotropic');
      const get = (constant) => { try { return context.getParameter(constant); } catch (_) { return null; } };
      const dims = get(context.MAX_VIEWPORT_DIMS);
      return {available: true, webgl2: !!canvas.getContext('webgl2'), vendor: debug ? get(debug.UNMASKED_VENDOR_WEBGL) : get(context.VENDOR), renderer: debug ? get(debug.UNMASKED_RENDERER_WEBGL) : get(context.RENDERER),
        version: get(context.VERSION), shadingLanguageVersion: get(context.SHADING_LANGUAGE_VERSION), supportedExtensions: context.getSupportedExtensions() || [],
        maxTextureSize: get(context.MAX_TEXTURE_SIZE), maxRenderbufferSize: get(context.MAX_RENDERBUFFER_SIZE), maxViewport: dims ? Array.from(dims) : null,
        anisotropy: anisotropic ? get(anisotropic.MAX_TEXTURE_MAX_ANISOTROPY_EXT) : null, debugRendererInfo: !!debug};
    }""", fallback={"available": False, "webgl2": False, "supportedExtensions": []})


def _performance(page: Any) -> dict[str, Any]:
    return _page_eval(page, """() => {
      const nav = performance.getEntriesByType('navigation')[0] || null;
      const paints = performance.getEntriesByType('paint').map(entry => ({name: entry.name, startTime: entry.startTime, duration: entry.duration}));
      const lcp = performance.getEntriesByType('largest-contentful-paint').map(entry => ({startTime: entry.startTime, size: entry.size || null, url: entry.url || null}));
      const timing = performance.timing || {};
      const keys = ['navigationStart','fetchStart','requestStart','responseStart','responseEnd','domInteractive','domContentLoadedEventEnd','loadEventEnd'];
      const legacy = {}; for (const key of keys) legacy[key] = typeof timing[key] === 'number' ? timing[key] : null;
      return {timeOrigin: performance.timeOrigin, now: performance.now(), navigation: nav ? {name: nav.name, type: nav.type, duration: nav.duration, redirectCount: nav.redirectCount, nextHopProtocol: nav.nextHopProtocol, requestStart: nav.requestStart, responseStart: nav.responseStart, responseEnd: nav.responseEnd, domInteractive: nav.domInteractive, domContentLoadedEventEnd: nav.domContentLoadedEventEnd, loadEventEnd: nav.loadEventEnd} : null,
        timing: legacy, resourceTimingCount: performance.getEntriesByType('resource').length, resourceEntries: performance.getEntriesByType('resource').slice(0, 500).map(entry => ({name: entry.name, initiatorType: entry.initiatorType, startTime: entry.startTime, duration: entry.duration, transferSize: entry.transferSize || 0})), paintEntries: paints, largestContentfulPaint: lcp};
    }""", fallback={"error": "performance evaluation unavailable"})


def _memory(page: Any) -> dict[str, Any]:
    return _page_eval(page, """() => {
      const memory = performance.memory || null;
      return {jsHeap: memory ? memory.jsHeapSizeLimit || null : null, usedHeap: memory ? memory.usedJSHeapSize || null : null, totalHeap: memory ? memory.totalJSHeapSize || null : null, heapLimit: memory ? memory.jsHeapSizeLimit || null : null, deviceMemory: navigator.deviceMemory || null, supported: !!memory};
    }""", fallback={"supported": False, "jsHeap": None, "usedHeap": None, "totalHeap": None, "heapLimit": None, "deviceMemory": None})


def _environment(page: Any, screen: dict[str, Any], webgl: dict[str, Any], navigator: dict[str, Any]) -> dict[str, Any]:
    page_values = _page_eval(page, """() => ({timezone: (() => {try{return Intl.DateTimeFormat().resolvedOptions().timeZone || null;}catch(_){return null;}})(), locale: navigator.language || null, languages: Array.from(navigator.languages || []), displayServer: null, fontCount: document.fonts ? document.fonts.size : null})""", fallback={})
    psutil_memory = None
    try:
        import psutil  # type: ignore
        psutil_memory = psutil.virtual_memory().total
    except Exception:
        pass
    display_server = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    return {**system_metadata(), "kernel": platform.release(), "cpu_logical_cores": os.cpu_count(), "memory_bytes": psutil_memory,
        "disk_free_bytes": shutil.disk_usage(Path.cwd()).free, "timezone": page_values.get("timezone"), "locale": page_values.get("locale"),
        "languages": page_values.get("languages", []), "gpu_available": bool(webgl.get("available")), "gpu_vendor": webgl.get("vendor"),
        "gpu_renderer": webgl.get("renderer"), "swiftshader": "swiftshader" in str(webgl.get("renderer", "")).lower(),
        "angle": "angle" in (str(webgl.get("renderer", "")) + " " + str(webgl.get("version", ""))).lower(),
        "display_server": display_server, "dbus_available": bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")),
        "display_resolution": {"width": screen.get("width"), "height": screen.get("height")}, "font_count": page_values.get("fontCount"),
        "navigator_platform": navigator.get("platform")}


def _browser_info(playwright: Any, browser: Any, context: Any, settings: Settings) -> dict[str, Any]:
    browser_type = playwright.chromium
    executable = None
    try:
        executable = browser_type.executable_path
    except Exception:
        pass
    browser_version = None
    try:
        browser_version = browser.version
    except Exception:
        try:
            browser_version = context.browser.version if context.browser else None
        except Exception:
            pass
    browser_name = "chrome" if settings.channel.lower() in {"chrome", "chrome-beta", "chrome-dev", "chrome-canary"} else "chromium"
    return {"browser_name": browser_name, "browser_version": browser_version, "playwright_version": package_version("playwright"),
        "chrome_executable": executable if settings.channel == "chrome" else None, "chromium_executable": executable,
        "launch_arguments": ["--disable-dev-shm-usage"], "channel": settings.channel or "chromium", "headless": settings.headless,
        "pid": None, "user_data_directory": str(settings.profile) if settings.profile else None,
        "persistent_context": bool(settings.profile), "temporary_context": not bool(settings.profile), "incognito": not bool(settings.profile),
        "executable_path": executable, "url": settings.url}


def _profile_info(context: Any, settings: Settings) -> dict[str, Any]:
    return {"persistent": bool(settings.profile), "temporary": not bool(settings.profile), "incognito": not bool(settings.profile),
        "user_data_directory": str(settings.profile) if settings.profile else None, "context_options": {"headless": settings.headless, "channel": settings.channel or "chromium"}}


def _unknown_run(settings: Settings, run_id: str, error: str) -> dict[str, Any]:
    empty = {"status": "UNKNOWN", "error": error}
    return {"run_id": run_id, "status": "UNKNOWN", "error": error, "browser": {"playwright_version": package_version("playwright"), "headless": settings.headless},
        "profile": _profile_info(None, settings), "fonts": {"supported": False, "count": 0, "faces": []}, "speech": {"supported": False, "count": 0, "voices": []}, "navigator": empty, "window": empty, "screen": empty, "storage": {"cookies": {"count": 0}, "localStorageKeys": [], "sessionStorageKeys": [], "indexedDBNames": [], "cacheNames": []},
        "cookies": {"count": 0, "cookies": []}, "permissions": {"permissions": {}}, "extensions": _extensions(), "webgl": {"available": False}, "performance": empty, "memory": {"supported": False}, "environment": {"status": "UNKNOWN"}, "statistics": {}, "duration_ms": 0.0}


def _run_once(settings: Settings, run_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    browser = context = page = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            launch = {"headless": settings.headless, "args": ["--disable-dev-shm-usage"]}
            if settings.channel:
                launch["channel"] = settings.channel
            if settings.profile:
                context = playwright.chromium.launch_persistent_context(str(settings.profile), **launch)
                page = context.pages[0] if context.pages else context.new_page()
                browser = context.browser
            else:
                browser = playwright.chromium.launch(**launch)
                context = browser.new_context()
                page = context.new_page()
            browser_info = _browser_info(playwright, browser, context, settings)
            profile_info = _profile_info(context, settings)
            page.goto(settings.url, wait_until="load", timeout=settings.timeout_ms)
            navigator = _navigator(page)
            window = _window(page)
            screen = _screen(page)
            storage = _storage(page, context)
            cookies = storage.get("cookies", {"count": 0, "cookies": []})
            permissions = _permissions(page)
            extensions = _extensions()
            webgl = _webgl(page)
            performance = _performance(page)
            memory = _memory(page)
            fonts = _fonts(page)
            speech = _speech(page)
            environment = _environment(page, screen, webgl, navigator)
            stats = {"cookie_count": cookies.get("count", 0), "local_storage_keys": len(storage.get("localStorageKeys", [])), "session_storage_keys": len(storage.get("sessionStorageKeys", [])), "indexeddb_count": len(storage.get("indexedDBNames", [])), "cache_storage_count": len(storage.get("cacheNames", [])), "permission_count": len(permissions.get("permissions", {})), "plugin_count": len(navigator.get("plugins", [])), "mime_count": len(navigator.get("mimeTypes", [])), "font_count": fonts.get("count", 0), "extension_count": extensions.get("count", 0), "webgl_extensions": len(webgl.get("supportedExtensions", [])), "performance_entries": len(performance.get("resourceEntries", [])) if isinstance(performance.get("resourceEntries"), list) else 0, "resource_entries": performance.get("resourceTimingCount", 0)}
            return {"run_id": run_id, "status": "VALID", "error": None, "browser": browser_info, "profile": profile_info, "fonts": fonts, "speech": speech, "navigator": navigator, "window": window, "screen": screen, "storage": storage, "cookies": cookies, "permissions": permissions, "extensions": extensions, "webgl": webgl, "performance": performance, "memory": memory, "environment": environment, "statistics": stats, "duration_ms": round((time.perf_counter() - started) * 1000, 2)}
    except Exception as exc:
        return _unknown_run(settings, run_id, str(exc))
    finally:
        for handle in (page, context, browser):
            if handle is None:
                continue
            try:
                handle.close()
            except Exception:
                pass


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [run for run in runs if run.get("status") == "VALID"]
    fields = ["cookie_count", "local_storage_keys", "session_storage_keys", "indexeddb_count", "cache_storage_count", "permission_count", "plugin_count", "mime_count", "font_count", "extension_count", "webgl_extensions", "performance_entries", "resource_entries"]
    stats = {field: sum(int(run.get("statistics", {}).get(field, 0) or 0) for run in runs) for field in fields}
    stats.update({"run_count": len(runs), "valid_runs": len(valid), "unknown_runs": sum(run.get("status") == "UNKNOWN" for run in runs), "failed_runs": sum(run.get("status") == "FAILED" for run in runs), "average_duration_ms": round(statistics.mean([run.get("duration_ms", 0) for run in runs]), 2) if runs else 0})
    return stats


def _consistency(runs: list[dict[str, Any]]) -> dict[str, Any]:
    checks = []
    for run in runs:
        if run.get("status") != "VALID":
            continue
        window, screen = run.get("window", {}), run.get("screen", {})
        checks.extend([
            {"rule": "outer_width_gte_inner_width", "pass": window.get("outerWidth", 0) >= window.get("innerWidth", 0)},
            {"rule": "outer_height_gte_inner_height", "pass": window.get("outerHeight", 0) >= window.get("innerHeight", 0)},
            {"rule": "screen_width_gte_available_width", "pass": screen.get("width", 0) >= screen.get("availWidth", 0)},
            {"rule": "screen_height_gte_available_height", "pass": screen.get("height", 0) >= screen.get("availHeight", 0)},
        ])
    return {"checks": checks, "passed": sum(item["pass"] for item in checks), "failed": sum(not item["pass"] for item in checks), "valid": not any(not item["pass"] for item in checks)}


def _report(summary: dict[str, Any], runs: list[dict[str, Any]], hashes: dict[str, Any], output: Path) -> str:
    run_rows = []
    for run in runs:
        nav = run.get("navigator", {})
        browser = run.get("browser", {})
        run_rows.append(f"| {run.get('run_id')} | {run.get('status')} | {browser.get('browser_version', 'unknown')} | {browser.get('headless', 'unknown')} | {nav.get('webdriver', 'unknown')} | {run.get('duration_ms', '—')} ms |")
    lines = ["# Experiment 020 — Browser Session Profiler", "", "Read-only snapshot. No init script, stealth patch, storage write, permission grant, or extension content read was performed.", "", "## Browser Overview", "", "| Run | Status | Version | Headless | webdriver | Duration |", "|---|---|---|---|---|---:|"] + run_rows
    lines += ["", "## Browser Process", "", json.dumps(runs[0].get("browser", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## Navigator Profile", "", json.dumps(runs[0].get("navigator", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## Window Profile", "", json.dumps(runs[0].get("window", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## Screen Profile", "", json.dumps(runs[0].get("screen", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## Storage Summary", "", json.dumps(runs[0].get("storage", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## Cookies Summary", "", json.dumps(runs[0].get("cookies", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## Permissions", "", json.dumps(runs[0].get("permissions", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## Fonts", "", json.dumps(runs[0].get("fonts", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## Speech", "", json.dumps(runs[0].get("speech", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## Extensions", "", json.dumps(runs[0].get("extensions", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## WebGL", "", json.dumps(runs[0].get("webgl", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## Performance", "", json.dumps(runs[0].get("performance", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## Environment", "", json.dumps(runs[0].get("environment", {}) if runs else {}, ensure_ascii=False, indent=2), "", "## Fingerprint Summary", "", json.dumps(hashes, ensure_ascii=False, indent=2), "", "## Final Conclusion", "", f"Session result: **{summary.get('result')}**. Session score: **{summary.get('session_score')}%**. Profile consistency: **{summary.get('profile_consistency', {}).get('valid')}**.", "", "Optional APIs are reported as unavailable rather than emulated. Cookie and storage values are intentionally excluded.", ""]
    return "\n".join(lines)


def _parse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment 020: read-only browser session profiler")
    parser.add_argument("--url", default="about:blank")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=30_000)
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--channel", default="")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def _validate(output: Path, root: Path, hashes: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    required = ["browser.json", "profile.json", "fingerprint.json", "navigator.json", "window.json", "screen.json", "storage.json", "cookies.json", "permissions.json", "extensions.json", "webgl.json", "performance.json", "memory.json", "environment.json", "statistics.json", "summary.json", "session_profile.md"]
    missing = [name for name in required if not (output / name).is_file()]
    hash_valid = all(isinstance(value, str) and len(value) == 64 for value in hashes.get("hashes", {}).values())
    consistency = summary.get("profile_consistency", {})
    return {"artifact_completeness": not missing, "missing_artifacts": missing, "hashes_valid": hash_valid, "profile_consistency_valid": bool(consistency.get("valid", False)), "result_allowed": summary.get("result") in {"VALID", "PARTIAL", "UNKNOWN", "FAILED"}}


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    args = _parse().parse_args(argv)
    root = project_root()
    settings = Settings(root=root, reports_dir=(args.reports_dir or root / "reports" / "experiments").resolve(), url=args.url, runs=max(1, int(args.runs)), timeout_ms=max(1000, int(args.timeout)), headless=not bool(args.headful), channel=args.channel, profile=args.profile)
    experiment = Experiment.create(settings.reports_dir)
    output = experiment.directory / "session_profile"
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"experiment": "Experiment 020 — Browser Session Profiler", "experiment_id": experiment.experiment_id, "created_at": experiment.started_at, "url": settings.url, "runs": settings.runs, "headless": settings.headless, "channel": settings.channel or "chromium", "profile": str(settings.profile) if settings.profile else None, "analysis_only": True, "browser_modified": False, "environment": system_metadata(), "git": git_metadata(root)}
    write_json_exclusive(output / "metadata.json", metadata)
    runs = []
    for index in range(1, settings.runs + 1):
        run_id = f"run_{index:03d}"
        print(f"[exp_020] {run_id}: {settings.url}")
        runs.append(_run_once(settings, run_id))
    aggregate_stats = _aggregate(runs)
    valid_runs = [run for run in runs if run.get("status") == "VALID"]
    success = len(valid_runs) == len(runs) and bool(runs)
    partial = bool(valid_runs) and not success
    result = "VALID" if success else "PARTIAL" if partial else "UNKNOWN" if all(run.get("status") == "UNKNOWN" for run in runs) else "FAILED"
    consistency = _consistency(runs)
    snapshot_payloads = {"browser": {"experiment_id": experiment.experiment_id, "runs": [run.get("browser", {}) for run in runs]}, "profile": {"experiment_id": experiment.experiment_id, "runs": [{**run.get("profile", {}), "fonts": run.get("fonts", {}), "speech": run.get("speech", {})} for run in runs]}, "navigator": {"experiment_id": experiment.experiment_id, "runs": [run.get("navigator", {}) for run in runs]}, "window": {"experiment_id": experiment.experiment_id, "runs": [run.get("window", {}) for run in runs]}, "screen": {"experiment_id": experiment.experiment_id, "runs": [run.get("screen", {}) for run in runs]}, "storage": {"experiment_id": experiment.experiment_id, "runs": [run.get("storage", {}) for run in runs]}, "cookies": {"experiment_id": experiment.experiment_id, "runs": [run.get("cookies", {}) for run in runs]}, "permissions": {"experiment_id": experiment.experiment_id, "runs": [run.get("permissions", {}) for run in runs]}, "extensions": {"experiment_id": experiment.experiment_id, "runs": [run.get("extensions", {}) for run in runs]}, "webgl": {"experiment_id": experiment.experiment_id, "runs": [run.get("webgl", {}) for run in runs]}, "performance": {"experiment_id": experiment.experiment_id, "runs": [run.get("performance", {}) for run in runs]}, "memory": {"experiment_id": experiment.experiment_id, "runs": [run.get("memory", {}) for run in runs]}, "environment": {"experiment_id": experiment.experiment_id, "runs": [run.get("environment", {}) for run in runs]}, "statistics": {"experiment_id": experiment.experiment_id, "runs": [run.get("statistics", {}) for run in runs]}}
    for name, payload in snapshot_payloads.items():
        write_json_exclusive(output / f"{name}.json", payload)
    hashes = {"hashes": {domain: sha256_file(output / filename) for domain, filename in DOMAIN_ARTIFACTS.items()}, "algorithm": "sha256_file helper", "source_artifacts": DOMAIN_ARTIFACTS}
    write_json_exclusive(output / "fingerprint.json", {"experiment_id": experiment.experiment_id, **hashes})
    fingerprint_hash = sha256_file(output / "fingerprint.json")
    profile_hash = sha256_file(output / "profile.json")
    environment_hash = sha256_file(output / "environment.json")
    summary = {"experiment": "Experiment 020 — Browser Session Profiler", "experiment_id": experiment.experiment_id, "browser": runs[0].get("browser", {}).get("browser_name") if runs else None, "version": runs[0].get("browser", {}).get("browser_version") if runs else None, "headless": settings.headless, "persistent_profile": bool(settings.profile), "webdriver": runs[0].get("navigator", {}).get("webdriver") if runs else None, "gpu": runs[0].get("environment", {}).get("gpu_renderer") if runs else None, "timezone": runs[0].get("environment", {}).get("timezone") if runs else None, "locale": runs[0].get("environment", {}).get("locale") if runs else None, "cookies": aggregate_stats.get("cookie_count"), "storage": {"localStorage": aggregate_stats.get("local_storage_keys"), "sessionStorage": aggregate_stats.get("session_storage_keys")}, "permissions": aggregate_stats.get("permission_count"), "extensions": aggregate_stats.get("extension_count"), "fonts": runs[0].get("fonts", {}) if runs else {}, "speech": runs[0].get("speech", {}) if runs else {}, "webgl": runs[0].get("webgl", {}) if runs else {}, "fingerprint_hash": fingerprint_hash, "profile_hash": profile_hash, "environment_hash": environment_hash, "session_score": round(sum(1 for run in runs if run.get("status") == "VALID") / len(runs) * 100, 2) if runs else 0, "profile_consistency": consistency, "result": result, "statistics": aggregate_stats, "runs": [{"run_id": run.get("run_id"), "status": run.get("status"), "duration_ms": run.get("duration_ms"), "error": run.get("error")} for run in runs]}
    write_json_exclusive(output / "summary.json", summary)
    write_text_exclusive(output / "session_profile.md", _report(summary, runs, hashes, output))
    validation = _validate(output, root, hashes, summary)
    write_json_exclusive(output / "validation.json", validation)
    print("\nBROWSER SESSION PROFILER")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Result: {result}")
    print(f"Session score: {summary['session_score']}%")
    print(f"Hashes valid: {validation['hashes_valid']}")
    print(f"Artifacts: {relative_path(output, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
