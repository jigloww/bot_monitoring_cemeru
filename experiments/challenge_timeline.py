"""Experiment 019: passive Cloudflare challenge lifecycle timeline.

The recorder observes one ordinary Playwright page.  It does not click,
submit, solve, reload, or otherwise interact with challenges.  Page-side
observers retain metadata only; cookie values and storage contents are never
written to artifacts.  Each invocation is allocated through ``Experiment``
and all output files are write-once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    git_metadata,
    now_iso,
    package_version,
    project_root,
    relative_path,
    system_metadata,
    write_json_exclusive,
    write_text_exclusive,
)


CF_URL_MARKERS = ("cdn-cgi", "challenge", "turnstile", "captcha", "cloudflare", "cf")
CF_COOKIE_NAMES = {"cf_clearance", "__cf_bm", "cf_chl_2", "cf_chl_prog", "cf_chl_rc_ni"}
SENSITIVE_HEADERS = {"cookie", "set-cookie", "authorization", "proxy-authorization"}
CHALLENGE_TEXT = (
    "just a moment", "verify you are human", "checking your browser",
    "security check", "please wait", "tunggu sebentar",
)
INIT_SCRIPT = r"""
(() => {
  if (window.__challengeTimelineInstalled) return;
  window.__challengeTimelineInstalled = true;
  const limit = 2000;
  const state = window.__challengeTimelineState = {dom: [], storage: [], redirects: [], errors: []};
  const add = (bucket, event, details) => {
    try {
      if (state[bucket].length >= limit) return;
      state[bucket].push({event, details: details || {}, page_relative_time_ms: Number(performance.now().toFixed(2))});
    } catch (_) {}
  };
  const describe = (node) => {
    try {
      if (!node || node.nodeType !== 1) return {nodeType: node ? node.nodeType : null};
      const tag = String(node.tagName || '').toLowerCase();
      const attrs = {};
      for (const name of ['id', 'class', 'name', 'src', 'href', 'rel', 'http-equiv', 'content', 'type']) {
        if (node.getAttribute && node.hasAttribute(name)) attrs[name] = String(node.getAttribute(name)).slice(0, 300);
      }
      const lower = (tag + ' ' + JSON.stringify(attrs)).toLowerCase();
      return {
        tag, attributes: attrs,
        kind: tag === 'iframe' ? 'iframe' : tag === 'form' ? 'form' : tag === 'input' && attrs.type === 'hidden' ? 'hidden_input' :
          tag === 'script' ? 'script' : tag === 'style' ? 'style' : tag === 'dialog' ? 'dialog' :
          /overlay|spinner|modal|challenge|turnstile|captcha|cf-/.test(lower) ? 'challenge_container' : 'node'
      };
    } catch (_) { return {kind: 'node'}; }
  };
  try {
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of Array.from(mutation.addedNodes || [])) {
          const info = describe(node);
          add('dom', 'node_insertion', info);
          if (info.tag === 'meta' && String((info.attributes || {})['http-equiv'] || '').toLowerCase() === 'refresh') add('redirects', 'meta_refresh', info);
        }
        for (const node of Array.from(mutation.removedNodes || [])) add('dom', 'node_removal', describe(node));
      }
    });
    observer.observe(document, {subtree: true, childList: true, attributes: true, attributeFilter: ['id', 'class', 'src', 'style', 'hidden']});
  } catch (_) {}
  const redirect = (event, details) => add('redirects', event, details);
  try {
    for (const name of ['pushState', 'replaceState']) {
      const original = history[name];
      history[name] = function(...args) {
        redirect('history.' + name, {url: String(args[2] || location.href)});
        return original.apply(this, args);
      };
    }
  } catch (_) {}
  try {
    for (const name of ['assign', 'replace']) {
      const original = window.location[name];
      window.location[name] = function(...args) {
        redirect('location.' + name, {url: String(args[0] || '')});
        return original.apply(this, args);
      };
    }
  } catch (_) {}
  try {
    window.addEventListener('beforeunload', () => redirect('beforeunload', {url: location.href}));
    window.addEventListener('hashchange', () => redirect('hashchange', {url: location.href}));
    window.addEventListener('securitypolicyviolation', (event) => add('errors', 'csp_violation', {blockedURI: String(event.blockedURI || '').slice(0, 500), violatedDirective: String(event.violatedDirective || '')}));
    window.addEventListener('storage', (event) => add('storage', 'storage_event', {storageArea: event.storageArea ? 'storage' : null, key: event.key, oldValuePresent: event.oldValue !== null, newValuePresent: event.newValue !== null}));
  } catch (_) {}
  try {
    const originalSet = Storage.prototype.setItem;
    const originalRemove = Storage.prototype.removeItem;
    const originalClear = Storage.prototype.clear;
    const area = (owner) => { try { return owner === window.localStorage ? 'localStorage' : owner === window.sessionStorage ? 'sessionStorage' : 'storage'; } catch (_) { return 'storage'; } };
    Storage.prototype.setItem = function(key, value) { add('storage', 'storage.setItem', {storageArea: area(this), key: String(key).slice(0, 200), valueLength: String(value).length}); return originalSet.call(this, key, value); };
    Storage.prototype.removeItem = function(key) { add('storage', 'storage.removeItem', {storageArea: area(this), key: String(key).slice(0, 200)}); return originalRemove.call(this, key); };
    Storage.prototype.clear = function() { add('storage', 'storage.clear', {storageArea: area(this)}); return originalClear.call(this); };
  } catch (_) {}
  try {
    if (window.indexedDB && IDBFactory && IDBFactory.prototype.open) {
      const originalOpen = IDBFactory.prototype.open;
      IDBFactory.prototype.open = function(name, version) { add('storage', 'indexedDB.open', {name: String(name).slice(0, 200), version: version === undefined ? null : Number(version)}); return originalOpen.apply(this, arguments); };
    }
  } catch (_) {}
  try {
    if (window.caches && CacheStorage && CacheStorage.prototype.open) {
      const originalOpen = CacheStorage.prototype.open;
      CacheStorage.prototype.open = function(name) { add('storage', 'cacheStorage.open', {name: String(name).slice(0, 200)}); return originalOpen.apply(this, arguments); };
      const originalDelete = CacheStorage.prototype.delete;
      CacheStorage.prototype.delete = function(name) { add('storage', 'cacheStorage.delete', {name: String(name).slice(0, 200)}); return originalDelete.apply(this, arguments); };
    }
  } catch (_) {}
})();
"""


@dataclass(frozen=True)
class Settings:
    root: Path
    reports_dir: Path
    url: str
    runs: int
    timeout_ms: int
    wait_ms: int
    headless: bool


class Recorder:
    """Host-side monotonic timeline recorder."""

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.events: list[dict[str, Any]] = []

    def add(self, event: str, category: str = "lifecycle", severity: str = "info", **details: Any) -> dict[str, Any]:
        value = {
            "timestamp": now_iso(),
            "relative_time_ms": round((time.perf_counter() - self.started) * 1000, 2),
            "event": event,
            "category": category,
            "details": details,
            "severity": severity,
        }
        self.events.append(value)
        return value

    def ordered(self) -> list[dict[str, Any]]:
        ordered = sorted(enumerate(self.events), key=lambda item: (float(item[1].get("relative_time_ms", 0)), item[0]))
        result = []
        for sequence, (_, event) in enumerate(ordered, 1):
            result.append({"sequence": sequence, **event})
        return result


def _headers(value: Any) -> dict[str, str]:
    try:
        items = value.items()
    except Exception:
        return {}
    result = {}
    for key, item in items:
        name = str(key).lower()
        if name in SENSITIVE_HEADERS:
            result[name] = "<redacted>"
            continue
        result[name] = str(item)[:4000]
    return result


def _highlight_url(url: str) -> bool:
    lower = str(url).lower()
    return any(marker in lower for marker in CF_URL_MARKERS)


def _cookie_meta(cookie: dict[str, Any]) -> dict[str, Any]:
    value = str(cookie.get("value") or "")
    return {
        "name": cookie.get("name"),
        "domain": cookie.get("domain"),
        "path": cookie.get("path"),
        "secure": cookie.get("secure"),
        "httpOnly": cookie.get("httpOnly"),
        "sameSite": cookie.get("sameSite"),
        "expires": cookie.get("expires"),
        "value_present": bool(value),
        "value_length": len(value),
        "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None,
        "highlight": cookie.get("name") in CF_COOKIE_NAMES or str(cookie.get("name", "")).startswith("cf_chl_"),
    }


def _cookie_snapshot(context: Any) -> dict[str, dict[str, Any]]:
    try:
        values = context.cookies()
    except Exception:
        return {}
    return {
        f"{item.get('name')}|{item.get('domain')}|{item.get('path')}": _cookie_meta(item)
        for item in values if isinstance(item, dict) and item.get("name")
    }


def _cookie_changes(previous: dict[str, dict[str, Any]], current: dict[str, dict[str, Any]], recorder: Recorder) -> list[dict[str, Any]]:
    changes = []
    for key in sorted(set(previous) | set(current)):
        old, new = previous.get(key), current.get(key)
        if old == new:
            continue
        value = new or old or {}
        operation = "added" if old is None else "removed" if new is None else "updated"
        change = {"timestamp": now_iso(), "relative_time_ms": round((time.perf_counter() - recorder.started) * 1000, 2), "name": value.get("name"), "domain": value.get("domain"), "path": value.get("path"), "secure": value.get("secure"), "httpOnly": value.get("httpOnly"), "sameSite": value.get("sameSite"), "expires": value.get("expires"), "operation": operation, "value_present": value.get("value_present"), "value_length": value.get("value_length"), "value_sha256": value.get("value_sha256"), "highlight": value.get("highlight", False)}
        changes.append(change)
        recorder.add("Cookie Changed", category="cookies", severity="warning" if change["highlight"] else "info", **{k: v for k, v in change.items() if k not in {"timestamp", "relative_time_ms"}})
    return changes


def _signals(page: Any) -> dict[str, Any]:
    try:
        result = page.evaluate("""() => {
          const title = String(document.title || '');
          const body = String(document.body ? (document.body.innerText || '') : '').slice(0, 16000);
          const html = String(document.documentElement ? (document.documentElement.innerHTML || '') : '').slice(0, 40000);
          const lower = (title + '\\n' + body + '\\n' + html).toLowerCase();
          const challengeText = /just a moment|verify you are human|checking your browser|security check|please wait|tunggu sebentar/.test(lower);
          const challengeNode = !!document.querySelector('#challenge-running,#challenge-stage,#cf-challenge-running,[id*="challenge" i]');
          const turnstile = !!document.querySelector('.cf-turnstile,[data-sitekey],iframe[src*="challenges.cloudflare.com/turnstile"],[name="cf-turnstile-response"]');
          const captcha = !!document.querySelector('[id*="captcha" i],[class*="captcha" i],iframe[src*="recaptcha"],iframe[src*="hcaptcha"]');
          const quota = /\\b(quota|kuota)\\b/.test(lower) || /\\b(quota|kuota)\\b/.test(location.href.toLowerCase());
          return {title, url: location.href, challenge: challengeText || challengeNode, turnstile, captcha, quota};
        }""")
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        return {"error": str(exc), "challenge": None, "turnstile": None, "captcha": None, "quota": False}


def _page_metadata(page: Any, settings: Settings, browser_version: str | None) -> dict[str, Any]:
    try:
        values = page.evaluate("""() => ({
          user_agent: navigator.userAgent || null,
          platform: navigator.platform || null,
          language: navigator.language || null,
          languages: Array.from(navigator.languages || []),
          timezone: (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || null; } catch (_) { return null; } })(),
          viewport: {width: window.innerWidth || null, height: window.innerHeight || null},
          device_pixel_ratio: Number(window.devicePixelRatio || 1)
        })""")
    except Exception as exc:
        values = {"error": str(exc)}
    return {
        **values,
        "browser_version": browser_version,
        "playwright_version": package_version("playwright"),
        "headless": settings.headless,
        "headed": not settings.headless,
        "persistent_profile": False,
        "url_tested": settings.url,
        "stealth_modules_enabled": [],
    }


def _safe_relative(path: Path, root: Path) -> str:
    return relative_path(path, root)


def _take_screenshot(page: Any, screenshot_dir: Path, label: str, index: int, recorder: Recorder, root: Path) -> str | None:
    path = screenshot_dir / f"{index:03d}_{label}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
        relative = _safe_relative(path, root)
        recorder.add("Screenshot", category="screenshot", severity="info", label=label, path=relative)
        return relative
    except Exception as exc:
        recorder.add("Screenshot Failed", category="screenshot", severity="warning", label=label, error=str(exc))
        return None


def _network_duration(network: list[dict[str, Any]]) -> float | None:
    values = [item.get("duration_ms") for item in network if isinstance(item.get("duration_ms"), (int, float))]
    return round(max(values), 2) if values else None


def _redirect_count(redirects: list[dict[str, Any]]) -> int:
    """Count redirects without double-counting request/response callbacks."""
    http = [item for item in redirects if item.get("type") == "http_redirect"]
    client = [item for item in redirects if str(item.get("type", "")).startswith("history.") or item.get("type") in {"location.assign", "location.replace", "meta_refresh"}]
    if http:
        return len(http) + len(client)
    frame = [item for item in redirects if item.get("type") == "frame_navigation"]
    return len(frame) + len(client)


def _classify(status: int | None, timed_out: bool, challenge: bool, challenge_still: bool | None, browser_error: bool) -> str:
    if timed_out:
        return "TIMEOUT"
    if challenge and challenge_still is not False:
        return "CHALLENGE"
    if browser_error and status is None:
        return "FAILED"
    if status is None:
        return "UNKNOWN"
    if status >= 400:
        return "CHALLENGE" if challenge else "FAILED"
    if 200 <= status < 400:
        return "SUCCESS"
    return "UNKNOWN"


def _unknown_run(settings: Settings, run_id: str, reason: str, screenshot_dir: Path) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "result": "UNKNOWN",
        "reason": reason,
        "challenge_detected": False,
        "turnstile_detected": False,
        "homepage_reached": False,
        "quota_page_reached": False,
        "cf_clearance_acquired": False,
        "challenge_solved_observed": False,
        "challenge_duration_ms": None,
        "redirect_count": 0,
        "network_requests": 0,
        "dom_mutations": 0,
        "cookie_changes": 0,
        "storage_updates": 0,
        "console_errors": 0,
        "page_errors": 0,
        "final_url": None,
        "final_title": None,
        "http_status": None,
        "load_duration_ms": None,
        "network_duration_ms": None,
        "timeline": [],
        "network_events": [],
        "dom_events": [],
        "cookies_timeline": [],
        "storage_timeline": [],
        "redirects": [],
        "console": [],
        "page_errors_detail": [],
        "screenshots": [],
        "browser_information": {"playwright_version": package_version("playwright"), "headless": settings.headless},
    }


def _run_once(settings: Settings, run_id: str, output: Path) -> dict[str, Any]:
    recorder = Recorder()
    screenshot_dir = output / "screenshots" / run_id
    screenshot_dir.mkdir(parents=True, exist_ok=False)
    network: list[dict[str, Any]] = []
    dom_events: list[dict[str, Any]] = []
    cookies_timeline: list[dict[str, Any]] = []
    storage_timeline: list[dict[str, Any]] = []
    redirects: list[dict[str, Any]] = []
    console: list[dict[str, Any]] = []
    page_errors: list[dict[str, Any]] = []
    screenshots: list[str] = []
    request_map: dict[int, dict[str, Any]] = {}
    frame_urls: list[str] = []
    previous_cookies: dict[str, dict[str, Any]] = {}
    challenge_seen_at: float | None = None
    challenge_duration: float | None = None
    challenge_detected = False
    turnstile_detected = False
    timed_out = False
    browser_crashed = False
    navigation_error: str | None = None
    status: int | None = None
    main_headers: dict[str, str] = {}
    final_signals: dict[str, Any] = {}
    domcontentloaded_ms: float | None = None
    load_ms: float | None = None
    browser = context = page = None
    browser_information: dict[str, Any] = {"playwright_version": package_version("playwright"), "headless": settings.headless}
    final_cookie_snapshot: dict[str, dict[str, Any]] = {}
    screenshot_index = 0
    observed_homepage = False
    quota_seen = False

    def shot(label: str) -> None:
        nonlocal screenshot_index
        path = _take_screenshot(page, screenshot_dir, label, screenshot_index, recorder, settings.root) if page is not None else None
        screenshot_index += 1
        if path:
            screenshots.append(path)

    def on_request(request: Any) -> None:
        started = round((time.perf_counter() - recorder.started) * 1000, 2)
        try:
            req_headers = _headers(request.headers)
            redirected_from = request.redirected_from.url if request.redirected_from else None
            resource_type = request.resource_type
            is_navigation = request.is_navigation_request()
        except Exception:
            req_headers, redirected_from, resource_type, is_navigation = {}, None, None, False
        item = {
            "url": str(getattr(request, "url", "")), "method": str(getattr(request, "method", "GET")),
            "resourceType": resource_type, "status": None, "redirected": bool(redirected_from),
            "redirected_from": redirected_from, "duration_ms": None, "request_headers": req_headers,
            "response_headers": {}, "failed": False, "highlight": _highlight_url(str(getattr(request, "url", ""))),
            "started_relative_time_ms": started, "is_navigation": is_navigation,
        }
        request_map[id(request)] = item
        network.append(item)
        recorder.add("Request", category="network", severity="warning" if item["highlight"] else "info", url=item["url"], method=item["method"], resourceType=resource_type, highlighted=item["highlight"])
        if redirected_from:
            redirects.append({"type": "http_redirect_request", "url": item["url"], "from": redirected_from, "relative_time_ms": started, "highlight": item["highlight"]})
            recorder.add("HTTP Redirect", category="redirect", severity="warning", url=item["url"], from_url=redirected_from)

    def on_response(response: Any) -> None:
        nonlocal status, main_headers
        try:
            request = response.request
            item = request_map.get(id(request))
            headers = _headers(response.headers)
            is_navigation = request.is_navigation_request()
            resource_type = request.resource_type
        except Exception:
            request, item, headers, is_navigation, resource_type = None, None, {}, False, None
        if item is None:
            item = {"url": str(getattr(response, "url", "")), "method": "GET", "resourceType": resource_type, "request_headers": {}}
            network.append(item)
        item.update({"status": int(response.status), "response_headers": headers, "failed": int(response.status) >= 400, "duration_ms": round((time.perf_counter() - recorder.started) * 1000 - float(item.get("started_relative_time_ms", 0)), 2)})
        if is_navigation and resource_type == "document":
            status = int(response.status)
            main_headers = headers
        if 300 <= int(response.status) < 400:
            redirect = {"type": "http_redirect", "url": str(response.url), "status": int(response.status), "location": headers.get("location"), "relative_time_ms": round((time.perf_counter() - recorder.started) * 1000, 2), "highlight": _highlight_url(str(response.url))}
            redirects.append(redirect)
            recorder.add("HTTP Redirect", category="redirect", severity="warning", **redirect)
        if int(response.status) >= 400:
            page_errors.append({"kind": "resource_loading_failure", "url": str(response.url), "status": int(response.status)})
            recorder.add("Response Failure", category="network", severity="error", url=str(response.url), status=int(response.status))

    def on_request_failed(request: Any) -> None:
        item = request_map.get(id(request))
        if item is not None:
            item["failed"] = True
            item["failure"] = str(getattr(request, "failure", None))
            item["duration_ms"] = round((time.perf_counter() - recorder.started) * 1000 - float(item.get("started_relative_time_ms", 0)), 2)
        detail = {"kind": "network_failure", "url": str(getattr(request, "url", "")), "failure": str(getattr(request, "failure", None))}
        page_errors.append(detail)
        recorder.add("Network Failure", category="errors", severity="error", **detail)

    def on_console(message: Any) -> None:
        detail = {"type": str(getattr(message, "type", "log")), "text": str(getattr(message, "text", ""))[:4000], "relative_time_ms": round((time.perf_counter() - recorder.started) * 1000, 2)}
        console.append(detail)
        recorder.add("Console " + detail["type"], category="console", severity="error" if detail["type"] == "error" else "info", text=detail["text"])

    def on_page_error(error: Any) -> None:
        detail = {"kind": "javascript_runtime_error", "message": str(error), "relative_time_ms": round((time.perf_counter() - recorder.started) * 1000, 2)}
        page_errors.append(detail)
        recorder.add("Page Error", category="errors", severity="error", message=detail["message"])

    def on_frame(frame: Any) -> None:
        if page is None or frame != page.main_frame:
            return
        url = str(frame.url)
        frame_urls.append(url)
        recorder.add("Frame Navigated", category="navigation", severity="info", url=url)
        if len(frame_urls) > 1:
            redirects.append({"type": "frame_navigation", "url": url, "from": frame_urls[-2], "relative_time_ms": round((time.perf_counter() - recorder.started) * 1000, 2), "highlight": _highlight_url(url)})

    def on_domcontentloaded() -> None:
        nonlocal domcontentloaded_ms
        domcontentloaded_ms = round((time.perf_counter() - recorder.started) * 1000, 2)
        recorder.add("DOMContentLoaded", category="navigation")

    def on_load() -> None:
        nonlocal load_ms
        load_ms = round((time.perf_counter() - recorder.started) * 1000, 2)
        recorder.add("Load", category="navigation")

    def on_crash() -> None:
        nonlocal browser_crashed
        browser_crashed = True
        recorder.add("Browser Crash", category="errors", severity="error")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            recorder.add("Browser Launch", category="lifecycle")
            browser = playwright.chromium.launch(headless=settings.headless, args=["--disable-dev-shm-usage"])
            recorder.add("Context Created", category="lifecycle")
            context = browser.new_context()
            page = context.new_page()
            recorder.add("Page Created", category="lifecycle")
            try:
                browser_information = _page_metadata(page, settings, str(getattr(browser, "version", None) or "unknown"))
            except Exception:
                browser_information = {"playwright_version": package_version("playwright"), "headless": settings.headless}
            try:
                page.add_init_script(INIT_SCRIPT)
            except Exception as exc:
                recorder.add("Observer Install Warning", category="lifecycle", severity="warning", error=str(exc))
            for name, callback in (("request", on_request), ("response", on_response), ("requestfailed", on_request_failed), ("console", on_console), ("pageerror", on_page_error), ("framenavigated", on_frame), ("domcontentloaded", on_domcontentloaded), ("load", on_load), ("crash", on_crash)):
                try:
                    page.on(name, callback)
                except Exception as exc:
                    recorder.add("Observer Install Warning", category="lifecycle", severity="warning", event_name=name, error=str(exc))
            try:
                shot("start")
            except Exception:
                pass
            recorder.add("Navigation Start", category="navigation", url=settings.url)
            previous_cookies = _cookie_snapshot(context)
            try:
                response = page.goto(settings.url, wait_until="domcontentloaded", timeout=settings.timeout_ms)
                if response is not None and status is None:
                    status = int(response.status)
                    main_headers = _headers(response.headers)
                if redirects:
                    shot("redirect")
            except Exception as exc:
                navigation_error = str(exc)
                timed_out = "timeout" in navigation_error.lower()
                recorder.add("Timeout" if timed_out else "Navigation Error", category="navigation", severity="error" if timed_out else "warning", error=navigation_error)
                if timed_out:
                    shot("timeout")
            try:
                page.wait_for_load_state("networkidle", timeout=min(settings.timeout_ms, max(1000, settings.wait_ms)))
                recorder.add("Network Idle", category="navigation")
            except Exception:
                recorder.add("Network Idle Timeout", category="navigation", severity="info")
            observation_end = time.perf_counter() + settings.wait_ms / 1000
            observed_challenge_screenshot = False
            observed_turnstile_screenshot = False
            while time.perf_counter() <= observation_end:
                final_signals = _signals(page)
                now_ms = round((time.perf_counter() - recorder.started) * 1000, 2)
                if final_signals.get("challenge") is True and not challenge_detected:
                    challenge_detected = True
                    challenge_seen_at = now_ms
                    recorder.add("Challenge Detected", category="challenge", severity="warning", url=final_signals.get("url"), title=final_signals.get("title"))
                    if not observed_challenge_screenshot:
                        shot("challenge")
                        observed_challenge_screenshot = True
                if final_signals.get("turnstile") is True:
                    first_turnstile = not turnstile_detected
                    turnstile_detected = True
                    if first_turnstile:
                        recorder.add("Turnstile Detected", category="challenge", severity="warning", url=final_signals.get("url"))
                    if not observed_turnstile_screenshot:
                        shot("turnstile")
                        observed_turnstile_screenshot = True
                if final_signals.get("quota") is True:
                    if not quota_seen:
                        recorder.add("Quota Page Observed", category="navigation", severity="info", url=final_signals.get("url"))
                    quota_seen = True
                current_cookies = _cookie_snapshot(context)
                changes = _cookie_changes(previous_cookies, current_cookies, recorder)
                cookies_timeline.extend(changes)
                previous_cookies = current_cookies
                if time.perf_counter() >= observation_end:
                    break
                try:
                    page.wait_for_timeout(min(250, max(1, int((observation_end - time.perf_counter()) * 1000))))
                except Exception:
                    break
            final_signals = _signals(page)
            if redirects and not any(Path(path).name.endswith("_redirect.png") for path in screenshots):
                shot("redirect")
            if challenge_detected and challenge_seen_at is not None:
                challenge_duration = round(max(0.0, (time.perf_counter() - recorder.started) * 1000 - challenge_seen_at), 2)
            if challenge_detected and not final_signals.get("challenge"):
                recorder.add("Challenge No Longer Present", category="challenge", severity="info", duration_ms=challenge_duration)
            target_host = urlparse(settings.url).hostname
            final_host = urlparse(str(final_signals.get("url", ""))).hostname
            target_path = urlparse(settings.url).path.rstrip("/")
            final_path = urlparse(str(final_signals.get("url", ""))).path.rstrip("/")
            if status is not None and 200 <= status < 400 and not final_signals.get("challenge") and target_host and target_host == final_host and target_path == final_path:
                observed_homepage = True
                recorder.add("Homepage Reached", category="navigation", severity="info", url=final_signals.get("url"))
                shot("homepage")
            try:
                state = page.evaluate("() => window.__challengeTimelineState || {dom:[], storage:[], redirects:[], errors:[]}")
            except Exception as exc:
                state = {"dom": [], "storage": [], "redirects": [], "errors": [], "error": str(exc)}
            for item in state.get("dom", []) if isinstance(state, dict) else []:
                detail = {"run_id": run_id, "timestamp": now_iso(), "relative_time_ms": round((time.perf_counter() - recorder.started) * 1000, 2), "category": "dom", "severity": "info", **item}
                dom_events.append(detail)
                recorder.add("DOM Mutation", category="dom", severity="warning" if (item.get("details") or {}).get("kind") == "challenge_container" else "info", **item)
            for item in state.get("storage", []) if isinstance(state, dict) else []:
                detail = {"run_id": run_id, "timestamp": now_iso(), "relative_time_ms": round((time.perf_counter() - recorder.started) * 1000, 2), "category": "storage", "severity": "info", **item}
                storage_timeline.append(detail)
                recorder.add("Storage Updated", category="storage", severity="info", **item)
            for item in state.get("redirects", []) if isinstance(state, dict) else []:
                detail = {"run_id": run_id, "timestamp": now_iso(), "relative_time_ms": round((time.perf_counter() - recorder.started) * 1000, 2), "category": "redirect", "severity": "info", **item}
                redirects.append(detail)
                recorder.add("Client Redirect", category="redirect", severity="info", **item)
            for item in state.get("errors", []) if isinstance(state, dict) else []:
                detail = {"run_id": run_id, **item}
                page_errors.append(detail)
                recorder.add("Page Error", category="errors", severity="warning", **item)
            recorder.add("Navigation End", category="navigation", url=final_signals.get("url", page.url), status=status)
    except Exception as exc:
        navigation_error = navigation_error or str(exc)
        page_errors.append({"kind": "browser_error", "message": str(exc)})
        recorder.add("Browser Error", category="errors", severity="error", error=str(exc))
    finally:
        if context is not None:
            try:
                final_cookie_snapshot = _cookie_snapshot(context)
                cookies_timeline.extend(_cookie_changes(previous_cookies, final_cookie_snapshot, recorder))
            except Exception:
                pass
        for handle in (page, context, browser):
            if handle is None:
                continue
            try:
                handle.close()
            except Exception:
                pass
        recorder.add("Browser Closed", category="lifecycle")

    ordered = recorder.ordered()
    # Any page-side events are appended at retrieval time above.  Sorting here
    # guarantees the persisted timeline is chronological even if Playwright
    # delivered callbacks in the same clock tick.
    network.sort(key=lambda item: float(item.get("started_relative_time_ms", 0)))
    redirects.sort(key=lambda item: float(item.get("relative_time_ms", 0)))
    cookies_timeline.sort(key=lambda item: float(item.get("relative_time_ms", 0)))
    storage_timeline.sort(key=lambda item: float(item.get("page_relative_time_ms", item.get("relative_time_ms", 0))))
    dom_events.sort(key=lambda item: float(item.get("page_relative_time_ms", item.get("relative_time_ms", 0))))
    if isinstance(final_signals, dict) and ("challenge" in final_signals or "turnstile" in final_signals):
        challenge_still = bool(final_signals.get("challenge") or final_signals.get("turnstile"))
    else:
        challenge_still = None
    # A missing Playwright package, missing executable, or launch failure has
    # no browser observation and is therefore UNKNOWN.  A crash after a
    # browser object was created remains FAILED.
    browser_error_observed = browser_crashed or bool(browser is not None and page_errors and status is None)
    challenge_observed = challenge_detected or turnstile_detected
    result = _classify(status, timed_out, challenge_observed, challenge_still, browser_error_observed)
    cf_clearance = any(item.get("name") == "cf_clearance" and item.get("value_present") for item in final_cookie_snapshot.values())
    quota_reached = quota_seen or bool(final_signals.get("quota"))
    return {
        "run_id": run_id,
        "result": result,
        "reason": navigation_error,
        "challenge_detected": challenge_detected,
        "turnstile_detected": turnstile_detected,
        "homepage_reached": bool(status is not None and 200 <= status < 400 and observed_homepage),
        "quota_page_reached": quota_reached,
        "cf_clearance_acquired": cf_clearance,
        "challenge_solved_observed": bool(challenge_observed and challenge_still is False and status is not None and status < 400),
        "challenge_duration_ms": challenge_duration,
        "redirect_count": _redirect_count(redirects),
        "network_requests": len(network),
        "dom_mutations": len(dom_events),
        "cookie_changes": len(cookies_timeline),
        "storage_updates": len(storage_timeline),
        "console_errors": len([item for item in console if item.get("type") == "error"]),
        "page_errors": len(page_errors),
        "final_url": final_signals.get("url") if isinstance(final_signals, dict) else None,
        "final_title": final_signals.get("title") if isinstance(final_signals, dict) else None,
        "http_status": status,
        "load_duration_ms": load_ms,
        "network_duration_ms": _network_duration(network),
        "navigation_error": navigation_error,
        "browser_crashed": browser_crashed,
        "timed_out": timed_out,
        "timeline": ordered,
        "network_events": network,
        "dom_events": dom_events,
        "cookies_timeline": cookies_timeline,
        "storage_timeline": storage_timeline,
        "redirects": redirects,
        "console": console,
        "page_errors_detail": page_errors,
        "screenshots": screenshots,
        "browser_information": browser_information,
    }


def _aggregate_statistics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    def total(name: str) -> int:
        return sum(int(item.get(name, 0) or 0) for item in runs)
    challenge_durations = [float(item["challenge_duration_ms"]) for item in runs if isinstance(item.get("challenge_duration_ms"), (int, float))]
    loads = [float(item["load_duration_ms"]) for item in runs if isinstance(item.get("load_duration_ms"), (int, float))]
    return {
        "run_count": len(runs),
        "total_requests": total("network_requests"),
        "successful_requests": sum(1 for run in runs for item in run.get("network_events", []) if isinstance(item.get("status"), int) and 200 <= item["status"] < 400),
        "failed_requests": sum(1 for run in runs for item in run.get("network_events", []) if item.get("failed")),
        "redirect_count": total("redirect_count"),
        "cookie_changes": total("cookie_changes"),
        "dom_mutations": total("dom_mutations"),
        "storage_updates": total("storage_updates"),
        "console_messages": sum(len(run.get("console", [])) for run in runs),
        "console_errors": total("console_errors"),
        "page_errors": total("page_errors"),
        "challenge_duration_ms": round(statistics.mean(challenge_durations), 2) if challenge_durations else None,
        "load_duration_ms": round(statistics.mean(loads), 2) if loads else None,
        "network_duration_ms": round(statistics.mean([float(item["network_duration_ms"]) for item in runs if isinstance(item.get("network_duration_ms"), (int, float))]), 2) if any(isinstance(item.get("network_duration_ms"), (int, float)) for item in runs) else None,
        "challenge_detected_count": sum(bool(item.get("challenge_detected")) for item in runs),
        "turnstile_detected_count": sum(bool(item.get("turnstile_detected")) for item in runs),
        "homepage_reached_count": sum(bool(item.get("homepage_reached")) for item in runs),
        "cf_clearance_acquired_count": sum(bool(item.get("cf_clearance_acquired")) for item in runs),
        "result_counts": {value: sum(1 for item in runs if item.get("result") == value) for value in ("SUCCESS", "CHALLENGE", "TIMEOUT", "FAILED", "UNKNOWN")},
    }


def _summary(runs: list[dict[str, Any]], experiment_id: str, settings: Settings) -> dict[str, Any]:
    stats = _aggregate_statistics(runs)
    final = next((run for run in reversed(runs) if run.get("final_url")), runs[-1] if runs else {})
    overall_result = "UNKNOWN"
    if any(run.get("result") == "TIMEOUT" for run in runs):
        overall_result = "TIMEOUT"
    elif any(run.get("result") == "CHALLENGE" for run in runs):
        overall_result = "CHALLENGE"
    elif any(run.get("result") == "SUCCESS" for run in runs):
        overall_result = "SUCCESS"
    elif any(run.get("result") == "FAILED" for run in runs):
        overall_result = "FAILED"
    return {
        "experiment": "Experiment 019 — Challenge Timeline Analyzer",
        "experiment_id": experiment_id,
        "created_at": now_iso(),
        "url": settings.url,
        "runs": len(runs),
        "challenge_detected": any(bool(run.get("challenge_detected")) for run in runs),
        "turnstile_detected": any(bool(run.get("turnstile_detected")) for run in runs),
        "homepage_reached": any(bool(run.get("homepage_reached")) for run in runs),
        "quota_page_reached": any(bool(run.get("quota_page_reached")) for run in runs),
        "cf_clearance_acquired": any(bool(run.get("cf_clearance_acquired")) for run in runs),
        "challenge_duration_ms": stats["challenge_duration_ms"],
        "redirect_count": stats["redirect_count"],
        "network_requests": stats["total_requests"],
        "dom_mutations": stats["dom_mutations"],
        "cookie_changes": stats["cookie_changes"],
        "storage_updates": stats["storage_updates"],
        "console_errors": stats["console_errors"],
        "page_errors": stats["page_errors"],
        "final_url": final.get("final_url"),
        "final_title": final.get("final_title"),
        "result": overall_result,
        "statistics": stats,
        "analysis_only": True,
        "challenge_interaction": False,
        "sensitive_values_persisted": False,
    }


def _report(summary: dict[str, Any], runs: list[dict[str, Any]], output: Path) -> str:
    lines = [
        "# Experiment 019 — Challenge Timeline Analyzer", "",
        "## Executive Summary", "",
        "Passive observation only. No challenge, CAPTCHA, Turnstile, booking, or form interaction was performed.", "",
        f"- Result: **{summary['result']}**", f"- URL: `{summary['url']}`", f"- Runs: `{summary['runs']}`", "",
        "## Browser Information", "",
        "| Run | Playwright | Browser | Headless | URL |", "|---|---|---|---|---|",
    ]
    for run in runs:
        info = run.get("browser_information", {})
        lines.append(f"| {run['run_id']} | {info.get('playwright_version', 'unknown')} | {info.get('browser_version', 'unknown')} | {info.get('headless', 'unknown')} | {summary['url']} |")
    lines.extend(["", "## Navigation Timeline", ""])
    for run in runs:
        lines.extend([f"### {run['run_id']}", "", "| Time ms | Event | Category | Severity | Details |", "|---:|---|---|---|---|"])
        events = run.get("timeline", [])
        if not events:
            lines.append("| — | No event observed | — | — | Environment unavailable |")
        for event in events:
            details = json.dumps(event.get("details", {}), ensure_ascii=False, separators=(",", ":")).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {event.get('relative_time_ms', '—')} | {event.get('event', '—')} | {event.get('category', '—')} | {event.get('severity', '—')} | {details} |")
    stats = summary["statistics"]
    lines.extend(["", "## Network Summary", "", f"Requests: **{stats['total_requests']}**, successful: **{stats['successful_requests']}**, failed: **{stats['failed_requests']}**, network duration: **{stats['network_duration_ms'] if stats['network_duration_ms'] is not None else 'N/A'} ms**.", "", "## Redirect Summary", "", f"Redirect events: **{stats['redirect_count']}**.", "", "## Cookie Timeline", "", f"Cookie changes: **{stats['cookie_changes']}**. `cf_clearance` acquired: **{summary['cf_clearance_acquired']}**.", "", "## DOM Mutation Summary", "", f"DOM mutations: **{stats['dom_mutations']}**.", "", "## Storage Summary", "", f"Storage metadata updates: **{stats['storage_updates']}**. Values are not persisted.", "", "## Console Messages", "", f"Console messages: **{stats['console_messages']}**, errors: **{stats['console_errors']}**.", "", "## Page Errors", "", f"Page and network errors: **{stats['page_errors']}**.", "", "## Screenshots", ""])
    for run in runs:
        links = []
        for path in run.get("screenshots", []):
            try:
                root = output.parents[3]
                href = Path(os.path.relpath(root / path, output)).as_posix()
            except Exception:
                href = str(path).replace("\\", "/")
            links.append(f"[{Path(path).name}]({href})")
        lines.append(f"- `{run['run_id']}`: " + (", ".join(links) if links else "none observed"))
    lines.extend(["", "## Final Conclusion", "", f"The observed outcome is **{summary['result']}**. Challenge detected: **{summary['challenge_detected']}**; Turnstile detected: **{summary['turnstile_detected']}**; homepage reached: **{summary['homepage_reached']}**. These observations describe this run and environment only; they are not evidence of bypass capability.", "", f"Artifacts: `{output}`", ""])
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment 019: passive challenge lifecycle analyzer")
    parser.add_argument("--url", default=None)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=60_000)
    parser.add_argument("--wait", type=int, default=5_000, help="Passive observation window after navigation (ms)")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--headful", action="store_true", help="Run headed instead of headless")
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    root = project_root()
    try:
        from bot.constants import BASE_URL
    except Exception:
        BASE_URL = "https://bromotenggersemeru.id/"
    return Settings(
        root=root,
        reports_dir=(args.reports_dir or root / "reports" / "experiments").resolve(),
        url=args.url or BASE_URL,
        runs=max(1, int(args.runs)),
        timeout_ms=max(1000, int(args.timeout)),
        wait_ms=max(0, int(args.wait)),
        headless=not bool(args.headful),
    )


def _validate(output: Path, runs: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    required = ["timeline.json", "network_events.json", "dom_events.json", "cookies_timeline.json", "storage_timeline.json", "redirects.json", "console.json", "page_errors.json", "statistics.json", "summary.json", "challenge_report.md"]
    missing = [name for name in required if not (output / name).is_file()]
    timeline_ordered = True
    for run in runs:
        values = [float(item.get("relative_time_ms", 0)) for item in run.get("timeline", [])]
        if values != sorted(values):
            timeline_ordered = False
    screenshot_paths = [path for run in runs for path in run.get("screenshots", []) if isinstance(path, str)]
    screenshots_valid = all((root / path).is_file() for path in screenshot_paths if not Path(path).is_absolute()) if screenshot_paths else None
    return {"artifact_completeness": not missing, "missing_artifacts": missing, "timeline_ordered": timeline_ordered, "screenshots_observed": bool(screenshot_paths), "screenshots_valid": screenshots_valid}


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    args = _parser().parse_args(argv)
    settings = _settings(args)
    experiment = Experiment.create(settings.reports_dir)
    output = experiment.directory / "challenge_timeline"
    output.mkdir(parents=True, exist_ok=False)
    (output / "screenshots").mkdir(parents=True, exist_ok=False)
    metadata = {"experiment": "Experiment 019 — Challenge Timeline Analyzer", "experiment_id": experiment.experiment_id, "created_at": experiment.started_at, "url": settings.url, "runs": settings.runs, "timeout_ms": settings.timeout_ms, "wait_ms": settings.wait_ms, "headless": settings.headless, "analysis_only": True, "challenge_interaction": False, "fingerprint_modified": False, "environment": system_metadata(), "git": git_metadata(settings.root), "playwright_version": package_version("playwright")}
    write_json_exclusive(output / "metadata.json", metadata)
    runs: list[dict[str, Any]] = []
    for index in range(1, settings.runs + 1):
        run_id = f"run_{index:03d}"
        print(f"[exp_019] {run_id}: {settings.url}")
        try:
            runs.append(_run_once(settings, run_id, output))
        except Exception as exc:
            runs.append(_unknown_run(settings, run_id, str(exc), output / "screenshots" / run_id))
    summary = _summary(runs, experiment.experiment_id, settings)
    timeline = {"experiment_id": experiment.experiment_id, "runs": [{"run_id": run["run_id"], "events": run.get("timeline", [])} for run in runs]}
    network = {"experiment_id": experiment.experiment_id, "runs": [{"run_id": run["run_id"], "events": run.get("network_events", [])} for run in runs]}
    dom = {"experiment_id": experiment.experiment_id, "runs": [{"run_id": run["run_id"], "events": run.get("dom_events", [])} for run in runs]}
    cookies = {"experiment_id": experiment.experiment_id, "runs": [{"run_id": run["run_id"], "events": run.get("cookies_timeline", [])} for run in runs]}
    storage = {"experiment_id": experiment.experiment_id, "runs": [{"run_id": run["run_id"], "events": run.get("storage_timeline", [])} for run in runs]}
    redirects = {"experiment_id": experiment.experiment_id, "runs": [{"run_id": run["run_id"], "events": run.get("redirects", [])} for run in runs]}
    console = {"experiment_id": experiment.experiment_id, "runs": [{"run_id": run["run_id"], "messages": run.get("console", [])} for run in runs]}
    errors = {"experiment_id": experiment.experiment_id, "runs": [{"run_id": run["run_id"], "errors": run.get("page_errors_detail", [])} for run in runs]}
    write_json_exclusive(output / "timeline.json", timeline)
    write_json_exclusive(output / "network_events.json", network)
    write_json_exclusive(output / "dom_events.json", dom)
    write_json_exclusive(output / "cookies_timeline.json", cookies)
    write_json_exclusive(output / "storage_timeline.json", storage)
    write_json_exclusive(output / "redirects.json", redirects)
    write_json_exclusive(output / "console.json", console)
    write_json_exclusive(output / "page_errors.json", errors)
    write_json_exclusive(output / "statistics.json", summary["statistics"])
    write_json_exclusive(output / "summary.json", summary)
    write_text_exclusive(output / "challenge_report.md", _report(summary, runs, output))
    validation = _validate(output, runs, settings.root)
    write_json_exclusive(output / "validation.json", validation)
    print("\nCHALLENGE TIMELINE ANALYZER")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Result: {summary['result']}")
    print(f"Challenge detected: {summary['challenge_detected']}")
    print(f"Timeline ordered: {validation['timeline_ordered']}")
    print(f"Artifacts: {relative_path(output, settings.root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
