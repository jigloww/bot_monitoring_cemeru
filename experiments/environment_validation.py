"""Experiment 016: diagnostic environment validation.

The evaluator answers a narrower question than fingerprint scoring: can this
host launch the requested browser, resolve and connect to representative
origins, persist browser state, and reach Cloudflare-protected domains?  It
does not alter stealth code or interact with a challenge.
"""
from __future__ import annotations

import argparse
import http.client
import http.server
import importlib.metadata
import json
import locale
import os
import platform
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
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
    now_iso,
    project_root,
    relative_path,
    write_json_exclusive,
    write_text_exclusive,
)


TARGET_URLS = (
    "https://www.google.com/",
    "https://cloudflare.com/",
    "https://github.com/",
    "https://bromotenggersemeru.id/",
)
STATUS_VALUES = ("PASS", "WARNING", "FAIL", "UNKNOWN")


@dataclass(frozen=True)
class Settings:
    root: Path
    output: Path
    urls: tuple[str, ...]
    channel: str
    headless: bool
    profile: Path | None
    timeout_ms: int
    wait_ms: int
    sandbox: bool


def _result(status: str, value: Any = None, *, error: str | None = None,
            root_cause: str | None = None, confidence: str = "Medium",
            recommendation: str = "") -> dict[str, Any]:
    if status not in STATUS_VALUES:
        raise ValueError(f"Unknown diagnostic status: {status}")
    return {
        "status": status,
        "value": value,
        "error": error,
        "root_cause": root_cause,
        "confidence": confidence,
        "recommendation": recommendation,
    }


def _run_command(command: list[str], timeout: float = 3.0) -> str | None:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        output = (completed.stdout or completed.stderr).strip()
        return output or None
    except (OSError, subprocess.SubprocessError):
        return None


def _memory_info() -> dict[str, Any]:
    try:
        import psutil  # type: ignore
        memory = psutil.virtual_memory()
        return {"total_bytes": memory.total, "available_bytes": memory.available, "used_bytes": memory.used, "percent": memory.percent, "source": "psutil"}
    except Exception:
        pass
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                values[parts[0].rstrip(":")] = int(parts[1]) * 1024
        if values:
            total, available = values.get("MemTotal"), values.get("MemAvailable")
            return {"total_bytes": total, "available_bytes": available, "used_bytes": total - available if total and available else None, "source": "/proc/meminfo"}
    return {"total_bytes": None, "available_bytes": None, "used_bytes": None, "source": "unavailable"}


def _disk_info(root: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(root)
        return {"path": str(root), "total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free, "percent_used": round(usage.used / usage.total * 100, 2) if usage.total else None}
    except OSError as exc:
        return {"path": str(root), "error": str(exc)}


def _font_inventory() -> dict[str, Any]:
    candidates: list[Path] = []
    if os.name == "nt":
        candidates.extend([Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts"])
    else:
        candidates.extend([Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts", Path.home() / ".local/share/fonts"])
    files: list[str] = []
    seen: set[str] = set()
    for directory in candidates:
        if not directory.is_dir():
            continue
        try:
            for path in directory.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".ttf", ".otf", ".ttc", ".woff", ".woff2"}:
                    key = str(path.resolve()).lower()
                    if key not in seen:
                        seen.add(key)
                        files.append(path.name)
        except OSError:
            continue
    files.sort(key=str.lower)
    return {"search_paths": [str(path) for path in candidates], "count": len(files), "sample": files[:200]}


def _executable_paths() -> dict[str, Any]:
    names = ["chrome", "chrome.exe", "chromium", "chromium-browser", "google-chrome", "msedge", "Xvfb"]
    found = {name: shutil.which(name) for name in names}
    common_windows = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    found["common_browser_paths"] = [str(path) for path in common_windows if path.is_file()]
    return found


def collect_system(settings: Settings) -> dict[str, Any]:
    uname = platform.uname()
    try:
        playwright_version = importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError:
        playwright_version = None
    try:
        locale_value = locale.getlocale()
    except Exception:
        locale_value = (None, None)
    tz = datetime.now().astimezone()
    display = os.environ.get("DISPLAY")
    dbus_socket = Path("/var/run/dbus/system_bus_socket")
    return {
        "timestamp": now_iso(),
        "os": {"system": platform.system(), "release": platform.release(), "version": platform.version(), "kernel": uname.release, "machine": uname.machine, "architecture": platform.architecture()[0]},
        "cpu": {"logical_count": os.cpu_count(), "processor": platform.processor()},
        "memory": _memory_info(),
        "disk": _disk_info(settings.root),
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation(), "executable": sys.executable},
        "playwright_version": playwright_version,
        "executables": _executable_paths(),
        "fonts": _font_inventory(),
        "timezone": {"name": tz.tzname(), "offset_seconds": tz.utcoffset().total_seconds() if tz.utcoffset() else None},
        "locale": {"default": locale_value, "environment": {key: os.environ.get(key) for key in ("LANG", "LC_ALL", "LC_CTYPE") if os.environ.get(key)}},
        "display": {"DISPLAY": display, "xvfb": shutil.which("Xvfb"), "xvfb_running": bool(display and shutil.which("xdpyinfo"))},
        "dbus": {"socket": str(dbus_socket), "available": dbus_socket.exists() or bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))},
        "browser_configuration": {"headless": settings.headless, "headed": not settings.headless, "persistent_profile": bool(settings.profile), "profile_path": str(settings.profile) if settings.profile else None, "sandbox_requested": settings.sandbox, "sandbox_flag": "--no-sandbox" if not settings.sandbox else None},
    }


def _dns_check(url: str, timeout: float) -> dict[str, Any]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    started = time.perf_counter()
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        ips = sorted({item[4][0] for item in addresses})
        return _result("PASS", {"host": host, "addresses": ips, "latency_ms": round((time.perf_counter() - started) * 1000, 2)}, confidence="High", recommendation="No DNS action required.")
    except socket.gaierror as exc:
        return _result("FAIL", {"host": host}, error=str(exc), root_cause="DNS", confidence="High", recommendation="Check resolver configuration and DNS egress.")
    except Exception as exc:
        return _result("UNKNOWN", {"host": host}, error=str(exc), root_cause="Network", confidence="Medium", recommendation="Repeat the DNS check outside the restricted environment.")


def _socket_check(url: str, timeout: float) -> dict[str, Any]:
    parsed = urlparse(url)
    host, port = parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80)
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return _result("PASS", {"host": host, "port": port, "latency_ms": round((time.perf_counter() - started) * 1000, 2)}, confidence="High", recommendation="Socket connectivity is available.")
    except socket.timeout as exc:
        return _result("FAIL", {"host": host, "port": port}, error=str(exc), root_cause="Network", confidence="High", recommendation="Check firewall, egress policy, and route latency.")
    except OSError as exc:
        return _result("UNKNOWN", {"host": host, "port": port}, error=str(exc), root_cause="Network", confidence="Medium", recommendation="Check network egress and resolver results.")


def _http_check(url: str, timeout: float, method: str = "HEAD") -> dict[str, Any]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    started = time.perf_counter()
    connection: Any = None
    try:
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            connection = http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
        else:
            connection = http.client.HTTPConnection(host, port, timeout=timeout)
        connection.request(method, parsed.path or "/", headers={"User-Agent": "cemeru-environment-validator/1.0", "Accept": "*/*"})
        response = connection.getresponse()
        headers = {str(key).lower(): str(value) for key, value in response.getheaders()}
        response.read(4096)
        status = response.status
        classification = "PASS" if 200 <= status < 400 else "WARNING" if status < 500 else "FAIL"
        return _result(classification, {"url": url, "status": status, "reason": response.reason, "headers": headers, "latency_ms": round((time.perf_counter() - started) * 1000, 2), "redirect": headers.get("location")}, root_cause="Cloudflare" if "cf-ray" in headers or "cloudflare" in headers.get("server", "").lower() else ("HTTP server" if status >= 400 else None), confidence="High", recommendation="Inspect HTTP status and response headers." if status >= 400 else "No HTTP action required.")
    except ssl.SSLCertVerificationError as exc:
        return _result("FAIL", {"url": url}, error=str(exc), root_cause="TLS", confidence="High", recommendation="Check system trust store, clock, proxy interception, and certificate chain.")
    except (socket.timeout, TimeoutError) as exc:
        return _result("FAIL", {"url": url}, error=str(exc), root_cause="Network", confidence="High", recommendation="Check egress firewall and latency.")
    except OSError as exc:
        return _result("UNKNOWN", {"url": url}, error=str(exc), root_cause="Network", confidence="Medium", recommendation="Repeat from an unrestricted network.")
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def collect_network(settings: Settings) -> dict[str, Any]:
    urls = list(settings.urls)
    https_checks = {url: _http_check(url, settings.timeout_ms / 1000) for url in urls}
    http_url = "http://example.com/"
    checks = {
        "dns": {url: _dns_check(url, settings.timeout_ms / 1000) for url in urls},
        "socket_https": {url: _socket_check(url, settings.timeout_ms / 1000) for url in urls},
        "https_connectivity": https_checks,
        "http_connectivity": {http_url: _http_check(http_url, settings.timeout_ms / 1000)},
        "certificate_validation": {url: check for url, check in https_checks.items()},
        "redirect_support": {url: {"status": check["status"], "redirect": (check.get("value") or {}).get("redirect") if isinstance(check.get("value"), dict) else None} for url, check in https_checks.items()},
    }
    flat = [check for group in checks.values() for check in group.values()]
    statuses = {status: sum(1 for check in flat if check.get("status") == status) for status in STATUS_VALUES}
    return {"timestamp": now_iso(), "checks": checks, "status_counts": statuses, "latency_ms": {url: (item.get("value") or {}).get("latency_ms") if isinstance(item.get("value"), dict) else None for url, item in https_checks.items()}}


def _browser_result_status(response_status: int | None, error: str | None, url: str, headers: dict[str, str]) -> dict[str, Any]:
    if url == "about:blank" and response_status is None and not error:
        return _result("PASS", {"url": url, "status": None}, confidence="High", recommendation="about:blank opened successfully.")
    if error and response_status is None:
        return _result("UNKNOWN", {"url": url, "status": response_status}, error=error, root_cause="Network" if "ERR_" in error else "Browser", confidence="Medium", recommendation="Repeat the navigation with network access and inspect browser logs.")
    if response_status is None:
        return _result("UNKNOWN", {"url": url, "status": None}, root_cause="Browser", confidence="Low", recommendation="Repeat navigation and capture a main-document response.")
    if 200 <= response_status < 400:
        return _result("PASS", {"url": url, "status": response_status}, confidence="High", recommendation="No browser navigation action required.")
    if "cf-ray" in headers or "cloudflare" in headers.get("server", "").lower():
        return _result("WARNING", {"url": url, "status": response_status}, root_cause="Cloudflare", confidence="High", recommendation="Treat the response as Cloudflare/site behavior, not a fingerprint score.")
    return _result("WARNING", {"url": url, "status": response_status}, root_cause="HTTP server", confidence="Medium", recommendation="Inspect the target server response and redirect policy.")


def _visit(page: Any, url: str, timeout_ms: int, wait_ms: int) -> dict[str, Any]:
    started = time.perf_counter()
    responses: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    console: list[dict[str, Any]] = []
    page_errors: list[str] = []
    frame_urls: list[str] = []
    main_response: Any = None

    def on_response(response: Any) -> None:
        nonlocal main_response
        headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        item = {"url": response.url, "status": response.status, "status_text": response.status_text, "resource_type": response.request.resource_type, "headers": headers, "is_navigation": response.request.is_navigation_request()}
        responses.append(item)
        if response.request.is_navigation_request() and response.request.resource_type == "document":
            main_response = response

    def on_request_failed(request: Any) -> None:
        failures.append({"url": request.url, "resource_type": request.resource_type, "failure": request.failure})

    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)
    page.on("console", lambda message: console.append({"type": message.type, "text": message.text[:1000]}))
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("framenavigated", lambda frame: frame_urls.append(frame.url) if frame == page.main_frame else None)
    navigation_error: str | None = None
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as exc:
        navigation_error = str(exc)
    if wait_ms > 0:
        try:
            page.wait_for_timeout(wait_ms)
        except Exception as exc:
            navigation_error = navigation_error or str(exc)
    final_url = page.url
    status = main_response.status if main_response is not None else None
    headers = {str(key).lower(): str(value) for key, value in main_response.headers.items()} if main_response is not None else {}
    redirect_count = 0
    if main_response is not None:
        request = main_response.request.redirected_from
        while request is not None:
            redirect_count += 1
            request = request.redirected_from
    try:
        timing = page.evaluate("""() => { const n=performance.getEntriesByType('navigation')[0]; const p=performance.getEntriesByName('first-contentful-paint')[0]; return {timeOrigin:performance.timeOrigin, firstContentfulPaint:p?p.startTime:null, navigation:n?{duration:n.duration,domContentLoadedEventEnd:n.domContentLoadedEventEnd,loadEventEnd:n.loadEventEnd,redirectCount:n.redirectCount,type:n.type}:null}; }""")
    except Exception as exc:
        timing = {"error": str(exc)}
    return {
        "url": url,
        "final_url": final_url,
        "http_status": status,
        "response_headers": headers,
        "cf_headers": {name: headers.get(name) for name in ("cf-ray", "cf-cache-status", "server")},
        "redirect_count": redirect_count,
        "js_redirect_count": max(0, len(frame_urls) - 1 - redirect_count),
        "navigation_time_ms": round((time.perf_counter() - started) * 1000, 2),
        "responses": responses[:500],
        "request_failures": failures[:100],
        "console": console[:100],
        "page_errors": page_errors[:100],
        "navigation_error": navigation_error,
        "performance_timing": timing,
        "result": _browser_result_status(status, navigation_error, url, headers),
    }


def _webgl_probe(page: Any) -> dict[str, Any]:
    try:
        value = page.evaluate("""() => { const c=document.createElement('canvas'); const gl=c.getContext('webgl')||c.getContext('experimental-webgl'); if(!gl) return {available:false}; const ext=gl.getExtension('WEBGL_debug_renderer_info'); const vendor=ext?gl.getParameter(ext.UNMASKED_VENDOR_WEBGL):gl.getParameter(gl.VENDOR); const renderer=ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER); return {available:true,vendor,renderer,version:gl.getParameter(gl.VERSION),swiftshader:/swiftshader/i.test(String(renderer)),backend:String(renderer||'').match(/(Direct3D|Vulkan|OpenGL|SwiftShader|Metal)/i)?.[1]||null,webgl2:!!c.getContext('webgl2')}; }""")
        if isinstance(value, dict):
            return value
    except Exception as exc:
        return {"available": None, "error": str(exc)}
    return {"available": None}


def _launch_browser_checks(settings: Settings) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    browser_results: dict[str, Any] = {}
    playwright_status = "PASS"
    with sync_playwright() as playwright:
        browser_types = [("chromium", playwright.chromium, {})]
        if settings.channel:
            browser_types.append((settings.channel, playwright.chromium, {"channel": settings.channel}))
        else:
            browser_types.append(("chrome", playwright.chromium, {"channel": "chrome"}))
        for name, browser_type, options in browser_types:
            launch_started = time.perf_counter()
            browser = None
            try:
                args = []
                if not settings.sandbox:
                    args.append("--no-sandbox")
                args.append("--disable-dev-shm-usage")
                browser = browser_type.launch(headless=settings.headless, args=args, **options)
                context = browser.new_context()
                page = context.new_page()
                visits = [_visit(page, "about:blank", settings.timeout_ms, settings.wait_ms)]
                visits.extend(_visit(page, url, settings.timeout_ms, settings.wait_ms) for url in settings.urls)
                browser_results[name] = {"launch": _result("PASS", {"version": browser.version, "launch_time_ms": round((time.perf_counter() - launch_started) * 1000, 2)}, confidence="High", recommendation="Browser launch is healthy."), "executable_path": str(browser_type.executable_path), "visits": visits, "webgl": _webgl_probe(page)}
                context.close()
                browser.close()
            except Exception as exc:
                playwright_status = "WARNING" if name == "chrome" else "FAIL"
                browser_results[name] = {"launch": _result(playwright_status, None, error=str(exc), root_cause="Browser installation" if "channel" in str(exc).lower() else "Playwright", confidence="High", recommendation="Install/repair the requested browser or verify Playwright browser binaries."), "executable_path": str(browser_type.executable_path), "visits": []}
                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    pass
    return {"playwright": {"status": playwright_status, "version": importlib.metadata.version("playwright")}, "browsers": browser_results}


def _profile_checks(settings: Settings) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    checks: dict[str, Any] = {"configured_profile": {"path": str(settings.profile) if settings.profile else None, "exists": bool(settings.profile and settings.profile.exists()), "writable": bool(settings.profile and os.access(settings.profile, os.W_OK)) if settings.profile else None}}
    class ProbeHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            payload = b"<!doctype html><title>environment profile probe</title>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    probe_url = f"http://127.0.0.1:{server.server_address[1]}/"
    with tempfile.TemporaryDirectory(prefix="cemeru-profile-") as temp_dir:
        checks["temporary_profile_path"] = temp_dir
        with sync_playwright() as playwright:
            persistent_context = None
            try:
                persistent_context = playwright.chromium.launch_persistent_context(temp_dir, headless=settings.headless, args=["--no-sandbox", "--disable-dev-shm-usage"])
                page = persistent_context.pages[0] if persistent_context.pages else persistent_context.new_page()
                checks["persistent_context"] = _storage_probe(page, probe_url)
                persistent_context.close()
            except Exception as exc:
                checks["persistent_context"] = _result("FAIL", None, error=str(exc), root_cause="User profile", confidence="High", recommendation="Check profile directory permissions and browser profile locking.")
                try:
                    if persistent_context is not None:
                        persistent_context.close()
                except Exception:
                    pass
            try:
                browser = playwright.chromium.launch(headless=settings.headless, args=["--no-sandbox", "--disable-dev-shm-usage"])
                context = browser.new_context()
                checks["temporary_context"] = _storage_probe(context.new_page(), probe_url)
                context.close()
                browser.close()
            except Exception as exc:
                checks["temporary_context"] = _result("FAIL", None, error=str(exc), root_cause="Browser installation", confidence="High", recommendation="Repair the Chromium installation before testing profile persistence.")
    server.shutdown()
    server.server_close()
    return checks


def _storage_probe(page: Any, url: str) -> dict[str, Any]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=10_000)
        value = page.evaluate("""async () => { const out={}; try { localStorage.setItem('__cemeru_probe','1'); out.localStorage=localStorage.getItem('__cemeru_probe')==='1'; localStorage.removeItem('__cemeru_probe'); } catch(e) { out.localStorage=false; out.localStorageError=String(e); } try { sessionStorage.setItem('__cemeru_probe','1'); out.sessionStorage=sessionStorage.getItem('__cemeru_probe')==='1'; sessionStorage.removeItem('__cemeru_probe'); } catch(e) { out.sessionStorage=false; out.sessionStorageError=String(e); } try { const db=await new Promise((resolve,reject)=>{ const req=indexedDB.open('__cemeru_probe',1); req.onsuccess=()=>{req.result.close(); indexedDB.deleteDatabase('__cemeru_probe'); resolve(true)}; req.onerror=()=>reject(req.error); }); out.indexedDB=!!db; } catch(e) { out.indexedDB=false; out.indexedDBError=String(e); } return out; }""")
        try:
            page.context.add_cookies([{"name": "__cemeru_probe", "value": "1", "domain": "example.com", "path": "/"}])
            value["cookies"] = any(cookie.get("name") == "__cemeru_probe" for cookie in page.context.cookies())
            page.context.clear_cookies()
        except Exception as exc:
            value["cookies"] = False
            value["cookiesError"] = str(exc)
        required = ("localStorage", "sessionStorage", "indexedDB", "cookies")
        healthy = all(value.get(key) for key in required)
        return _result("PASS" if healthy else "WARNING", value, root_cause="User profile" if not healthy else None, confidence="High", recommendation="Check storage restrictions if any persistence probe fails.")
    except Exception as exc:
        return _result("FAIL", None, error=str(exc), root_cause="User profile", confidence="High", recommendation="Check browser profile and storage permissions.")


def _readiness(network: dict[str, Any], browser: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    network_statuses = network.get("status_counts", {})
    https_statuses = [item.get("status") for item in network.get("checks", {}).get("https_connectivity", {}).values()]
    browser_launches = [item.get("launch", {}).get("status") for item in browser.get("browsers", {}).values()]
    browser_ready = "PASS" if "PASS" in browser_launches and browser.get("browsers", {}).get("chromium", {}).get("visits", [{}])[0].get("result", {}).get("status") == "PASS" else "FAIL" if "FAIL" in browser_launches else "UNKNOWN"
    network_ready = "PASS" if "PASS" in https_statuses and network_statuses.get("FAIL", 0) == 0 else "FAIL" if network_statuses.get("FAIL", 0) >= 2 else "UNKNOWN"
    cf_visits = []
    chromium = browser.get("browsers", {}).get("chromium", {})
    for visit in chromium.get("visits", []):
        if any(host in visit.get("url", "") for host in ("cloudflare.com", "bromotenggersemeru.id")):
            cf_visits.append(visit.get("result", {}).get("status"))
    cf_ready = "PASS" if any(status == "PASS" for status in cf_visits) else "WARNING" if any(status == "WARNING" for status in cf_visits) else "UNKNOWN"
    overall = "PASS" if browser_ready == network_ready == "PASS" and cf_ready in {"PASS", "WARNING"} else "FAIL" if browser_ready == "FAIL" or network_ready == "FAIL" else "WARNING" if cf_ready == "WARNING" else "UNKNOWN"
    return {"browser_readiness": browser_ready, "network_readiness": network_ready, "cloudflare_readiness": cf_ready, "overall_readiness": overall}


def _root_cause(readiness: dict[str, Any], network: dict[str, Any], browser: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    if readiness["browser_readiness"] == "FAIL":
        return {"root_cause": "Browser installation or Playwright", "confidence": "High", "recommendation": "Repair the failing browser launch before investigating stealth behavior."}
    if readiness["network_readiness"] in {"FAIL", "UNKNOWN"}:
        return {"root_cause": "VPS network/DNS/TLS environment", "confidence": "High", "recommendation": "Validate DNS, egress firewall, proxy, certificate trust, and socket connectivity outside this sandbox."}
    if readiness["cloudflare_readiness"] in {"WARNING", "UNKNOWN"}:
        return {"root_cause": "Cloudflare or target-site behavior", "confidence": "Medium", "recommendation": "Repeat from a permitted network and compare HTTP/CF headers; do not infer from fingerprint similarity."}
    profile_statuses = [profile.get(key, {}).get("status") for key in ("persistent_context", "temporary_context")]
    if "FAIL" in profile_statuses:
        return {"root_cause": "User profile/storage permissions", "confidence": "High", "recommendation": "Check profile locks, filesystem permissions, and storage policy."}
    return {"root_cause": "No single environment root cause observed", "confidence": "Low", "recommendation": "Proceed with controlled repeated runs and retain immutable artifacts."}


def _render_report(system: dict[str, Any], network: dict[str, Any], browser: dict[str, Any], profile: dict[str, Any], summary: dict[str, Any], output: Path) -> str:
    lines = [
        "# Experiment 016 - Environment Validation",
        "",
        "Diagnostic-only report. No stealth module, fingerprint, scoring, or Cloudflare behavior was modified.",
        f"\nOutput: `{output}`",
        "",
        "## Readiness",
        "",
        "| Area | Status |",
        "|---|---|",
        f"| Browser | {summary['readiness']['browser_readiness']} |",
        f"| Network | {summary['readiness']['network_readiness']} |",
        f"| Cloudflare | {summary['readiness']['cloudflare_readiness']} |",
        f"| Overall | **{summary['readiness']['overall_readiness']}** |",
        "",
        "## Root Cause Assessment",
        "",
        f"**{summary['root_cause']['root_cause']}** ({summary['root_cause']['confidence']} confidence)",
        "",
        summary["root_cause"]["recommendation"],
        "",
        "## Browser Checks",
        "",
        "| Browser | Launch | Version | about:blank | Google | Cloudflare | GitHub | Target |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, item in browser.get("browsers", {}).items():
        visits = item.get("visits", [])
        statuses = [visit.get("result", {}).get("status", "UNKNOWN") for visit in visits]
        while len(statuses) < 5:
            statuses.append("UNKNOWN")
        lines.append(f"| {name} | {item.get('launch', {}).get('status', 'UNKNOWN')} | {(item.get('launch', {}).get('value') or {}).get('version', '-')} | {' | '.join(statuses[:5])} |")
    lines.extend([
        "",
        "## Network Checks",
        "",
        "| Check | PASS | WARNING | FAIL | UNKNOWN |",
        "|---|---:|---:|---:|---:|",
    ])
    for group, checks in network.get("checks", {}).items():
        statuses = [item.get("status") for item in checks.values()]
        lines.append(f"| {group} | {statuses.count('PASS')} | {statuses.count('WARNING')} | {statuses.count('FAIL')} | {statuses.count('UNKNOWN')} |")
    lines.extend([
        "",
        "## Profile Checks",
        "",
        "| Probe | Status |",
        "|---|---|",
        f"| Persistent context | {profile.get('persistent_context', {}).get('status', 'UNKNOWN')} |",
        f"| Temporary context | {profile.get('temporary_context', {}).get('status', 'UNKNOWN')} |",
        "",
        "## System",
        "",
        f"- OS: `{system['os']['system']} {system['os']['release']}` ({system['os']['architecture']})",
        f"- CPU logical count: `{system['cpu']['logical_count']}`",
        f"- Python: `{system['python']['version']}`",
        f"- Playwright: `{system.get('playwright_version')}`",
        f"- Fonts detected: `{system['fonts']['count']}`",
        f"- DISPLAY: `{system['display']['DISPLAY']}`; Xvfb: `{system['display']['xvfb']}`",
        f"- DBUS available: `{system['dbus']['available']}`",
        "",
        "## Recommendations",
        "",
        "Use these diagnostics to separate host/network/browser failures from stealth fingerprint behavior. Repeat with headed mode, a controlled persistent profile, and an unrestricted network before drawing Cloudflare conclusions.",
        "",
    ])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Experiment 016: diagnostic environment validation.")
    parser.add_argument("--url", action="append", dest="urls", help="Additional HTTPS URL to test")
    parser.add_argument("--channel", default="", help="Playwright Chromium channel, e.g. chrome")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--wait", type=int, default=500, help="Milliseconds to wait after browser navigation")
    parser.add_argument("--timeout", type=int, default=10_000, help="Per-navigation/network timeout in milliseconds")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def run(settings: Settings) -> int:
    experiment = Experiment.create(settings.output)
    output = experiment.directory / "environment"
    output.mkdir(parents=True, exist_ok=True)
    system = collect_system(settings)
    network = collect_network(settings)
    browser = _launch_browser_checks(settings)
    chromium_webgl = browser.get("browsers", {}).get("chromium", {}).get("webgl")
    system["gpu"] = chromium_webgl if isinstance(chromium_webgl, dict) else {"available": None, "error": "Chromium WebGL probe unavailable"}
    profile = _profile_checks(settings)
    readiness = _readiness(network, browser, profile)
    cause = _root_cause(readiness, network, browser, profile)
    summary = {
        "experiment": "Experiment 016 - Environment Validation",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "status": readiness["overall_readiness"],
        "readiness": readiness,
        "root_cause": cause,
        "analysis_only": True,
        "inputs": {"urls": list(settings.urls), "headless": settings.headless, "persistent_profile": bool(settings.profile), "sandbox": settings.sandbox},
    }
    environment_document = {"experiment": summary["experiment"], "experiment_id": experiment.experiment_id, "system": system, "browser": browser, "profile": profile, "readiness": readiness, "root_cause": cause}
    browser_document = {"experiment_id": experiment.experiment_id, **browser}
    system_document = {"experiment_id": experiment.experiment_id, **system}
    write_json_exclusive(output / "environment.json", environment_document)
    write_json_exclusive(output / "network.json", network)
    write_json_exclusive(output / "browser.json", browser_document)
    write_json_exclusive(output / "system.json", system_document)
    write_json_exclusive(output / "summary.json", summary)
    report = _render_report(system, network, browser, profile, summary, output)
    write_text_exclusive(output / "environment_report.md", report)
    print(report)
    return 0


def main() -> int:
    args = build_parser().parse_args()
    configure_console_error_handling()
    if args.wait < 0 or args.timeout < 1:
        raise SystemExit("--wait must be non-negative and --timeout must be positive")
    root = project_root()
    reports_dir = args.reports_dir or root / "reports" / "experiments"
    if not reports_dir.is_absolute():
        reports_dir = root / reports_dir
    profile = args.profile
    if profile is not None and not profile.is_absolute():
        profile = root / profile
    urls = tuple(args.urls or TARGET_URLS)
    settings = Settings(
        root=root,
        output=reports_dir.resolve(),
        urls=urls,
        channel=args.channel,
        headless=not args.no_headless,
        profile=profile.resolve() if profile else None,
        timeout_ms=args.timeout,
        wait_ms=args.wait,
        sandbox=not args.no_sandbox,
    )
    return run(settings)


if __name__ == "__main__":
    raise SystemExit(main())
