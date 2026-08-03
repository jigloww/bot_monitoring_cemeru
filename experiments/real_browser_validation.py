"""Experiment 018: observational real-browser validation.

This experiment compares browser launch modes against a target using only
observable navigation behaviour.  It never clicks a challenge, submits a
CAPTCHA/Turnstile token, or changes fingerprint values.  Every execution is
allocated a new experiment directory and all artifacts are write-once.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
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


MODES = ("plain", "playwright_stealth", "local_stealth", "chrome_cdp", "chrome_manual_profile")
MODE_LABELS = {
    "plain": "Plain Playwright",
    "playwright_stealth": "playwright-stealth",
    "local_stealth": "Local Stealth Framework",
    "chrome_cdp": "Chrome via CDP",
    "chrome_manual_profile": "Chrome Manual Profile",
}
CHALLENGE_TEXT = (
    "just a moment", "verify you are human", "checking your browser",
    "security check", "tunggu sebentar", "please wait", "performing security verification",
)
CF_COOKIE_NAMES = {"cf_clearance", "__cf_bm", "cf_chl_2", "cf_chl_prog", "cf_chl_rc_ni"}
SENSITIVE_HEADERS = {"set-cookie", "cookie", "authorization", "proxy-authorization"}
CF_HEADER_NAMES = {
    "cf-ray", "cf-cache-status", "cf-mitigated", "cf-chl-out", "cf-chl-bypass",
    "server", "location", "content-type", "content-encoding", "alt-svc",
}


@dataclass(frozen=True)
class Settings:
    root: Path
    reports_root: Path
    url: str
    runs: int
    timeout_ms: int
    wait_ms: int
    headless: bool
    cdp_url: str | None
    manual_profile: Path | None
    quota_endpoint: str | None
    quota_year_month: str | None
    check_quota: bool
    modes: tuple[str, ...]


def _safe(value: Any, default: Any = None) -> Any:
    try:
        return value if value is not None else default
    except Exception:
        return default


def _event(timeline: list[dict[str, Any]], started: float, name: str, **details: Any) -> None:
    timeline.append({
        "sequence": len(timeline) + 1,
        "event": name,
        "timestamp": now_iso(),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        **details,
    })


def _sanitize_headers(headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        items = headers.items()
    except Exception:
        return result
    for key, value in items:
        name = str(key).lower()
        if name in SENSITIVE_HEADERS:
            continue
        result[name] = str(value)
    return result


def _cloudflare_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key in CF_HEADER_NAMES or key.startswith("cf-")}


def _page_signals(page: Any) -> dict[str, Any]:
    """Read passive DOM signals; no element is clicked or submitted."""
    try:
        value = page.evaluate("""() => {
          const title = String(document.title || '');
          const body = String(document.body ? (document.body.innerText || '') : '').slice(0, 16000);
          const html = String(document.documentElement ? (document.documentElement.innerHTML || '') : '').slice(0, 40000);
          const lower = (title + '\\n' + body + '\\n' + html).toLowerCase();
          const challengeText = /just a moment|verify you are human|checking your browser|security check|tunggu sebentar|please wait|performing security verification/.test(lower);
          const challengeNode = !!document.querySelector('#challenge-running,#challenge-stage,#cf-challenge-running,[id*="challenge" i]');
          const turnstile = !!document.querySelector('.cf-turnstile,[data-sitekey],iframe[src*="challenges.cloudflare.com/turnstile"],[name="cf-turnstile-response"]');
          const captcha = !!document.querySelector('[id*="captcha" i],[class*="captcha" i],iframe[src*="recaptcha"],iframe[src*="hcaptcha"]');
          return {title, url: location.href, challenge: challengeText || challengeNode, turnstile, captcha};
        }""")
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        return {"challenge": None, "turnstile": None, "captcha": None, "error": str(exc)}


def _paint_entries(page: Any) -> dict[str, float | None]:
    try:
        value = page.evaluate("""() => {
          const entries = performance.getEntriesByType('paint');
          const result = {first_paint_ms: null, first_contentful_paint_ms: null};
          for (const entry of entries) {
            if (entry.name === 'first-paint') result.first_paint_ms = Number(entry.startTime);
            if (entry.name === 'first-contentful-paint') result.first_contentful_paint_ms = Number(entry.startTime);
          }
          return result;
        }""")
        return value if isinstance(value, dict) else {"first_paint_ms": None, "first_contentful_paint_ms": None}
    except Exception:
        return {"first_paint_ms": None, "first_contentful_paint_ms": None}


def _browser_metadata(page: Any, browser_version: str | None, playwright_version: str) -> dict[str, Any]:
    try:
        value = page.evaluate("""() => ({
          user_agent: navigator.userAgent || null,
          language: navigator.language || null,
          languages: Array.from(navigator.languages || []),
          timezone: (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || null; } catch (_) { return null; } })(),
          viewport: {width: window.innerWidth || null, height: window.innerHeight || null},
          device_pixel_ratio: Number(window.devicePixelRatio || 1),
          platform: navigator.platform || null,
          vendor: navigator.vendor || null
        })""")
        metadata = value if isinstance(value, dict) else {}
    except Exception as exc:
        metadata = {"error": str(exc)}
    metadata.update({
        "browser_version": browser_version,
        "playwright_version": playwright_version,
    })
    return metadata


def _cookie_snapshot(context: Any) -> dict[str, Any]:
    try:
        values = context.cookies()
    except Exception as exc:
        return {"count": 0, "names": [], "cf_clearance": False, "__cf_bm": False, "cf_cookie_names": [], "error": str(exc)}
    names = [str(item.get("name")) for item in values if isinstance(item, dict)]
    cf_names = sorted(name for name in names if name in CF_COOKIE_NAMES)
    # Cookie values are intentionally never persisted.
    return {
        "count": len(values),
        "names": sorted(set(names)),
        "cf_cookie_names": cf_names,
        "cf_clearance": "cf_clearance" in cf_names,
        "__cf_bm": "__cf_bm" in cf_names,
        "cookie_acquisition": bool(values),
    }


def _local_modules(root: Path) -> list[str]:
    try:
        from stealth.registry import get_default_registry
        registry = get_default_registry()
        return [item.name for item in registry.modules if item.enabled and item.js_file.exists()]
    except Exception:
        return []


def _apply_playwright_stealth(page: Any) -> tuple[list[str], str | None]:
    if importlib.util.find_spec("playwright_stealth") is None:
        return [], "playwright-stealth package is not installed"
    try:
        import playwright_stealth  # type: ignore
        if hasattr(playwright_stealth, "stealth_sync"):
            playwright_stealth.stealth_sync(page)
        elif hasattr(playwright_stealth, "Stealth"):
            instance = playwright_stealth.Stealth()
            method = getattr(instance, "apply_stealth_sync", None)
            if not callable(method):
                return [], "installed playwright-stealth has no synchronous apply method"
            method(page)
        else:
            return [], "installed playwright-stealth API is unsupported"
        return ["playwright-stealth"], None
    except Exception as exc:
        return [], f"playwright-stealth apply failed: {exc}"


def _apply_local_stealth(context: Any, page: Any, root: Path) -> tuple[list[str], str | None]:
    try:
        # Use the existing public page API exactly once.  This keeps the
        # validation mode independent of the framework's internal loader and
        # avoids installing duplicate init scripts.
        from stealth import apply_stealth
        apply_stealth(page)
        return _local_modules(root), None
    except Exception as exc:
        return [], f"local stealth apply failed: {exc}"


def _classify(status: int | None, error: str | None, challenge: bool, timed_out: bool, crashed: bool) -> dict[str, Any]:
    if crashed:
        return {"status": "FAIL", "reason": "Browser/page crash observed."}
    if timed_out:
        return {"status": "FAIL", "reason": "Navigation timeout observed."}
    if status is None:
        if error:
            return {"status": "UNKNOWN", "reason": "No HTTP response after navigation error.", "error": error}
        return {"status": "UNKNOWN", "reason": "No main-document HTTP response observed."}
    if 200 <= status < 400 and not challenge:
        return {"status": "PASS", "reason": "Navigation completed without an observed challenge."}
    if 200 <= status < 400 and challenge:
        return {"status": "WARNING", "reason": "Navigation completed while a challenge was observed."}
    if status in {401, 403, 429, 503, 520, 521, 522, 523, 524}:
        return {"status": "WARNING", "reason": f"Target returned challenge-like HTTP status {status}."}
    if status >= 400:
        return {"status": "WARNING", "reason": f"Target returned HTTP status {status}."}
    return {"status": "UNKNOWN", "reason": "Outcome could not be classified."}


def _quota_check(context: Any, settings: Settings) -> dict[str, Any]:
    if not settings.check_quota:
        return {"attempted": False, "status": "UNKNOWN", "reason": "Quota check disabled."}
    if not settings.quota_endpoint or not settings.quota_year_month:
        return {"attempted": False, "status": "UNKNOWN", "reason": "No quota endpoint or month configured."}
    try:
        response = context.request.post(
            settings.quota_endpoint,
            form={"action": "kapasitas", "id_site": "8", "year_month": settings.quota_year_month},
            timeout=settings.timeout_ms,
        )
        status_code = int(response.status)
        return {
            "attempted": True,
            "status": "PASS" if 200 <= status_code < 400 else "WARNING",
            "http_status": status_code,
            "success": 200 <= status_code < 400,
        }
    except Exception as exc:
        return {"attempted": True, "status": "UNKNOWN", "success": False, "error": str(exc)}


def _run_unavailable(settings: Settings, mode: str, run_number: int, reason: str) -> dict[str, Any]:
    run_id = f"run_{run_number:03d}_{mode}"
    return {
        "run_id": run_id,
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "run_number": run_number,
        "status": "UNKNOWN",
        "reason": reason,
        "mode_error": reason,
        "navigation_success": False,
        "challenge_detected": False,
        "challenge_solved": False,
        "challenge_duration_ms": None,
        "cf_clearance_acquired": False,
        "__cf_bm_acquired": False,
        "http_status": None,
        "redirect_count": 0,
        "redirect_success": False,
        "homepage_success": False,
        "quota_endpoint_success": False,
        "console_errors": [],
        "request_failures": [],
        "response_failures": [],
        "browser_crashed": False,
        "navigation_timeout": False,
        "elapsed_ms": 0.0,
        "load_time_ms": None,
        "modules": [],
        "profile_type": "unavailable",
        "timeline": [],
        "network": [],
        "headers": {},
        "cookies": {"count": 0, "names": [], "cf_clearance": False, "__cf_bm": False},
        "metadata": {
            "browser_version": None,
            "chrome_version": None,
            "playwright_version": package_version("playwright"),
        },
        "screenshot": None,
    }


def _run_navigation(page: Any, context: Any, settings: Settings, mode: str, run_number: int,
                    browser_version: str | None, modules: list[str], profile_type: str,
                    mode_error: str | None, run_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    run_id = f"run_{run_number:03d}_{mode}"
    timeline: list[dict[str, Any]] = []
    network: list[dict[str, Any]] = []
    console_errors: list[dict[str, Any]] = []
    request_failures: list[dict[str, Any]] = []
    response_failures: list[dict[str, Any]] = []
    frame_urls: list[str] = []
    challenge_samples: list[dict[str, Any]] = []
    main_response: Any = None
    navigation_error: str | None = mode_error
    timed_out = False
    crashed = False
    domcontentloaded_ms: float | None = None
    load_event_ms: float | None = None

    def event(name: str, **details: Any) -> None:
        _event(timeline, started, name, **details)

    def on_response(response: Any) -> None:
        nonlocal main_response
        try:
            request = response.request
            is_navigation = bool(request.is_navigation_request())
            resource_type = str(request.resource_type)
        except Exception:
            request, is_navigation, resource_type = None, False, None
        headers = _sanitize_headers(getattr(response, "headers", {}))
        item = {
            "url": str(getattr(response, "url", "")),
            "status": _safe(getattr(response, "status", None)),
            "resource_type": resource_type,
            "is_navigation": is_navigation,
            "headers": headers,
        }
        network.append(item)
        if item["status"] is not None and int(item["status"]) >= 400:
            response_failures.append({"url": item["url"], "status": item["status"], "resource_type": resource_type})
        if is_navigation and resource_type == "document":
            main_response = response
            event("navigation_response", url=item["url"], status=item["status"], cloudflare_headers=_cloudflare_headers(headers))

    def on_request_failed(request: Any) -> None:
        detail = {"url": str(getattr(request, "url", "")), "failure": _safe(getattr(request, "failure", None))}
        request_failures.append(detail)
        event("request_failed", **detail)

    def on_console(message: Any) -> None:
        try:
            msg_type = str(message.type)
            if msg_type == "error":
                entry = {"type": msg_type, "text": str(message.text)}
                console_errors.append(entry)
                event("console_error", **entry)
        except Exception:
            pass

    def on_page_error(error: Any) -> None:
        event("page_error", text=str(error))

    def on_crash() -> None:
        nonlocal crashed
        crashed = True
        event("browser_crash")

    def on_frame_navigated(frame: Any) -> None:
        try:
            if frame == page.main_frame:
                url = str(frame.url)
                frame_urls.append(url)
                event("frame_navigated", url=url)
        except Exception:
            pass

    def on_domcontentloaded() -> None:
        nonlocal domcontentloaded_ms
        domcontentloaded_ms = round((time.perf_counter() - started) * 1000, 2)
        event("domcontentloaded")

    def on_load() -> None:
        nonlocal load_event_ms
        load_event_ms = round((time.perf_counter() - started) * 1000, 2)
        event("load")

    for name, callback in (
        ("response", on_response), ("requestfailed", on_request_failed),
        ("console", on_console), ("pageerror", on_page_error), ("crash", on_crash),
        ("framenavigated", on_frame_navigated), ("domcontentloaded", on_domcontentloaded),
        ("load", on_load),
    ):
        try:
            page.on(name, callback)
        except Exception:
            pass

    event("navigation_start", url=settings.url, mode=mode)
    try:
        response = page.goto(settings.url, wait_until="domcontentloaded", timeout=settings.timeout_ms)
        if response is not None and main_response is None:
            main_response = response
        event("goto_returned", status=_safe(getattr(response, "status", None)))
    except Exception as exc:
        navigation_error = str(exc)
        timed_out = "timeout" in navigation_error.lower()
        event("navigation_error", error=navigation_error, timeout=timed_out)

    # Passive observation window.  It may detect a challenge disappearing, but
    # never clicks, reloads, fills, or submits anything.
    first_challenge_ms: float | None = None
    challenge_duration_ms: float | None = None
    challenge_detected = False
    challenge_solved = False
    last_signals: dict[str, Any] = {}
    observation_until = time.perf_counter() + max(0, settings.wait_ms) / 1000
    while time.perf_counter() <= observation_until:
        try:
            signals = _page_signals(page)
        except Exception as exc:
            signals = {"error": str(exc)}
        last_signals = signals
        sample_elapsed = round((time.perf_counter() - started) * 1000, 2)
        sample = {"elapsed_ms": sample_elapsed, **{key: signals.get(key) for key in ("challenge", "turnstile", "captcha", "title", "url")}}
        challenge_samples.append(sample)
        event("challenge_sample", **sample)
        if signals.get("challenge") is True:
            challenge_detected = True
            if first_challenge_ms is None:
                first_challenge_ms = sample_elapsed
                event("challenge_detected")
        elif challenge_detected and first_challenge_ms is not None and challenge_duration_ms is None:
            challenge_duration_ms = round(max(0.0, sample_elapsed - first_challenge_ms), 2)
            challenge_solved = True
            event("challenge_no_longer_present", duration_ms=challenge_duration_ms)
        if time.perf_counter() >= observation_until:
            break
        try:
            page.wait_for_timeout(min(250, max(1, int((observation_until - time.perf_counter()) * 1000))))
        except Exception:
            break

    if challenge_detected and challenge_duration_ms is None and first_challenge_ms is not None:
        # The challenge remained visible for the complete passive observation
        # window.  Record the observed lower bound rather than claiming it was
        # solved.
        challenge_duration_ms = round(max(0.0, (time.perf_counter() - started) * 1000 - first_challenge_ms), 2)
    event("navigation_end", url=_safe(last_signals.get("url"), settings.url), title=_safe(last_signals.get("title"), ""))
    paint = _paint_entries(page)
    if paint.get("first_paint_ms") is not None:
        event("first_paint", value_ms=paint["first_paint_ms"])
    if paint.get("first_contentful_paint_ms") is not None:
        event("first_contentful_paint", value_ms=paint["first_contentful_paint_ms"])

    cookies = _cookie_snapshot(context)
    if cookies.get("cookie_acquisition"):
        event("cookies_acquired", count=cookies.get("count"))
    try:
        quota = _quota_check(context, settings)
    except Exception as exc:
        quota = {"attempted": True, "status": "UNKNOWN", "success": False, "error": str(exc)}
    if quota.get("attempted"):
        event("quota_endpoint", status=quota.get("status"), http_status=quota.get("http_status"))

    status = None
    main_headers: dict[str, str] = {}
    if main_response is not None:
        try:
            status = int(main_response.status)
            main_headers = _sanitize_headers(main_response.headers)
        except Exception:
            pass
    final_url = _safe(last_signals.get("url"), _safe(getattr(page, "url", None), settings.url))
    redirects = 0
    if main_response is not None:
        try:
            request = main_response.request
            while request is not None:
                previous = request.redirected_from
                if previous is None:
                    break
                redirects += 1
                request = previous
        except Exception:
            redirects = max(0, len(frame_urls) - 1)
    else:
        redirects = max(0, len(frame_urls) - 1)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    navigation_success = bool(status is not None and 200 <= status < 400 and not timed_out and not crashed)
    parsed_target, parsed_final = urlparse(settings.url), urlparse(str(final_url))
    homepage_success = bool(navigation_success and parsed_target.hostname and parsed_target.hostname == parsed_final.hostname and not challenge_detected)
    classification = _classify(status, navigation_error, challenge_detected, timed_out, crashed)
    if mode_error:
        # A navigation result is not attributed to a mode whose injection
        # setup failed; keep the observation but mark its mode outcome
        # UNKNOWN for fair comparison.
        classification = {"status": "UNKNOWN", "reason": mode_error, "navigation_observed": True}
    result = {
        "run_id": run_id,
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "run_number": run_number,
        "status": classification["status"],
        "classification": classification,
        "reason": navigation_error,
        "mode_error": mode_error,
        "navigation_success": navigation_success,
        "challenge_detected": challenge_detected,
        "challenge_solved": challenge_solved,
        "challenge_duration_ms": challenge_duration_ms,
        "challenge_timed_out": bool(challenge_detected and not challenge_solved and settings.wait_ms > 0),
        "turnstile_detected": any(sample.get("turnstile") is True for sample in challenge_samples),
        "captcha_detected": any(sample.get("captcha") is True for sample in challenge_samples),
        "cf_clearance_acquired": bool(cookies.get("cf_clearance")),
        "__cf_bm_acquired": bool(cookies.get("__cf_bm")),
        "cookie_acquisition": bool(cookies.get("cookie_acquisition")),
        "cookie_count": int(cookies.get("count", 0)),
        "http_status": status,
        "redirect_count": redirects,
        "redirect_success": bool(main_response is not None and status is not None and status < 400),
        "homepage_success": homepage_success,
        "quota_endpoint_success": bool(quota.get("success")),
        "quota": quota,
        "final_url": final_url,
        "page_title": _safe(last_signals.get("title"), ""),
        "domcontentloaded_ms": domcontentloaded_ms,
        "load_event_ms": load_event_ms,
        "first_paint_ms": paint.get("first_paint_ms"),
        "first_contentful_paint_ms": paint.get("first_contentful_paint_ms"),
        "load_time_ms": load_event_ms if load_event_ms is not None else elapsed_ms,
        "elapsed_ms": elapsed_ms,
        "console_errors": console_errors,
        "request_failures": request_failures,
        "response_failures": response_failures,
        "browser_crashed": crashed,
        "navigation_timeout": timed_out,
        "js_redirect_count": max(0, len(frame_urls) - 1 - redirects),
        "frame_urls": frame_urls,
        "metadata": {
            **_browser_metadata(page, browser_version, package_version("playwright")),
            "chrome_version": browser_version if mode in {"chrome_cdp", "chrome_manual_profile"} else None,
        },
        "modules": modules,
        "profile_type": profile_type,
        "timeline": timeline,
        "network": network,
        "headers": {"main": main_headers, "cloudflare": _cloudflare_headers(main_headers)},
        "cookies": cookies,
        "challenge_samples": challenge_samples,
        "screenshot": None,
    }
    try:
        screenshot = run_dir / "screenshot.png"
        page.screenshot(path=str(screenshot), full_page=False)
        result["screenshot"] = relative_path(screenshot, settings.root)
        event("screenshot", path=result["screenshot"])
    except Exception as exc:
        result["screenshot_error"] = str(exc)
    return result


def _launch_mode(playwright: Any, settings: Settings, mode: str, run_number: int,
                 experiment_root: Path) -> dict[str, Any]:
    """Launch one isolated mode and collect one run."""
    run_id = f"run_{run_number:03d}_{mode}"
    run_dir = experiment_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    browser = context = page = None
    profile_type = "ephemeral"
    modules: list[str] = []
    mode_error: str | None = None
    browser_version: str | None = None
    try:
        launch_args = ["--disable-dev-shm-usage"]
        if mode in {"plain", "playwright_stealth", "local_stealth"}:
            browser = playwright.chromium.launch(headless=settings.headless, args=launch_args)
            browser_version = _safe(getattr(browser, "version", None))
            context = browser.new_context()
            page = context.new_page()
            if mode == "playwright_stealth":
                modules, mode_error = _apply_playwright_stealth(page)
            elif mode == "local_stealth":
                modules, mode_error = _apply_local_stealth(context, page, settings.root)
        elif mode == "chrome_cdp":
            if not settings.cdp_url:
                return _run_unavailable(settings, mode, run_number, "No --cdp-url supplied.")
            browser = playwright.chromium.connect_over_cdp(settings.cdp_url)
            browser_version = _safe(getattr(browser, "version", None))
            contexts = browser.contexts
            if not contexts:
                return _run_unavailable(settings, mode, run_number, "CDP endpoint exposed no browser context.")
            context = contexts[0]
            profile_type = "cdp_remote"
            page = context.new_page()
            modules = ["real-chrome-cdp"]
        elif mode == "chrome_manual_profile":
            if not settings.manual_profile:
                return _run_unavailable(settings, mode, run_number, "No --manual-profile supplied.")
            profile = settings.manual_profile.expanduser().resolve()
            if not profile.exists() or not profile.is_dir():
                return _run_unavailable(settings, mode, run_number, f"Manual profile does not exist: {profile}")
            context = playwright.chromium.launch_persistent_context(
                str(profile), channel="chrome", headless=settings.headless, args=launch_args,
            )
            profile_type = "persistent"
            browser = context.browser
            browser_version = _safe(getattr(browser, "version", None))
            page = context.pages[0] if context.pages else context.new_page()
            modules = ["chrome-manual-profile"]
        else:
            return _run_unavailable(settings, mode, run_number, f"Unsupported mode: {mode}")
        if page is None or context is None:
            return _run_unavailable(settings, mode, run_number, mode_error or "Browser context unavailable.")
        return _run_navigation(page, context, settings, mode, run_number, browser_version, modules, profile_type, mode_error, run_dir)
    except Exception as exc:
        return _run_unavailable(settings, mode, run_number, str(exc))
    finally:
        # CDP attaches to an externally owned browser; only close the page.
        if page is not None and mode == "chrome_cdp":
            try:
                page.close()
            except Exception:
                pass
        elif context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None and mode not in {"chrome_cdp", "chrome_manual_profile"}:
            try:
                browser.close()
            except Exception:
                pass


def _stats(records: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    values = [item for item in records if item.get("mode") == mode]
    total = len(values)
    count = lambda predicate: sum(1 for item in values if predicate(item))
    load_times = [float(item["load_time_ms"]) for item in values if isinstance(item.get("load_time_ms"), (int, float))]
    success_count = count(lambda item: bool(item.get("navigation_success")))
    challenge_count = count(lambda item: bool(item.get("challenge_detected")))
    observed_http = [item for item in values if item.get("http_status") is not None]
    status_403 = count(lambda item: item.get("http_status") == 403)
    unknown = count(lambda item: item.get("status") == "UNKNOWN")
    failure = count(lambda item: item.get("status") == "FAIL")
    return {
        "mode": mode,
        "label": MODE_LABELS[mode],
        "runs": total,
        "navigation_success_rate": round(success_count / total * 100, 2) if total else 0.0,
        "challenge_rate": round(challenge_count / total * 100, 2) if total else 0.0,
        "challenge_solved_rate": round(count(lambda item: bool(item.get("challenge_solved"))) / total * 100, 2) if total else 0.0,
        "clearance_acquisition_rate": round(count(lambda item: bool(item.get("cf_clearance_acquired"))) / total * 100, 2) if total else 0.0,
        "cookie_acquisition_rate": round(count(lambda item: bool(item.get("cookie_acquisition"))) / total * 100, 2) if total else 0.0,
        "http_success_rate": round(count(lambda item: isinstance(item.get("http_status"), int) and 200 <= item["http_status"] < 400) / total * 100, 2) if total else 0.0,
        "redirect_success_rate": round(count(lambda item: bool(item.get("redirect_success"))) / total * 100, 2) if total else 0.0,
        "homepage_success_rate": round(count(lambda item: bool(item.get("homepage_success"))) / total * 100, 2) if total else 0.0,
        "quota_endpoint_success_rate": round(count(lambda item: bool(item.get("quota_endpoint_success"))) / total * 100, 2) if total else 0.0,
        "403_rate": round(status_403 / total * 100, 2) if total else 0.0,
        "timeout_rate": round(count(lambda item: bool(item.get("navigation_timeout"))) / total * 100, 2) if total else 0.0,
        "crash_rate": round(count(lambda item: bool(item.get("browser_crashed"))) / total * 100, 2) if total else 0.0,
        "failure_rate": round(failure / total * 100, 2) if total else 0.0,
        "unknown_rate": round(unknown / total * 100, 2) if total else 0.0,
        "average_load_time_ms": round(statistics.mean(load_times), 2) if load_times else None,
        "median_load_time_ms": round(statistics.median(load_times), 2) if load_times else None,
        "average_challenge_duration_ms": round(statistics.mean([float(item["challenge_duration_ms"]) for item in values if isinstance(item.get("challenge_duration_ms"), (int, float))]), 2) if any(isinstance(item.get("challenge_duration_ms"), (int, float)) for item in values) else None,
        "average_redirects": round(statistics.mean([float(item.get("redirect_count", 0)) for item in values]), 2) if values else 0.0,
    }


def _rank_classification(stat: dict[str, Any]) -> str:
    if not stat["runs"] or stat["unknown_rate"] == 100:
        return "UNUSABLE"
    if stat["navigation_success_rate"] >= 100 and stat["crash_rate"] == 0 and stat["timeout_rate"] == 0:
        return "BEST"
    if stat["navigation_success_rate"] >= 75 and stat["crash_rate"] == 0 and stat["timeout_rate"] == 0:
        return "GOOD"
    if stat["navigation_success_rate"] > 0:
        return "NEUTRAL"
    if stat["crash_rate"] > 0 or stat["timeout_rate"] > 0:
        return "UNUSABLE"
    return "POOR"


def _render_report(settings: Settings, experiment: Experiment, records: list[dict[str, Any]], stats: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    rows = []
    for stat in stats:
        rows.append(
            f"| {stat['label']} | {stat['runs']} | {stat['navigation_success_rate']:.1f}% | "
            f"{stat['challenge_rate']:.1f}% | {stat['clearance_acquisition_rate']:.1f}% | "
            f"{stat['403_rate']:.1f}% | {stat['timeout_rate']:.1f}% | {stat['crash_rate']:.1f}% | "
            f"{stat['average_load_time_ms'] if stat['average_load_time_ms'] is not None else '—'} ms | "
            f"{stat['median_load_time_ms'] if stat['median_load_time_ms'] is not None else '—'} ms | "
            f"{stat['classification']} |"
        )
    clearance = summary.get("clearance_modes") or ["None observed"]
    return f"""# Experiment 018 — Real Browser Validation

This report is observational only. No CAPTCHA, Turnstile, Cloudflare challenge,
or booking interaction was automated. Cookie values are never persisted.

## Configuration

- Target: `{settings.url}`
- Runs per mode: `{settings.runs}`
- Headless: `{settings.headless}`
- Playwright: `{package_version('playwright')}`
- Experiment allocation: `{experiment.experiment_id}`

## Mode comparison

| Mode | Runs | Navigation success | Challenge rate | cf_clearance | 403 rate | Timeout | Crash | Avg load | Median load | Classification |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(rows)}

## Observed answers

- Most stable: **{summary.get('most_stable') or 'No mode with a completed run'}**
- Mode acquiring `cf_clearance`: **{', '.join(clearance)}**
- Most challenges: **{summary.get('most_challenged') or 'No challenge observed'}**
- Fastest (median load): **{summary.get('fastest') or 'No measurable load'}**
- Most failures: **{summary.get('most_failed') or 'No failures observed'}**
- Bot-monitoring candidate: **{summary.get('bot_monitoring_mode') or 'None from this sample'}**
- Booking suitability: **NOT_EVALUATED** — this experiment performs no booking or challenge interaction.

## Limitations and interpretation

Results are tied to the target URL, network, browser build, profile state, and
time of execution. `cf_clearance` acquisition is not a bypass guarantee, and
absence of a challenge in one run is not evidence of production reliability.
Use the mode marked for monitoring only as a hypothesis for further authorized
testing, with rate limits and manual review.

Generated at `{now_iso()}`.
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experiment 018: observational real-browser validation")
    parser.add_argument("--url", default=None)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=30_000, help="Navigation timeout in milliseconds")
    parser.add_argument("--wait", type=int, default=5_000, help="Passive observation window in milliseconds")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--cdp-url", default=None)
    parser.add_argument("--manual-profile", type=Path, default=None)
    parser.add_argument("--quota-endpoint", default=None)
    parser.add_argument("--quota-year-month", default=None, help="YYYY-MM; quota check is read-only")
    parser.add_argument("--no-quota-check", action="store_true")
    parser.add_argument("--modes", default=", ".join(MODES).replace(", ", ","), help="Comma-separated mode list")
    parser.add_argument("--reports-root", type=Path, default=None)
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    root = project_root()
    try:
        from bot.constants import BASE_URL, QUOTA_ENDPOINT
    except Exception:
        BASE_URL, QUOTA_ENDPOINT = "https://bromotenggersemeru.id/", None
    month = args.quota_year_month or datetime.now().strftime("%Y-%m")
    requested = tuple(item.strip() for item in str(args.modes).split(",") if item.strip())
    unknown = [item for item in requested if item not in MODES]
    if unknown:
        raise ValueError(f"Unknown mode(s): {', '.join(unknown)}")
    runs = max(1, int(args.runs))
    return Settings(
        root=root,
        reports_root=(args.reports_root or root / "reports" / "experiments").resolve(),
        url=args.url or BASE_URL,
        runs=runs,
        timeout_ms=max(1000, int(args.timeout)),
        wait_ms=max(0, int(args.wait)),
        headless=not bool(args.headful),
        cdp_url=args.cdp_url,
        manual_profile=args.manual_profile,
        quota_endpoint=args.quota_endpoint or QUOTA_ENDPOINT,
        quota_year_month=month,
        check_quota=not bool(args.no_quota_check),
        modes=requested or MODES,
    )


def main(argv: list[str] | None = None) -> int:
    configure_console_error_handling()
    args = _build_parser().parse_args(argv)
    try:
        settings = _settings(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    experiment = Experiment.create(settings.reports_root)
    output = experiment.directory / "real_validation"
    output.mkdir(parents=True, exist_ok=False)
    metadata = {
        "experiment": "Experiment 018 — Real Browser Validation",
        "experiment_id": experiment.experiment_id,
        "started_at": experiment.started_at,
        "target_url": settings.url,
        "modes": list(settings.modes),
        "runs": settings.runs,
        "timeout_ms": settings.timeout_ms,
        "wait_ms": settings.wait_ms,
        "headless": settings.headless,
        "profile_type": "persistent_requested" if settings.manual_profile else "ephemeral",
        "quota_check": settings.check_quota,
        "observational_only": True,
        "challenge_interaction": False,
        "stealth_modified": False,
        "environment": system_metadata(),
        "git": git_metadata(settings.root),
        "playwright_version": package_version("playwright"),
    }
    write_json_exclusive(output / "metadata.json", metadata)
    records: list[dict[str, Any]] = []
    started_all = time.perf_counter()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            for run_number in range(1, settings.runs + 1):
                for mode in settings.modes:
                    print(f"[exp_018] run {run_number}/{settings.runs} — {MODE_LABELS[mode]}")
                    records.append(_launch_mode(playwright, settings, mode, run_number, output))
    except Exception as exc:
        # Preserve immutable output even when Playwright cannot be imported or launched.
        for run_number in range(1, settings.runs + 1):
            for mode in settings.modes:
                if not any(item.get("run_number") == run_number and item.get("mode") == mode for item in records):
                    records.append(_run_unavailable(settings, mode, run_number, str(exc)))

    stats = []
    for mode in settings.modes:
        item = _stats(records, mode)
        item["classification"] = _rank_classification(item)
        stats.append(item)
    usable = [item for item in stats if item["runs"] and item["unknown_rate"] < 100]
    stable = sorted(usable, key=lambda item: (-item["navigation_success_rate"], item["crash_rate"], item["timeout_rate"], item["median_load_time_ms"] if item["median_load_time_ms"] is not None else float("inf")))
    fastest = sorted([item for item in usable if item["median_load_time_ms"] is not None], key=lambda item: item["median_load_time_ms"])
    challenge_modes = sorted(usable, key=lambda item: item["challenge_rate"], reverse=True)
    failure_modes = sorted(usable, key=lambda item: item["failure_rate"] + item["timeout_rate"] + item["crash_rate"], reverse=True)
    clearance_modes = [item["label"] for item in stats if item["clearance_acquisition_rate"] > 0]
    summary = {
        "experiment": "Experiment 018 — Real Browser Validation",
        "experiment_id": experiment.experiment_id,
        "completed_at": now_iso(),
        "target_url": settings.url,
        "total_runs": len(records),
        "duration_ms": round((time.perf_counter() - started_all) * 1000, 2),
        "most_stable": stable[0]["label"] if stable else None,
        "clearance_modes": clearance_modes,
        "most_challenged": challenge_modes[0]["label"] if challenge_modes and challenge_modes[0]["challenge_rate"] > 0 else None,
        "fastest": fastest[0]["label"] if fastest else None,
        "most_failed": failure_modes[0]["label"] if failure_modes and (failure_modes[0]["failure_rate"] + failure_modes[0]["timeout_rate"] + failure_modes[0]["crash_rate"]) > 0 else None,
        "bot_monitoring_mode": stable[0]["label"] if stable and stable[0]["navigation_success_rate"] > 0 else None,
        "booking_suitability": "NOT_EVALUATED",
        "booking_reason": "No booking or challenge interaction is performed by this observational experiment.",
        "limitations": [
            "A single run is not a production reliability guarantee.",
            "Cloudflare outcomes vary by target, network, browser build, and time.",
            "cf_clearance acquisition is recorded, never requested or forged.",
            "Unavailable optional modes are classified UNKNOWN rather than failure.",
        ],
        "statistics": stats,
    }
    evaluation = {"metadata": metadata, "runs": records}
    timeline = {"experiment_id": experiment.experiment_id, "runs": [{"run_id": r["run_id"], "mode": r["mode"], "events": r.get("timeline", []), "challenge_samples": r.get("challenge_samples", [])} for r in records]}
    network = {"experiment_id": experiment.experiment_id, "runs": [{"run_id": r["run_id"], "mode": r["mode"], "http_status": r.get("http_status"), "final_url": r.get("final_url"), "redirect_count": r.get("redirect_count"), "requests": r.get("network", []), "request_failures": r.get("request_failures", []), "response_failures": r.get("response_failures", [])} for r in records]}
    cookies = {"experiment_id": experiment.experiment_id, "runs": [{"run_id": r["run_id"], "mode": r["mode"], "cookies": r.get("cookies", {})} for r in records]}
    headers = {"experiment_id": experiment.experiment_id, "runs": [{"run_id": r["run_id"], "mode": r["mode"], "headers": r.get("headers", {})} for r in records]}
    write_json_exclusive(output / "evaluation.json", evaluation)
    write_json_exclusive(output / "timeline.json", timeline)
    write_json_exclusive(output / "network.json", network)
    write_json_exclusive(output / "cookies.json", cookies)
    write_json_exclusive(output / "headers.json", headers)
    write_json_exclusive(output / "statistics.json", {"experiment_id": experiment.experiment_id, "modes": stats})
    write_json_exclusive(output / "summary.json", summary)
    write_text_exclusive(output / "real_validation_report.md", _render_report(settings, experiment, records, stats, summary))
    print("\nREAL BROWSER VALIDATION")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Target: {settings.url}")
    print(f"Runs: {len(records)}")
    print(f"Most stable: {summary.get('most_stable') or 'none observed'}")
    print(f"cf_clearance: {', '.join(clearance_modes) if clearance_modes else 'none observed'}")
    print(f"Artifacts: {relative_path(output, settings.root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
