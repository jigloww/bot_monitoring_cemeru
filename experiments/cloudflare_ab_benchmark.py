"""Experiment 017: real Cloudflare browser-mode A/B benchmark.

The benchmark measures observable navigation behavior only.  It never clicks
or solves a challenge, injects a CAPTCHA response, or treats fingerprint
similarity as evidence of success.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    read_json,
    write_json_exclusive,
    write_text_exclusive,
)


MODES = ("plain", "playwright_stealth", "local_stealth", "chrome_cdp")
MODE_LABELS = {
    "plain": "Plain Playwright (Chromium)",
    "playwright_stealth": "Playwright + playwright-stealth",
    "local_stealth": "Local Stealth Framework",
    "chrome_cdp": "Real Chrome via CDP",
}
CHALLENGE_TEXT = (
    "just a moment", "tunggu sebentar", "verify you are human",
    "checking your browser", "please wait", "security check",
)
CF_COOKIE_NAMES = {"cf_clearance", "__cf_bm", "cf_chl_2", "cf_chl_prog", "cf_chl_rc_ni"}


@dataclass(frozen=True)
class Settings:
    root: Path
    output: Path
    url: str
    runs: int
    timeout_ms: int
    wait_ms: int
    headless: bool
    profile: Path | None
    cdp_url: str | None


def _status(status: str, reason: str, *, value: Any = None, error: str | None = None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "value": value, "error": error}


def _page_signals(page: Any) -> dict[str, Any]:
    try:
        value = page.evaluate("""() => {
          const title=String(document.title||'');
          const body=String(document.body?document.body.innerText||'':'').slice(0,12000);
          const html=String(document.documentElement?document.documentElement.innerHTML||'':'').slice(0,30000);
          const lower=(title+'\\n'+body+'\\n'+html).toLowerCase();
          const text=/just a moment|tunggu sebentar|verify you are human|checking your browser|please wait|security check/.test(lower);
          const nodes=!!document.querySelector('#challenge-running,#challenge-stage,#cf-challenge-running,[name="cf-turnstile-response"],iframe[src*="challenges.cloudflare.com"]');
          const turnstile=!!document.querySelector('.cf-turnstile,[data-sitekey],iframe[src*="challenges.cloudflare.com/turnstile"],[name="cf-turnstile-response"]');
          const captcha=!!document.querySelector('[id*="captcha" i],[class*="captcha" i],iframe[src*="recaptcha"],iframe[src*="hcaptcha"]');
          return {title,challenge:text||nodes,turnstile,captcha,url:location.href};
        }""")
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        return {"challenge": None, "turnstile": None, "captcha": None, "error": str(exc)}


def _cookies(context: Any) -> dict[str, Any]:
    try:
        values = context.cookies()
    except Exception as exc:
        return {"count": 0, "cf_clearance": False, "__cf_bm": False, "names": [], "error": str(exc)}
    names = [str(cookie.get("name")) for cookie in values if isinstance(cookie, dict)]
    return {
        "count": len(values),
        "names": names,
        "cf_clearance": any(cookie.get("name") == "cf_clearance" and cookie.get("value") for cookie in values if isinstance(cookie, dict)),
        "__cf_bm": any(cookie.get("name") == "__cf_bm" and cookie.get("value") for cookie in values if isinstance(cookie, dict)),
        "cf_cookie_names": sorted(name for name in names if name in CF_COOKIE_NAMES),
    }


def _classification(status: int | None, error: str | None, challenge: bool, timed_out: bool) -> dict[str, Any]:
    if timed_out:
        return _status("FAIL", "Navigation timeout observed.")
    if error and status is None:
        return _status("UNKNOWN", "No HTTP outcome was observed after navigation error.", error=error)
    if status is None:
        return _status("UNKNOWN", "No main-document HTTP response was observed.")
    if 200 <= status < 400 and not challenge:
        return _status("PASS", "Navigation completed without an observed challenge.")
    if 200 <= status < 400 and challenge:
        return _status("WARNING", "Navigation completed while a challenge was observed.")
    if status in {401, 403, 429, 503, 520, 521, 522, 523, 524}:
        return _status("WARNING", f"Cloudflare/site returned challenge-like HTTP status {status}.")
    if status >= 400:
        return _status("WARNING", f"Target returned HTTP status {status}.")
    return _status("UNKNOWN", "Outcome could not be classified.")


def _modules_for_local_stack(settings: Settings) -> list[str]:
    if not settings.root.joinpath("stealth").is_dir():
        return []
    try:
        from stealth.registry import get_default_registry
        return [module.name for module in get_default_registry().modules if module.enabled and module.js_file.exists()]
    except Exception:
        return []


def _apply_mode(page: Any, mode: str, settings: Settings) -> tuple[list[str], str | None]:
    if mode == "plain":
        return [], None
    if mode == "playwright_stealth":
        if importlib.util.find_spec("playwright_stealth") is None:
            return [], "playwright-stealth package is not installed"
        try:
            import playwright_stealth  # type: ignore
            if hasattr(playwright_stealth, "stealth_sync"):
                playwright_stealth.stealth_sync(page)
            elif hasattr(playwright_stealth, "Stealth"):
                stealth = playwright_stealth.Stealth()
                if hasattr(stealth, "apply_stealth_sync"):
                    stealth.apply_stealth_sync(page)
                else:
                    return [], "installed playwright-stealth API has no synchronous apply method"
            else:
                return [], "installed playwright-stealth API is unsupported"
            return ["playwright-stealth"], None
        except Exception as exc:
            return [], f"playwright-stealth apply failed: {exc}"
    if mode == "local_stealth":
        try:
            from stealth import apply_stealth
            apply_stealth(page)
            return _modules_for_local_stack(settings), None
        except Exception as exc:
            return [], f"local stealth apply failed: {exc}"
    return [], None


def _run_navigation(page: Any, context: Any, settings: Settings, mode: str, run_id: str, browser_version: str | None, playwright_version: str, modules: list[str], mode_error: str | None) -> dict[str, Any]:
    started = time.perf_counter()
    responses: list[dict[str, Any]] = []
    request_failures: list[dict[str, Any]] = []
    response_failures: list[dict[str, Any]] = []
    console_errors: list[dict[str, Any]] = []
    page_errors: list[str] = []
    frame_urls: list[str] = []
    crashed = False
    main_response: Any = None
    timeline: list[dict[str, Any]] = []

    def event(name: str, **details: Any) -> None:
        timeline.append({"sequence": len(timeline) + 1, "event": name, "timestamp": now_iso(), "elapsed_ms": round((time.perf_counter() - started) * 1000, 2), **details})

    def on_response(response: Any) -> None:
        nonlocal main_response
        headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        item = {"url": response.url, "status": response.status, "resource_type": response.request.resource_type, "headers": headers, "is_navigation": response.request.is_navigation_request()}
        responses.append(item)
        if response.status >= 400:
            response_failures.append({"url": response.url, "status": response.status, "resource_type": response.request.resource_type})
        if response.request.is_navigation_request() and response.request.resource_type == "document":
            main_response = response
            event("http_response", url=response.url, status=response.status)

    def on_request_failed(request: Any) -> None:
        request_failures.append({"url": request.url, "resource_type": request.resource_type, "failure": request.failure})
        event("request_failure", url=request.url, failure=request.failure)

    def on_crash() -> None:
        nonlocal crashed
        crashed = True
        event("browser_crash")

    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)
    page.on("console", lambda message: console_errors.append({"type": message.type, "text": message.text[:1500]}) if message.type == "error" else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("crash", on_crash)
    page.on("framenavigated", lambda frame: frame_urls.append(frame.url) if frame == page.main_frame else None)

    event("navigation_start", url=settings.url)
    if mode_error:
        event("mode_unavailable", error=mode_error)
    navigation_error: str | None = mode_error
    timed_out = False
    if not mode_error:
        try:
            page.goto(settings.url, wait_until="domcontentloaded", timeout=settings.timeout_ms)
        except Exception as exc:
            navigation_error = str(exc)
            timed_out = "timeout" in navigation_error.lower()
            event("navigation_error", error=navigation_error, timeout=timed_out)
    waited = 0
    samples: list[dict[str, Any]] = []
    while waited < settings.wait_ms and not mode_error:
        try:
            page.wait_for_timeout(min(250, settings.wait_ms - waited))
            signal = _page_signals(page)
            signal["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
            samples.append(signal)
            if signal.get("challenge") and not any(item.get("challenge") for item in samples[:-1]):
                event("challenge_detected", url=signal.get("url"), title=signal.get("title"))
            if signal.get("turnstile") and not any(item.get("turnstile") for item in samples[:-1]):
                event("turnstile_detected", url=signal.get("url"))
            if signal.get("captcha") and not any(item.get("captcha") for item in samples[:-1]):
                event("captcha_detected", url=signal.get("url"))
        except Exception as exc:
            event("observation_error", error=str(exc))
            break
        waited += 250
    final_signal = _page_signals(page) if not mode_error else {}
    samples.append(final_signal)
    challenge_detected = any(item.get("challenge") is True for item in samples)
    challenge_still_present = bool(final_signal.get("challenge")) if isinstance(final_signal, dict) else False
    challenge_started = next((item.get("elapsed_ms") for item in timeline if item.get("event") == "challenge_detected"), None)
    challenge_duration = round((time.perf_counter() - started) * 1000 - float(challenge_started), 2) if challenge_started is not None and not challenge_still_present else None
    status = main_response.status if main_response is not None else None
    final_url = page.url
    headers = {str(key).lower(): str(value) for key, value in main_response.headers.items()} if main_response is not None else {}
    redirects = 0
    if main_response is not None:
        request = main_response.request.redirected_from
        while request is not None:
            redirects += 1
            request = request.redirected_from
    event("navigation_end", url=final_url, status=status)
    cookies = _cookies(context)
    result = _classification(status, navigation_error, challenge_detected, timed_out)
    if settings.url == "about:blank" and status is None and navigation_error is None and not mode_error:
        result = _status("PASS", "about:blank opened successfully; no HTTP response is expected.")
    if crashed:
        result = _status("FAIL", "Browser crash observed during navigation.")
    if mode_error:
        result = _status("UNKNOWN", "Benchmark mode unavailable in this environment.", error=mode_error)
    return {
        "run_id": run_id,
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "timestamp": now_iso(),
        "url": settings.url,
        "navigation_success": result["status"] == "PASS",
        "http_status": status,
        "redirect_count": redirects,
        "js_redirect_count": max(0, len(frame_urls) - 1 - redirects),
        "challenge_detected": challenge_detected,
        "challenge_duration_ms": challenge_duration,
        "challenge_timeout": bool(challenge_detected and challenge_still_present and waited >= settings.wait_ms),
        "turnstile_detected": any(item.get("turnstile") is True for item in samples),
        "captcha_detected": any(item.get("captcha") is True for item in samples),
        "cf_clearance_acquired": cookies["cf_clearance"],
        "__cf_bm_acquired": cookies["__cf_bm"],
        "cookie_count": cookies["count"],
        "cf_cookie_names": cookies["cf_cookie_names"],
        "console_errors": console_errors[:100],
        "request_failures": request_failures[:100],
        "response_failures": response_failures[:100],
        "browser_crashed": crashed,
        "navigation_timeout": timed_out,
        "final_url": final_url,
        "elapsed_time_ms": round((time.perf_counter() - started) * 1000, 2),
        "browser_version": browser_version,
        "playwright_version": playwright_version,
        "stealth_modules_enabled": modules,
        "headless": settings.headless,
        "persistent_profile": bool(settings.profile),
        "response_headers": headers,
        "outcome": result,
        "timeline": timeline,
        "samples": samples,
    }


def _launch_mode(settings: Settings, mode: str, run_id: str, playwright: Any, playwright_version: str) -> dict[str, Any]:
    if mode == "chrome_cdp":
        if not settings.cdp_url:
            return _run_unavailable(settings, mode, run_id, playwright_version, "No --cdp-url supplied")
        try:
            browser = playwright.chromium.connect_over_cdp(settings.cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            result = _run_navigation(page, context, settings, mode, run_id, getattr(browser, "version", None), playwright_version, ["real-chrome-cdp"], None)
            page.close()
            return result
        except Exception as exc:
            return _run_unavailable(settings, mode, run_id, playwright_version, f"CDP connection failed: {exc}")

    from playwright.sync_api import Error as PlaywrightError
    browser = None
    context = None
    try:
        args = ["--disable-dev-shm-usage"]
        if settings.profile is None:
            args.append("--no-sandbox")
        if settings.profile:
            context = playwright.chromium.launch_persistent_context(str(settings.profile), headless=settings.headless, args=args)
            page = context.pages[0] if context.pages else context.new_page()
            browser_version = context.browser.version if context.browser else None
        else:
            browser = playwright.chromium.launch(headless=settings.headless, args=args)
            context = browser.new_context()
            page = context.new_page()
            browser_version = browser.version
        modules, mode_error = _apply_mode(page, mode, settings)
        result = _run_navigation(page, context, settings, mode, run_id, browser_version, playwright_version, modules, mode_error)
        context.close()
        if browser is not None:
            browser.close()
        return result
    except Exception as exc:
        try:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()
        except Exception:
            pass
        return _run_unavailable(settings, mode, run_id, playwright_version, f"Browser mode failed: {exc}")


def _run_unavailable(settings: Settings, mode: str, run_id: str, playwright_version: str, error: str) -> dict[str, Any]:
    result = _classification(None, error, False, False)
    result = _status("UNKNOWN", "Benchmark mode unavailable in this environment.", error=error)
    return {
        "run_id": run_id, "mode": mode, "mode_label": MODE_LABELS[mode], "timestamp": now_iso(), "url": settings.url,
        "navigation_success": False, "http_status": None, "redirect_count": 0, "js_redirect_count": 0,
        "challenge_detected": False, "challenge_duration_ms": None, "challenge_timeout": False,
        "turnstile_detected": False, "captcha_detected": False, "cf_clearance_acquired": False, "__cf_bm_acquired": False,
        "cookie_count": 0, "cf_cookie_names": [], "console_errors": [], "request_failures": [], "response_failures": [],
        "browser_crashed": False, "navigation_timeout": False, "final_url": None, "elapsed_time_ms": None,
        "browser_version": None, "playwright_version": playwright_version, "stealth_modules_enabled": [],
        "headless": settings.headless, "persistent_profile": bool(settings.profile), "response_headers": {}, "outcome": result,
        "timeline": [{"sequence": 1, "event": "mode_unavailable", "timestamp": now_iso(), "elapsed_ms": 0, "error": error}], "samples": [],
    }


def _stats(records: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    total = len(records)
    statuses = {status: sum(1 for record in records if record.get("outcome", {}).get("status") == status) for status in ("PASS", "WARNING", "FAIL", "UNKNOWN")}
    challenges = sum(bool(record.get("challenge_detected")) for record in records)
    solved = sum(bool(record.get("challenge_detected") and not record.get("challenge_timeout")) for record in records)
    durations = [record["challenge_duration_ms"] for record in records if isinstance(record.get("challenge_duration_ms"), (int, float))]
    elapsed = [record["elapsed_time_ms"] for record in records if isinstance(record.get("elapsed_time_ms"), (int, float))]
    redirects = [record.get("redirect_count", 0) for record in records]
    classification = "UNUSABLE"
    success_rate = statuses["PASS"] / total if total else 0
    if total and success_rate >= 0.9 and statuses["FAIL"] == 0 and sum(record.get("browser_crashed", False) for record in records) == 0:
        classification = "BEST"
    elif total and success_rate >= 0.7:
        classification = "GOOD"
    elif total and success_rate >= 0.3:
        classification = "NEUTRAL"
    elif total and statuses["PASS"] > 0:
        classification = "POOR"
    return {
        "mode": mode, "mode_label": MODE_LABELS[mode], "run_count": total, "status_counts": statuses,
        "success_rate_pct": round(success_rate * 100, 1), "challenge_rate_pct": round(challenges / total * 100, 1) if total else 0.0,
        "clearance_acquisition_rate_pct": round(sum(record.get("cf_clearance_acquired", False) for record in records) / total * 100, 1) if total else 0.0,
        "average_challenge_duration_ms": round(sum(durations) / len(durations), 2) if durations else None,
        "average_navigation_time_ms": round(sum(elapsed) / len(elapsed), 2) if elapsed else None,
        "average_redirects": round(sum(redirects) / len(redirects), 2) if redirects else 0.0,
        "failure_rate_pct": round((statuses["FAIL"] + statuses["WARNING"]) / total * 100, 1) if total else 0.0,
        "crash_rate_pct": round(sum(record.get("browser_crashed", False) for record in records) / total * 100, 1) if total else 0.0,
        "timeout_rate_pct": round(sum(record.get("navigation_timeout", False) for record in records) / total * 100, 1) if total else 0.0,
        "cookie_acquisition_rate_pct": round(sum(record.get("cookie_count", 0) > 0 for record in records) / total * 100, 1) if total else 0.0,
        "challenge_success_rate_pct": round(solved / challenges * 100, 1) if challenges else None,
        "classification": classification,
    }


def _render_report(summary: dict[str, Any], records: list[dict[str, Any]], stats: dict[str, Any], output: Path) -> str:
    lines = [
        "# Experiment 017 - Real Cloudflare A/B Benchmark",
        "",
        "Benchmark-only report. No challenge or CAPTCHA was solved or bypassed.",
        f"\nOutput: `{output}`",
        "",
        "## Per Mode",
        "",
        "| Mode | Classification | Success | Challenge | Clearance | Avg Nav ms | Avg Challenge ms | Failure | Crash | Timeout |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        item = stats.get(mode, {})
        lines.append(f"| {MODE_LABELS[mode]} | {item.get('classification','UNUSABLE')} | {item.get('success_rate_pct',0)}% | {item.get('challenge_rate_pct',0)}% | {item.get('clearance_acquisition_rate_pct',0)}% | {item.get('average_navigation_time_ms') or '-'} | {item.get('average_challenge_duration_ms') or '-'} | {item.get('failure_rate_pct',0)}% | {item.get('crash_rate_pct',0)}% | {item.get('timeout_rate_pct',0)}% |")
    lines.extend(["", "## Per Run", "", "| Run | Mode | Outcome | HTTP | Challenge | Clearance | Cookies | Elapsed ms | Final URL |", "|---|---|---|---:|---|---|---:|---:|---|"])
    for record in records:
        lines.append(f"| {record['run_id']} | {MODE_LABELS[record['mode']]} | {record['outcome']['status']} | {record.get('http_status') or '-'} | {record.get('challenge_detected')} | {record.get('cf_clearance_acquired')} | {record.get('cookie_count',0)} | {record.get('elapsed_time_ms') or '-'} | {record.get('final_url') or '-'} |")
    lines.extend(["", "## Overall Ranking", "", "| Rank | Mode | Classification | Success rate | Reason |", "|---:|---|---|---:|---|"])
    ranking = sorted(stats.values(), key=lambda item: (item.get("success_rate_pct", 0), -item.get("failure_rate_pct", 100), -item.get("crash_rate_pct", 100)), reverse=True)
    for index, item in enumerate(ranking, 1):
        lines.append(f"| {index} | {item.get('mode_label')} | {item.get('classification')} | {item.get('success_rate_pct',0)}% | {item.get('status_counts')} |")
    lines.extend([
        "", "## Interpretation", "",
        f"Total runs: **{summary['run_count']}**; PASS: **{summary['status_counts']['PASS']}**, WARNING: **{summary['status_counts']['WARNING']}**, FAIL: **{summary['status_counts']['FAIL']}**, UNKNOWN: **{summary['status_counts']['UNKNOWN']}**.",
        "",
        "UNKNOWN means the environment did not provide a reliable HTTP outcome. It is not evidence that stealth succeeded or failed.",
        "",
        "## Recommendations", "",
        "Repeat the benchmark from a permitted network, keep the target and browser settings identical, and compare observed challenge/clearance rates rather than fingerprint similarity.",
        "",
    ])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Experiment 017: Cloudflare A/B benchmark.")
    parser.add_argument("--url", default="", help="Cloudflare-protected target URL")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=30_000)
    parser.add_argument("--wait", type=int, default=5_000)
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--cdp-url", default=None, help="Optional Chrome DevTools URL")
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def run(settings: Settings) -> int:
    experiment = Experiment.create(settings.output)
    output = experiment.directory / "ab_benchmark"
    output.mkdir(parents=True, exist_ok=True)
    try:
        playwright_version = importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError:
        playwright_version = "unknown"
    records: list[dict[str, Any]] = []
    for index in range(1, settings.runs + 1):
        for mode in MODES:
            run_id = f"run_{index:03d}_{mode}"
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                record = _launch_mode(settings, mode, run_id, playwright, playwright_version)
            run_dir = output / "runs" / run_id
            write_json_exclusive(run_dir / "run.json", record)
            write_json_exclusive(run_dir / "timeline.json", {"run_id": run_id, "events": record.get("timeline", []), "samples": record.get("samples", [])})
            records.append(record)
    stats = {mode: _stats([record for record in records if record["mode"] == mode], mode) for mode in MODES}
    summary = {
        "experiment": "Experiment 017 - Real Cloudflare A/B Benchmark", "experiment_id": experiment.experiment_id, "created_at": now_iso(), "analysis_only": True,
        "target_url": settings.url, "run_count": len(records), "mode_count": len(MODES), "status_counts": {status: sum(1 for record in records if record["outcome"]["status"] == status) for status in ("PASS", "WARNING", "FAIL", "UNKNOWN")},
        "ranking": [item["mode"] for item in sorted(stats.values(), key=lambda item: (item["success_rate_pct"], -item["failure_rate_pct"]), reverse=True)], "statistics": stats,
        "configuration": {"runs_per_mode": settings.runs, "timeout_ms": settings.timeout_ms, "wait_ms": settings.wait_ms, "headless": settings.headless, "persistent_profile": bool(settings.profile), "cdp_configured": bool(settings.cdp_url)},
    }
    benchmark = {"experiment": summary["experiment"], "experiment_id": experiment.experiment_id, "modes": [{"mode": mode, "label": MODE_LABELS[mode], "optional": mode == "chrome_cdp"} for mode in MODES], "configuration": summary["configuration"]}
    write_json_exclusive(output / "benchmark.json", benchmark)
    write_json_exclusive(output / "runs.json", {"experiment_id": experiment.experiment_id, "runs": records})
    write_json_exclusive(output / "statistics.json", {"experiment_id": experiment.experiment_id, "modes": stats})
    write_json_exclusive(output / "timeline.json", {"experiment_id": experiment.experiment_id, "runs": [{"run_id": record["run_id"], "events": record.get("timeline", []), "samples": record.get("samples", [])} for record in records]})
    write_json_exclusive(output / "summary.json", summary)
    report = _render_report(summary, records, stats, output)
    write_text_exclusive(output / "benchmark_report.md", report)
    print(report)
    return 0


def main() -> int:
    args = build_parser().parse_args()
    configure_console_error_handling()
    if args.runs < 1 or args.timeout < 1 or args.wait < 0:
        raise SystemExit("--runs must be >=1, --timeout positive, and --wait non-negative")
    root = project_root()
    reports_dir = args.reports_dir or root / "reports" / "experiments"
    if not reports_dir.is_absolute():
        reports_dir = root / reports_dir
    target = args.url
    if not target:
        baseline = root / "reports" / "fingerprint" / "fingerprint_real.json"
        try:
            target = str(read_json(baseline).get("_meta", {}).get("url") or "about:blank")
        except Exception:
            target = "about:blank"
    profile = args.profile
    if profile is not None and not profile.is_absolute():
        profile = root / profile
    settings = Settings(root=root, output=reports_dir.resolve(), url=target, runs=args.runs, timeout_ms=args.timeout, wait_ms=args.wait, headless=not args.no_headless, profile=profile.resolve() if profile else None, cdp_url=args.cdp_url)
    return run(settings)


if __name__ == "__main__":
    raise SystemExit(main())
