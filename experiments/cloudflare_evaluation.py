"""Experiment 015: observational Cloudflare evaluation.

This module does not solve, bypass, or interact with a Cloudflare challenge.
It only records what a normal Playwright navigation observes and classifies
the outcome.  Every invocation receives a new immutable experiment directory;
``--runs`` additionally stores immutable per-run artifacts below ``runs/``.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import logging
import sys
import time

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.baseline import load_baseline, resolve_baseline_path
from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    relative_path,
    write_json_exclusive,
    write_text_exclusive,
)
from tools._shared import BrowserConfig, get_cf_cookies, is_cf_challenge, launch_browser, setup_logging


log = setup_logging("experiment.cloudflare_evaluation")
CF_HEADER_NAMES = ("cf-ray", "cf-cache-status", "server", "cf-mitigated", "cf-chl-out")
CF_COOKIE_NAMES = {"cf_clearance", "__cf_bm", "cf_chl_2", "cf_chl_prog", "cf_chl_rc_ni"}
CHALLENGE_TITLES = (
    "just a moment", "tunggu sebentar", "verify you are human",
    "checking your browser", "please wait", "security check",
)
COMPLETE_STACK_MODULES = (
    "navigator", "window", "screen", "chrome", "permissions", "fonts", "speech", "performance", "webgl",
)


@dataclass(frozen=True)
class Settings:
    root: Path
    output: Path
    url: str
    channel: str
    headless: bool
    profile: Path | None
    wait_ms: int
    timeout_ms: int
    runs: int
    use_stealth: bool


class Recorder:
    """Monotonic event recorder with JSON-safe timestamps."""

    def __init__(self) -> None:
        self.started_perf = time.perf_counter()
        self.events: list[dict[str, Any]] = []

    def add(self, kind: str, **details: Any) -> dict[str, Any]:
        event = {
            "sequence": len(self.events) + 1,
            "event": kind,
            "timestamp": now_iso(),
            "elapsed_ms": round((time.perf_counter() - self.started_perf) * 1000, 2),
        }
        event.update(details)
        self.events.append(event)
        return event


def _safe_headers(headers: Any) -> dict[str, str]:
    if not isinstance(headers, dict):
        return {}
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _cf_headers(headers: dict[str, str]) -> dict[str, str | None]:
    return {name: headers.get(name) for name in CF_HEADER_NAMES}


def _redacted_cookie(cookie: dict[str, Any]) -> dict[str, Any]:
    value = str(cookie.get("value") or "")
    result = {key: cookie.get(key) for key in (
        "name", "domain", "path", "expires", "httpOnly", "secure", "sameSite",
    )}
    result.update({
        "value_present": bool(value),
        "value_length": len(value),
        "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None,
    })
    return result


def _cookie_snapshot(context: Any) -> dict[str, Any]:
    try:
        cookies = context.cookies()
    except Exception as exc:  # pragma: no cover - browser teardown edge case
        return {"cookies": [], "error": str(exc), "cf_cookies": {}}
    redacted = [_redacted_cookie(cookie) for cookie in cookies if isinstance(cookie, dict)]
    cf = {
        str(cookie.get("name")): {
            "acquired": bool(cookie.get("value")),
            "domain": cookie.get("domain"),
            "path": cookie.get("path"),
            "value_length": len(str(cookie.get("value") or "")),
        }
        for cookie in cookies
        if isinstance(cookie, dict) and cookie.get("name") in CF_COOKIE_NAMES
    }
    return {
        "cookies": redacted,
        "cookie_count": len(redacted),
        "cf_cookies": cf,
        "cf_clearance_acquired": bool(cf.get("cf_clearance", {}).get("acquired")),
        "cf_bm_acquired": bool(cf.get("__cf_bm", {}).get("acquired")),
    }


def _page_signals(page: Any) -> dict[str, Any]:
    """Read challenge markers without clicking or changing page state."""
    script = """() => {
      const title = String(document.title || '');
      const body = String(document.body ? document.body.innerText || '' : '').slice(0, 12000);
      const html = String(document.documentElement ? document.documentElement.innerHTML || '' : '').slice(0, 30000);
      const lower = (title + '\\n' + body + '\\n' + html).toLowerCase();
      const challengeText = /just a moment|tunggu sebentar|verify you are human|checking your browser|please wait|security check/.test(lower);
      const challengeNodes = !!document.querySelector('#challenge-running,#challenge-stage,#cf-challenge-running,[name="cf-turnstile-response"],iframe[src*="challenges.cloudflare.com"]');
      const turnstile = !!document.querySelector('.cf-turnstile,[data-sitekey],iframe[src*="challenges.cloudflare.com/turnstile"],[name="cf-turnstile-response"]');
      const captcha = !!document.querySelector('[id*="captcha" i],[class*="captcha" i],iframe[src*="recaptcha"],iframe[src*="hcaptcha"]');
      return { title, challengeText, challengeNodes, challenge: challengeText || challengeNodes, turnstile, captcha, url: location.href };
    }"""
    try:
        value = page.evaluate(script)
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        return {"error": str(exc), "challenge": None, "turnstile": None, "captcha": None}


def _performance_snapshot(page: Any) -> dict[str, Any]:
    script = """() => {
      const nav = performance.getEntriesByType('navigation')[0];
      const fcp = performance.getEntriesByName('first-contentful-paint')[0];
      const timing = performance.timing || {};
      const pick = (obj, names) => Object.fromEntries(names.filter(n => obj && typeof obj[n] === 'number').map(n => [n, obj[n]]));
      return {
        timeOrigin: performance.timeOrigin,
        now: performance.now(),
        firstContentfulPaint: fcp ? fcp.startTime : null,
        navigation: nav ? {
          name: nav.name, entryType: nav.entryType, startTime: nav.startTime,
          duration: nav.duration, type: nav.type, redirectCount: nav.redirectCount,
          nextHopProtocol: nav.nextHopProtocol, transferSize: nav.transferSize,
          requestStart: nav.requestStart, responseStart: nav.responseStart,
          responseEnd: nav.responseEnd, domInteractive: nav.domInteractive,
          domContentLoadedEventEnd: nav.domContentLoadedEventEnd,
          loadEventEnd: nav.loadEventEnd
        } : null,
        legacyTiming: pick(timing, ['navigationStart','fetchStart','requestStart','responseStart','responseEnd','domInteractive','domContentLoadedEventEnd','loadEventEnd']),
        resourceCount: performance.getEntriesByType('resource').length
      };
    }"""
    try:
        value = page.evaluate(script)
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        return {"error": str(exc)}


def _browser_metadata(page: Any, context: Any, settings: Settings, modules: list[str]) -> dict[str, Any]:
    try:
        browser_version = page.context.browser.version if page.context.browser else None
    except Exception:
        browser_version = None
    try:
        navigator = page.evaluate("""() => ({
          userAgent: navigator.userAgent,
          platform: navigator.platform,
          language: navigator.language,
          webdriver: navigator.webdriver
        })""")
    except Exception:
        navigator = {}
    try:
        context_options = dict(context._options) if hasattr(context, "_options") else {}
    except Exception:
        context_options = {}
    return {
        "browser_version": browser_version,
        "playwright_version": importlib.metadata.version("playwright"),
        "headless": settings.headless,
        "headed": not settings.headless,
        "persistent_profile": bool(settings.profile),
        "profile_path": str(settings.profile) if settings.profile else None,
        "url_tested": settings.url,
        "stealth_enabled": bool(modules),
        "stealth_modules_enabled": modules,
        "navigator": navigator,
        "context_options": {key: str(value) for key, value in context_options.items() if key in {"locale", "timezone_id"}},
    }


def _classify(
    *,
    status: int | None,
    navigation_error: str | None,
    timed_out: bool,
    challenge_seen: bool,
    challenge_still_present: bool | None,
    challenge_solved: bool,
    browser_errors: list[str],
) -> dict[str, Any]:
    blocked = status in {401, 403, 429, 503, 520, 521, 522, 523, 524}
    http_success = status is not None and 200 <= status < 400
    if timed_out:
        return {"status": "FAIL", "reason": "Navigation or challenge wait timed out.", "blocked": blocked, "http_success": http_success}
    if blocked:
        return {"status": "FAIL", "reason": f"Cloudflare/proxy response indicates blocked or challenged HTTP status {status}.", "blocked": True, "http_success": False}
    if browser_errors and not status:
        return {"status": "UNKNOWN", "reason": "Browser or network error prevented an HTTP outcome from being observed.", "blocked": False, "http_success": False}
    if navigation_error and not status:
        return {"status": "UNKNOWN", "reason": "Navigation failed before an HTTP response was observed.", "blocked": False, "http_success": False}
    if not http_success:
        return {"status": "UNKNOWN", "reason": "No successful HTTP response was observed.", "blocked": False, "http_success": False}
    if challenge_seen and challenge_still_present:
        return {"status": "WARNING", "reason": "A Cloudflare challenge remained visible after the observation window.", "blocked": False, "http_success": True}
    if challenge_seen and challenge_solved:
        return {"status": "PASS", "reason": "Challenge disappeared and a successful final response was observed.", "blocked": False, "http_success": True}
    if challenge_seen:
        return {"status": "WARNING", "reason": "Challenge activity was observed, but a solved state could not be proven.", "blocked": False, "http_success": True}
    return {"status": "PASS", "reason": "Successful navigation without an observed challenge.", "blocked": False, "http_success": True}


def evaluate_run(settings: Settings, run_id: str) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    modules: list[str] = []
    if settings.use_stealth:
        from stealth.registry import get_default_registry
        modules = [module.name for module in get_default_registry().modules if module.enabled and module.js_file.exists()]

    recorder = Recorder()
    responses: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    main_navigations: list[dict[str, Any]] = []
    console_messages: list[dict[str, Any]] = []
    page_errors: list[str] = []
    request_failures: list[dict[str, Any]] = []
    response_status: int | None = None
    final_headers: dict[str, str] = {}
    navigation_error: str | None = None
    timed_out = False
    context = None
    handle = None
    page = None
    browser_meta: dict[str, Any] = {}
    challenge_samples: list[dict[str, Any]] = []
    final_signals: dict[str, Any] = {}
    performance: dict[str, Any] = {}
    cookie_snapshot: dict[str, Any] = {"cookies": [], "cookie_count": 0, "cf_cookies": {}}
    final_url: str | None = None

    def on_request(request: Any) -> None:
        if len(requests) >= 500:
            return
        if request.resource_type == "document" or request.is_navigation_request():
            requests.append({
                "url": request.url,
                "method": request.method,
                "resource_type": request.resource_type,
                "is_navigation": request.is_navigation_request(),
                "redirected_from": request.redirected_from.url if request.redirected_from else None,
            })

    def on_response(response: Any) -> None:
        nonlocal response_status, final_headers
        if len(responses) >= 500:
            return
        headers = _safe_headers(response.headers)
        is_main = response.request.is_navigation_request() and response.request.resource_type == "document"
        item = {
            "url": response.url,
            "status": response.status,
            "status_text": response.status_text,
            "resource_type": response.request.resource_type,
            "is_navigation": response.request.is_navigation_request(),
            "headers": headers,
            "cf_headers": _cf_headers(headers),
        }
        responses.append(item)
        if is_main:
            response_status = response.status
            final_headers = headers
            main_navigations.append({
                "url": response.url,
                "status": response.status,
                "redirected_from": response.request.redirected_from.url if response.request.redirected_from else None,
                "cf_headers": _cf_headers(headers),
            })
            recorder.add("http_response", url=response.url, status=response.status, cf_headers=_cf_headers(headers))

    def on_frame_navigated(frame: Any) -> None:
        if page is not None and frame == page.main_frame:
            recorder.add("frame_navigated", url=frame.url)

    def on_load() -> None:
        recorder.add("load")

    def on_domcontentloaded() -> None:
        recorder.add("domcontentloaded")

    def on_console(message: Any) -> None:
        if len(console_messages) < 200:
            console_messages.append({"type": message.type, "text": message.text[:2000]})

    def on_page_error(error: Any) -> None:
        if len(page_errors) < 100:
            page_errors.append(str(error))

    def on_request_failed(request: Any) -> None:
        if len(request_failures) < 100:
            request_failures.append({"url": request.url, "failure": request.failure})

    try:
        with sync_playwright() as playwright:
            config = BrowserConfig(
                channel=settings.channel,
                headless=settings.headless,
                profile=str(settings.profile) if settings.profile else "",
                url=settings.url,
                wait_ms=settings.wait_ms,
                timeout=settings.timeout_ms,
            )
            handle, page, _persistent = launch_browser(playwright, config)
            context = page.context
            page.on("request", on_request)
            page.on("response", on_response)
            page.on("framenavigated", on_frame_navigated)
            page.on("load", on_load)
            page.on("domcontentloaded", on_domcontentloaded)
            page.on("console", on_console)
            page.on("pageerror", on_page_error)
            page.on("requestfailed", on_request_failed)
            if settings.use_stealth:
                try:
                    from stealth import apply_stealth
                    from stealth.apply import apply_modules
                    apply_stealth(page)
                    # Performance is a completed module but remains marked as
                    # placeholder in the legacy registry.  Load any existing
                    # stack module not already included by apply_stealth;
                    # markers in each module keep this idempotent.
                    missing = [name for name in COMPLETE_STACK_MODULES if name not in modules]
                    if missing:
                        apply_modules(page, missing)
                        modules = [name for name in COMPLETE_STACK_MODULES if (settings.root / "stealth" / "modules" / f"{name}.js").is_file()]
                    recorder.add("stealth_applied", modules=modules)
                except Exception as exc:
                    page_errors.append(f"stealth apply: {exc}")
                    recorder.add("stealth_apply_error", error=str(exc))
            browser_meta = _browser_metadata(page, context, settings, modules)
            recorder.add("navigation_start", url=settings.url)
            try:
                page.goto(settings.url, wait_until="domcontentloaded", timeout=settings.timeout_ms)
            except Exception as exc:
                navigation_error = str(exc)
                timed_out = "timeout" in navigation_error.lower()
                recorder.add("navigation_error", error=navigation_error, timeout=timed_out)

            sample_interval = 250
            waited = 0
            while waited < settings.wait_ms:
                try:
                    page.wait_for_timeout(min(sample_interval, settings.wait_ms - waited))
                    signals = _page_signals(page)
                    signals["elapsed_ms"] = round((time.perf_counter() - recorder.started_perf) * 1000, 2)
                    challenge_samples.append(signals)
                    if signals.get("challenge") and not any(sample.get("challenge") for sample in challenge_samples[:-1]):
                        recorder.add("challenge_detected", title=signals.get("title"), url=signals.get("url"))
                    if signals.get("turnstile"):
                        recorder.add("turnstile_detected", url=signals.get("url"))
                    if signals.get("captcha"):
                        recorder.add("captcha_detected", url=signals.get("url"))
                except Exception as exc:
                    recorder.add("observation_error", error=str(exc))
                    break
                waited += sample_interval

            final_signals = _page_signals(page)
            challenge_samples.append(final_signals)
            performance = _performance_snapshot(page)
            cookie_snapshot = _cookie_snapshot(context)
            recorder.add("navigation_end", url=page.url, status=response_status)
            recorder.add("observation_end", waiting_ms=waited)
            final_url = page.url
    except Exception as exc:
        navigation_error = navigation_error or str(exc)
        if not page_errors:
            page_errors.append(str(exc))
        final_url = page.url if page is not None else None
        performance = {}
        cookie_snapshot = _cookie_snapshot(context) if context is not None else {"cookies": [], "cookie_count": 0, "cf_cookies": {}}
    finally:
        try:
            if handle is not None:
                handle.close()
        except Exception as exc:
            page_errors.append(f"browser close: {exc}")

    challenge_seen = any(sample.get("challenge") is True for sample in challenge_samples)
    challenge_still_present = bool(final_signals.get("challenge")) if isinstance(final_signals, dict) else None
    cf_clearance = bool(cookie_snapshot.get("cf_clearance_acquired"))
    challenge_solved = bool(challenge_seen and not challenge_still_present and response_status and 200 <= response_status < 400)
    if challenge_solved:
        recorder.add("challenge_solved", evidence=["challenge_disappeared", "successful_http_response"])
    elif challenge_seen and challenge_still_present:
        recorder.add("challenge_timeout", waiting_ms=settings.wait_ms)

    outcome = _classify(
        status=response_status,
        navigation_error=navigation_error,
        timed_out=timed_out,
        challenge_seen=challenge_seen,
        challenge_still_present=challenge_still_present,
        challenge_solved=challenge_solved,
        browser_errors=page_errors + [item.get("failure", "") for item in request_failures],
    )
    reload_count = max(0, sum(1 for item in main_navigations if item.get("url") == (main_navigations[0].get("url") if main_navigations else None)) - 1)
    redirect_count = sum(1 for item in main_navigations if int(item.get("status") or 0) in range(300, 400))
    js_redirect_count = max(0, len(main_navigations) - 1 - redirect_count)
    cf_header_values = _cf_headers(final_headers)
    evaluation = {
        "experiment": "Experiment 015 - Cloudflare Evaluation",
        "run_id": run_id,
        "created_at": now_iso(),
        "url_tested": settings.url,
        "final_url": final_url,
        "http_status": response_status,
        "redirect_count": redirect_count,
        "js_redirect_count": js_redirect_count,
        "reload_count": reload_count,
        "cf_ray": cf_header_values.get("cf-ray"),
        "cf_cache_status": cf_header_values.get("cf-cache-status"),
        "server": cf_header_values.get("server"),
        "response_headers": final_headers,
        "challenge": {
            "detected": challenge_seen,
            "solved": challenge_solved,
            "timeout": bool(challenge_seen and challenge_still_present),
            "turnstile_detected": any(sample.get("turnstile") is True for sample in challenge_samples),
            "captcha_detected": any(sample.get("captcha") is True for sample in challenge_samples),
            "samples": len(challenge_samples),
        },
        "waiting_ms": settings.wait_ms,
        "challenge_duration_ms": _challenge_duration(recorder.events),
        "performance_timing": performance,
        "browser_metadata": browser_meta,
        "navigation_error": navigation_error,
        "unexpected_browser_errors": page_errors,
        "outcome": outcome,
        "cookie_acquisition": {
            "cf_clearance": cf_clearance,
            "__cf_bm": bool(cookie_snapshot.get("cf_bm_acquired")),
            "cookie_count": cookie_snapshot.get("cookie_count", 0),
        },
    }
    return {
        "evaluation": evaluation,
        "timeline": {"run_id": run_id, "events": recorder.events, "challenge_samples": challenge_samples},
        "network": {"run_id": run_id, "requests": requests, "responses": responses, "main_navigations": main_navigations},
        "cookies": {"run_id": run_id, **cookie_snapshot},
        "summary": _run_summary(evaluation),
    }


def _challenge_duration(events: list[dict[str, Any]]) -> float | None:
    detected = next((event for event in events if event.get("event") == "challenge_detected"), None)
    end = next((event for event in events if event.get("event") in {"challenge_solved", "challenge_timeout"}), None)
    if not detected or not end:
        return None
    return round(float(end.get("elapsed_ms", 0)) - float(detected.get("elapsed_ms", 0)), 2)


def _run_summary(evaluation: dict[str, Any]) -> dict[str, Any]:
    outcome = evaluation["outcome"]
    challenge = evaluation["challenge"]
    return {
        "run_id": evaluation["run_id"],
        "status": outcome["status"],
        "reason": outcome["reason"],
        "http_success": outcome["http_success"],
        "blocked": outcome["blocked"],
        "challenge_detected": challenge["detected"],
        "challenge_solved": challenge["solved"],
        "challenge_timeout": challenge["timeout"],
        "challenge_duration_ms": evaluation["challenge_duration_ms"],
        "clearance_acquired": evaluation["cookie_acquisition"]["cf_clearance"],
        "waiting_ms": evaluation["waiting_ms"],
        "browser_errors": len(evaluation["unexpected_browser_errors"]),
    }


def _aggregate_summary(run_summaries: list[dict[str, Any]], experiment_id: str) -> dict[str, Any]:
    counts = {key: sum(1 for row in run_summaries if row.get(key)) for key in (
        "http_success", "blocked", "challenge_detected", "challenge_solved", "challenge_timeout", "clearance_acquired",
    )}
    statuses = {status: sum(1 for row in run_summaries if row.get("status") == status) for status in ("PASS", "WARNING", "FAIL", "UNKNOWN")}
    durations = [row["challenge_duration_ms"] for row in run_summaries if isinstance(row.get("challenge_duration_ms"), (int, float))]
    return {
        "experiment": "Experiment 015 - Cloudflare Evaluation",
        "experiment_id": experiment_id,
        "run_count": len(run_summaries),
        "status_counts": statuses,
        "statistics": {
            **counts,
            "challenge_success_rate_pct": round(counts["challenge_solved"] / counts["challenge_detected"] * 100, 1) if counts["challenge_detected"] else None,
            "clearance_acquisition_rate_pct": round(counts["clearance_acquired"] / len(run_summaries) * 100, 1) if run_summaries else None,
            "http_success_rate_pct": round(counts["http_success"] / len(run_summaries) * 100, 1) if run_summaries else None,
            "mean_challenge_duration_ms": round(sum(durations) / len(durations), 2) if durations else None,
            "min_challenge_duration_ms": min(durations) if durations else None,
            "max_challenge_duration_ms": max(durations) if durations else None,
            "unexpected_browser_errors": sum(int(row.get("browser_errors", 0)) for row in run_summaries),
        },
        "runs": run_summaries,
        "analysis_only": True,
    }


def _render_report(
    summary: dict[str, Any],
    evaluations: list[dict[str, Any]],
    output: Path,
    timelines: list[dict[str, Any]] | None = None,
) -> str:
    timelines = timelines or []
    timeline_by_run = {str(item.get("run_id")): item for item in timelines}
    lines = [
        "# Experiment 015 - Cloudflare Evaluation",
        "",
        "Observational only: no challenge was clicked, solved, bypassed, or modified.",
        f"\nOutput: `{output}`",
        "",
        "## Runs",
        "",
        "| Run | Status | HTTP | Challenge | Solved | Clearance | Final URL | Reason |",
        "|---|---|---:|---|---|---|---|---|",
    ]
    for evaluation in evaluations:
        challenge = evaluation["challenge"]
        outcome = evaluation["outcome"]
        lines.append(
            f"| {evaluation['run_id']} | {outcome['status']} | {evaluation.get('http_status') or '-'} | "
            f"{challenge['detected']} | {challenge['solved']} | {evaluation['cookie_acquisition']['cf_clearance']} | "
            f"{evaluation.get('final_url') or '-'} | {outcome['reason']} |"
        )
    lines.extend(["", "## Timeline", ""])
    for evaluation in evaluations:
        lines.append(f"### {evaluation['run_id']}")
        lines.append("")
        lines.append("| Event | Elapsed ms | Details |")
        lines.append("|---|---:|---|")
        timeline = timeline_by_run.get(str(evaluation["run_id"]), {})
        events = timeline.get("events", []) if isinstance(timeline, dict) else []
        if not events:
            lines.append("| - | - | No lifecycle event was observed. |")
        for event in events:
            details = {key: value for key, value in event.items() if key not in {"event", "elapsed_ms", "sequence", "timestamp"}}
            detail_text = json.dumps(details, ensure_ascii=False, separators=(",", ":")) if details else "-"
            detail_text = detail_text.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {event.get('event', '-')} | {event.get('elapsed_ms', '-')} | {detail_text} |")
        lines.append("")
    lines.extend([
        "## Cookies",
        "",
        "Cookie values are redacted; presence, length, and SHA-256 are retained.",
        "",
        "| Run | Cookie count | cf_clearance | __cf_bm |",
        "|---|---:|---|---|",
    ])
    for evaluation in evaluations:
        acquisition = evaluation["cookie_acquisition"]
        lines.append(f"| {evaluation['run_id']} | {acquisition['cookie_count']} | {acquisition['cf_clearance']} | {acquisition['__cf_bm']} |")
    lines.extend([
        "",
        "## Headers",
        "",
        "| Run | cf-ray | cf-cache-status | server |",
        "|---|---|---|---|",
    ])
    for evaluation in evaluations:
        lines.append(f"| {evaluation['run_id']} | {evaluation.get('cf_ray') or '-'} | {evaluation.get('cf_cache_status') or '-'} | {evaluation.get('server') or '-'} |")
    lines.extend([
        "",
        "## Challenge Events",
        "",
        "| Run | Detected | Solved | Timeout | Turnstile | CAPTCHA | Duration ms |",
        "|---|---|---|---|---|---|---:|",
    ])
    for evaluation in evaluations:
        challenge = evaluation["challenge"]
        lines.append(f"| {evaluation['run_id']} | {challenge['detected']} | {challenge['solved']} | {challenge['timeout']} | {challenge['turnstile_detected']} | {challenge['captcha_detected']} | {evaluation['challenge_duration_ms'] or '-'} |")
    statistics = summary["statistics"]
    lines.extend([
        "",
        "## Final Outcome",
        "",
        f"PASS: **{summary['status_counts']['PASS']}**, WARNING: **{summary['status_counts']['WARNING']}**, FAIL: **{summary['status_counts']['FAIL']}**, UNKNOWN: **{summary['status_counts']['UNKNOWN']}**",
        "",
        "## Observed Risks",
        "",
        "- A FAIL indicates an observed HTTP block, challenge timeout, or browser timeout; it is not a bypass attempt.",
        "- UNKNOWN indicates that the environment did not provide a reliable HTTP outcome.",
        "- Cloudflare cookies are redacted in reports to avoid persisting clearance tokens.",
        "",
        "## Recommendations",
        "",
        "- Repeat the same URL with controlled headed/headless and persistent-profile settings.",
        "- Compare challenge and clearance rates over time; do not infer bypass success from fingerprint similarity.",
        "- Investigate only observed network/browser failures; this evaluator does not alter challenge behavior.",
        "",
        "## Statistics",
        "",
        f"Challenge success: {statistics['challenge_success_rate_pct'] if statistics['challenge_success_rate_pct'] is not None else 'N/A'}%",
        f"HTTP success: {statistics['http_success_rate_pct'] if statistics['http_success_rate_pct'] is not None else 'N/A'}%",
        f"Clearance acquired: {statistics['clearance_acquisition_rate_pct'] if statistics['clearance_acquisition_rate_pct'] is not None else 'N/A'}%",
        f"Mean challenge duration: {statistics['mean_challenge_duration_ms'] if statistics['mean_challenge_duration_ms'] is not None else 'N/A'} ms",
        "",
    ])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Experiment 015: observational Cloudflare evaluation.")
    parser.add_argument("--url", default="", help="Cloudflare-protected URL; defaults to baseline metadata URL")
    parser.add_argument("--channel", default="")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--wait", type=int, default=5_000, help="Observation window after navigation, milliseconds")
    parser.add_argument("--timeout", type=int, default=60_000, help="Navigation timeout, milliseconds")
    parser.add_argument("--runs", type=int, default=1, help="Number of immutable repeated runs in this experiment")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--no-stealth", action="store_true", help="Observe plain browser behavior instead of the active stack")
    parser.add_argument("--reports-dir", type=Path, default=None)
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    return parser


def run(settings: Settings) -> int:
    experiment = Experiment.create(settings.output)
    output = experiment.directory / "cloudflare"
    output.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for index in range(1, settings.runs + 1):
        run_id = f"run_{index:03d}"
        log.info("Cloudflare evaluation %s/%s: %s", index, settings.runs, settings.url)
        result = evaluate_run(settings, run_id)
        run_dir = output / "runs" / run_id
        write_json_exclusive(run_dir / "evaluation.json", result["evaluation"])
        write_json_exclusive(run_dir / "timeline.json", result["timeline"])
        write_json_exclusive(run_dir / "network.json", result["network"])
        write_json_exclusive(run_dir / "cookies.json", result["cookies"])
        write_json_exclusive(run_dir / "summary.json", result["summary"])
        write_text_exclusive(run_dir / "cloudflare_report.md", _render_report(
            _aggregate_summary([result["summary"]], experiment.experiment_id), [result["evaluation"]], run_dir,
            [result["timeline"]],
        ))
        runs.append(result)

    evaluations = [result["evaluation"] for result in runs]
    aggregate = _aggregate_summary([result["summary"] for result in runs], experiment.experiment_id)
    aggregate["configuration"] = {
        "url": settings.url,
        "headless": settings.headless,
        "persistent_profile": bool(settings.profile),
        "stealth_enabled": settings.use_stealth,
        "wait_ms": settings.wait_ms,
        "timeout_ms": settings.timeout_ms,
    }
    evaluation_document = {
        "experiment": "Experiment 015 - Cloudflare Evaluation",
        "experiment_id": experiment.experiment_id,
        "analysis_only": True,
        "configuration": aggregate["configuration"],
        "runs": evaluations,
    }
    timeline_document = {"experiment_id": experiment.experiment_id, "runs": [result["timeline"] for result in runs]}
    network_document = {"experiment_id": experiment.experiment_id, "runs": [result["network"] for result in runs]}
    cookies_document = {"experiment_id": experiment.experiment_id, "runs": [result["cookies"] for result in runs]}
    write_json_exclusive(output / "evaluation.json", evaluation_document)
    write_json_exclusive(output / "timeline.json", timeline_document)
    write_json_exclusive(output / "network.json", network_document)
    write_json_exclusive(output / "cookies.json", cookies_document)
    write_json_exclusive(output / "summary.json", aggregate)
    timelines = [result["timeline"] for result in runs]
    report = _render_report(aggregate, evaluations, output, timelines)
    write_text_exclusive(output / "cloudflare_report.md", report)
    print(report)
    return 0


def main() -> int:
    args = build_parser().parse_args()
    configure_console_error_handling()
    log.setLevel(getattr(logging, args.log_level))
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")
    if args.wait < 0 or args.timeout < 1:
        raise SystemExit("--wait must be non-negative and --timeout must be positive")
    root = project_root()
    baseline_path = resolve_baseline_path(root, args.baseline)
    baseline = load_baseline(baseline_path)
    reports_dir = args.reports_dir or root / "reports" / "experiments"
    if not reports_dir.is_absolute():
        reports_dir = root / reports_dir
    profile = args.profile
    if profile is not None and not profile.is_absolute():
        profile = root / profile
    settings = Settings(
        root=root,
        output=reports_dir.resolve(),
        url=args.url or str(baseline.metadata.get("url") or "about:blank"),
        channel=args.channel,
        headless=not args.no_headless,
        profile=profile.resolve() if profile else None,
        wait_ms=args.wait,
        timeout_ms=args.timeout,
        runs=args.runs,
        use_stealth=not args.no_stealth,
    )
    return run(settings)


if __name__ == "__main__":
    raise SystemExit(main())
