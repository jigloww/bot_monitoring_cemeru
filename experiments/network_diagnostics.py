"""Phase 4: runtime network and environment diagnostics.

This experiment is intentionally independent from fingerprint scoring.  It
records the host, resolver, TLS, HTTP, and Playwright network path and reports
what can (and cannot) be observed in the current environment.
"""
from __future__ import annotations

import argparse
import http.client
import importlib.metadata
import json
import os
import platform
import socket
import ssl
import subprocess
import sys
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.experiment import Experiment
from experiments.utils import configure_console_error_handling, now_iso, project_root, read_json, write_json_exclusive, write_text_exclusive


STATUS_VALUES = ("PASS", "WARNING", "FAIL", "UNKNOWN")
DEFAULT_TARGETS = (
    "https://www.google.com/",
    "https://cloudflare.com/",
    "https://github.com/",
    "https://bromotenggersemeru.id/",
)


@dataclass(frozen=True)
class Settings:
    root: Path
    output: Path
    targets: tuple[str, ...]
    timeout: float
    wait_ms: int
    headless: bool


def _result(status: str, value: Any = None, *, error: str | None = None, root_cause: str | None = None, confidence: str = "Medium", recommendation: str = "") -> dict[str, Any]:
    if status not in STATUS_VALUES:
        raise ValueError(status)
    return {"status": status, "value": value, "error": error, "root_cause": root_cause, "confidence": confidence, "recommendation": recommendation}


def _command(command: list[str], timeout: float = 3.0) -> str | None:
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        if process.returncode != 0:
            return None
        return ((process.stdout or "").strip() or None)
    except (OSError, subprocess.SubprocessError):
        return None


def _system(settings: Settings) -> dict[str, Any]:
    uname = platform.uname()
    container_markers = {
        "container_env": any(os.environ.get(key) for key in ("container", "KUBERNETES_SERVICE_HOST", "ECS_CONTAINER_METADATA_URI")),
        "docker_cgroup": False,
        "vm_markers": [],
    }
    cgroup = Path("/proc/1/cgroup")
    if cgroup.is_file():
        try:
            text = cgroup.read_text(encoding="utf-8", errors="replace").lower()
            container_markers["docker_cgroup"] = any(token in text for token in ("docker", "kubepods", "containerd", "lxc"))
        except OSError:
            pass
    vm_markers = []
    for command in (["systemd-detect-virt"], ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystem).Model"]):
        value = _command(command)
        if value and value.lower() not in {"none", "unknown"}:
            vm_markers.append(value)
    container_markers["vm_markers"] = vm_markers
    try:
        playwright_version = importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError:
        playwright_version = None
    memory: dict[str, Any] = {}
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        memory = {"total_bytes": vm.total, "available_bytes": vm.available, "used_bytes": vm.used, "percent": vm.percent, "source": "psutil"}
    except Exception:
        memory = {"source": "unavailable"}
    try:
        disk = __import__("shutil").disk_usage(settings.root)
        disk_data = {"total_bytes": disk.total, "free_bytes": disk.free, "used_bytes": disk.used}
    except OSError as exc:
        disk_data = {"error": str(exc)}
    return {
        "timestamp": now_iso(),
        "os": {"system": platform.system(), "release": platform.release(), "version": platform.version(), "kernel": uname.release, "architecture": platform.architecture()[0], "machine": uname.machine},
        "cpu": {"logical_count": os.cpu_count(), "processor": platform.processor()},
        "ram": memory,
        "disk": disk_data,
        "container_vm": container_markers,
        "python_version": platform.python_version(),
        "playwright_version": playwright_version,
        "timezone": time.tzname,
        "locale": {key: os.environ.get(key) for key in ("LANG", "LC_ALL", "LC_CTYPE") if os.environ.get(key)},
        "proxy_environment": {key: os.environ.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY") if os.environ.get(key)},
        "headless": settings.headless,
    }


def _resolver_addresses() -> list[str]:
    values: list[str] = []
    resolv = Path("/etc/resolv.conf")
    if resolv.is_file():
        try:
            values.extend(line.split()[1] for line in resolv.read_text(encoding="utf-8", errors="replace").splitlines() if line.startswith("nameserver ") and len(line.split()) > 1)
        except OSError:
            pass
    if os.name == "nt":
        text = _command(["ipconfig", "/all"])
        if text:
            for line in text.splitlines():
                if "DNS Servers" in line or line.strip().startswith("DNS Server"):
                    value = line.split(":", 1)[-1].strip()
                    if value:
                        values.append(value)
    return sorted(set(values))


def _dns_one(url: str, timeout: float) -> dict[str, Any]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    started = time.perf_counter()
    try:
        entries = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = sorted({entry[4][0] for entry in entries})
        families = sorted({"IPv6" if entry[0] == socket.AF_INET6 else "IPv4" for entry in entries})
        return _result("PASS", {"host": host, "addresses": addresses, "families": families, "latency_ms": round((time.perf_counter() - started) * 1000, 2)}, confidence="High", recommendation="DNS resolution is available.")
    except socket.gaierror as exc:
        return _result("FAIL", {"host": host}, error=str(exc), root_cause="DNS", confidence="High", recommendation="Check resolver configuration and DNS egress.")
    except Exception as exc:
        return _result("UNKNOWN", {"host": host}, error=str(exc), root_cause="Network", confidence="Medium", recommendation="Repeat DNS diagnostics from an unrestricted host.")


def _local_ip() -> dict[str, Any]:
    values: set[str] = set()
    try:
        for entry in socket.getaddrinfo(socket.gethostname(), None):
            values.add(entry[4][0])
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(0.2)
        probe.connect(("8.8.8.8", 80))
        values.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    ipv4 = sorted(value for value in values if ":" not in value)
    ipv6 = sorted(value for value in values if ":" in value)
    return {"addresses": sorted(values), "ipv4": ipv4, "ipv6": ipv6, "status": "PASS" if values else "UNKNOWN"}


def _public_ip(timeout: float) -> dict[str, Any]:
    endpoints = ("https://api.ipify.org?format=json", "https://ifconfig.me/ip")
    errors: list[str] = []
    for endpoint in endpoints:
        try:
            request = Request(endpoint, headers={"User-Agent": "cemeru-network-diagnostics/1.0"})
            started = time.perf_counter()
            with urlopen(request, timeout=timeout) as response:
                body = response.read(4096).decode("utf-8", errors="replace").strip()
            value = body
            if body.startswith("{"):
                value = str(json.loads(body).get("ip") or body)
            return _result("PASS", {"ip": value, "endpoint": endpoint, "latency_ms": round((time.perf_counter() - started) * 1000, 2)}, confidence="High", recommendation="Public IP was observed.")
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")
    return _result("UNKNOWN", None, error="; ".join(errors), root_cause="Network", confidence="Medium", recommendation="Repeat public-IP discovery from a network that permits outbound HTTPS.")


def _socket_one(url: str, timeout: float) -> dict[str, Any]:
    parsed = urlparse(url)
    host, port = parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80)
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return _result("PASS", {"host": host, "port": port, "latency_ms": round((time.perf_counter() - started) * 1000, 2)}, confidence="High", recommendation="TCP/socket connectivity is available.")
    except socket.timeout as exc:
        return _result("FAIL", {"host": host, "port": port}, error=str(exc), root_cause="Network", confidence="High", recommendation="Check firewall, egress policy, and route latency.")
    except OSError as exc:
        return _result("UNKNOWN", {"host": host, "port": port}, error=str(exc), root_cause="Network", confidence="Medium", recommendation="Check egress and resolver results outside the sandbox.")


def collect_dns(settings: Settings) -> dict[str, Any]:
    checks = {url: _dns_one(url, settings.timeout) for url in settings.targets}
    statuses = {status: sum(item["status"] == status for item in checks.values()) for status in STATUS_VALUES}
    return {"timestamp": now_iso(), "resolver": _resolver_addresses(), "public_ip": _public_ip(settings.timeout), "local_ip": _local_ip(), "tcp_connectivity": {url: _socket_one(url, settings.timeout) for url in settings.targets}, "checks": checks, "status_counts": statuses}


def _tls_one(url: str, timeout: float) -> dict[str, Any]:
    parsed = urlparse(url)
    host, port = parsed.hostname or "", parsed.port or 443
    started = time.perf_counter()
    raw = None
    wrapped = None
    try:
        context = ssl.create_default_context()
        context.set_alpn_protocols(["h2", "http/1.1"])
        raw = socket.create_connection((host, port), timeout=timeout)
        wrapped = context.wrap_socket(raw, server_hostname=host)
        cert = wrapped.getpeercert()
        binary = wrapped.getpeercert(binary_form=True)
        chain = []
        get_chain = getattr(wrapped, "get_verified_chain", None)
        if callable(get_chain):
            try:
                chain = [str(item) for item in get_chain()]
            except Exception:
                chain = []
        return _result("PASS", {"url": url, "tls_version": wrapped.version(), "cipher": wrapped.cipher(), "alpn": wrapped.selected_alpn_protocol(), "sni": host, "certificate": {"subject": cert.get("subject"), "issuer": cert.get("issuer"), "notBefore": cert.get("notBefore"), "notAfter": cert.get("notAfter"), "san": cert.get("subjectAltName")}, "certificate_sha256": __import__("hashlib").sha256(binary).hexdigest() if binary else None, "certificate_chain": chain, "validation": True, "handshake_ms": round((time.perf_counter() - started) * 1000, 2)}, confidence="High", recommendation="TLS handshake and certificate validation succeeded.")
    except ssl.SSLCertVerificationError as exc:
        return _result("FAIL", {"url": url, "sni": host, "validation": False}, error=str(exc), root_cause="TLS certificate validation", confidence="High", recommendation="Check trust store, system clock, proxy interception, and certificate chain.")
    except (socket.timeout, TimeoutError) as exc:
        return _result("FAIL", {"url": url, "sni": host}, error=str(exc), root_cause="TLS/network", confidence="High", recommendation="Check network egress and TLS handshake latency.")
    except OSError as exc:
        return _result("UNKNOWN", {"url": url, "sni": host}, error=str(exc), root_cause="Network", confidence="Medium", recommendation="Repeat TLS diagnostics from an unrestricted network.")
    finally:
        try:
            if wrapped is not None:
                wrapped.close()
            elif raw is not None:
                raw.close()
        except OSError:
            pass


def collect_tls(settings: Settings) -> dict[str, Any]:
    checks = {url: _tls_one(url, settings.timeout) for url in settings.targets if urlparse(url).scheme == "https"}
    return {"timestamp": now_iso(), "checks": checks, "status_counts": {status: sum(item["status"] == status for item in checks.values()) for status in STATUS_VALUES}}


def _http_one(url: str, timeout: float, method: str) -> dict[str, Any]:
    current = url
    chain: list[dict[str, Any]] = []
    started = time.perf_counter()
    for _ in range(8):
        parsed = urlparse(current)
        host, port = parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80)
        connection: Any = None
        try:
            if parsed.scheme == "https":
                connection = http.client.HTTPSConnection(host, port, timeout=timeout, context=ssl.create_default_context())
            else:
                connection = http.client.HTTPConnection(host, port, timeout=timeout)
            connection.request(method, parsed.path or "/", headers={"User-Agent": "cemeru-network-diagnostics/1.0", "Accept-Encoding": "gzip, br"})
            response = connection.getresponse()
            headers = {str(key).lower(): str(value) for key, value in response.getheaders()}
            if method == "GET":
                response.read(16384)
            item = {"url": current, "status": response.status, "reason": response.reason, "headers": headers, "content_encoding": headers.get("content-encoding"), "http2": headers.get("alt-svc", "").find("h2") >= 0, "http3": headers.get("alt-svc", "").find("h3") >= 0}
            chain.append(item)
            if response.status in {301, 302, 303, 307, 308} and headers.get("location"):
                current = urljoin(current, headers["location"])
                continue
            status = "PASS" if 200 <= response.status < 400 else "WARNING" if response.status < 500 else "FAIL"
            return _result(status, {"method": method, "requested_url": url, "final_url": current, "status": response.status, "headers": headers, "redirect_chain": chain, "redirect_count": max(0, len(chain) - 1), "gzip": headers.get("content-encoding") == "gzip", "brotli": headers.get("content-encoding") == "br", "http2": item["http2"], "http3": item["http3"], "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)}, root_cause="Cloudflare" if "cf-ray" in headers or "cloudflare" in headers.get("server", "").lower() else ("HTTP server" if response.status >= 400 else None), confidence="High", recommendation="Inspect HTTP response and redirect headers." if response.status >= 400 else "HTTP request succeeded.")
        except ssl.SSLCertVerificationError as exc:
            return _result("FAIL", {"method": method, "requested_url": url, "redirect_chain": chain}, error=str(exc), root_cause="TLS certificate validation", confidence="High", recommendation="Check certificate trust and system clock.")
        except (socket.timeout, TimeoutError) as exc:
            return _result("FAIL", {"method": method, "requested_url": url, "redirect_chain": chain}, error=str(exc), root_cause="Network", confidence="High", recommendation="Check egress firewall and latency.")
        except OSError as exc:
            return _result("UNKNOWN", {"method": method, "requested_url": url, "redirect_chain": chain}, error=str(exc), root_cause="Network", confidence="Medium", recommendation="Repeat HTTP diagnostics outside the restricted environment.")
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
    return _result("WARNING", {"method": method, "requested_url": url, "redirect_chain": chain}, root_cause="HTTP redirect loop", confidence="High", recommendation="Inspect redirect policy and canonical URL.")


def collect_http(settings: Settings) -> dict[str, Any]:
    checks = {url: {"GET": _http_one(url, settings.timeout, "GET"), "HEAD": _http_one(url, settings.timeout, "HEAD")} for url in settings.targets}
    flat = [item for methods in checks.values() for item in methods.values()]
    return {"timestamp": now_iso(), "checks": checks, "http2_support": any((item.get("value") or {}).get("http2") for item in flat if isinstance(item.get("value"), dict)), "http3_support": any((item.get("value") or {}).get("http3") for item in flat if isinstance(item.get("value"), dict)), "status_counts": {status: sum(item["status"] == status for item in flat) for status in STATUS_VALUES}}


def _browser_network(settings: Settings) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    browsers: dict[str, Any] = {}
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=settings.headless, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context()
            page = context.new_page()
            responses: list[dict[str, Any]] = []
            failed: list[dict[str, Any]] = []
            security: list[dict[str, Any]] = []
            console: list[dict[str, Any]] = []
            page_errors: list[str] = []
            timings: list[dict[str, Any]] = []
            page.on("response", lambda response: responses.append({"url": response.url, "status": response.status, "resource_type": response.request.resource_type, "timing": response.request.timing, "headers": {str(k).lower(): str(v) for k, v in response.headers.items()}}))
            def on_failed(request: Any) -> None:
                failure = request.failure or "unknown"
                item = {"url": request.url, "failure": failure, "resource_type": request.resource_type}
                failed.append(item)
                if any(token in str(failure).upper() for token in ("CERT", "SSL", "SECURITY")):
                    security.append(item)
            page.on("requestfailed", on_failed)
            page.on("console", lambda message: console.append({"type": message.type, "text": message.text[:1200]}))
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            visit_results = []
            for url in ("about:blank", *settings.targets):
                started = time.perf_counter()
                error = None
                status = None
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=int(settings.timeout * 1000))
                    status = response.status if response is not None else None
                except Exception as exc:
                    error = str(exc)
                if settings.wait_ms:
                    try:
                        page.wait_for_timeout(settings.wait_ms)
                    except Exception as exc:
                        error = error or str(exc)
                elapsed = round((time.perf_counter() - started) * 1000, 2)
                result_status = "PASS" if (url == "about:blank" and not error) or (status is not None and status < 400) else "UNKNOWN" if status is None else "WARNING"
                visit_results.append({"url": url, "status": status, "final_url": page.url, "elapsed_ms": elapsed, "error": error, "result": _result(result_status, {"status": status, "elapsed_ms": elapsed}, error=error, root_cause="TLS/network" if error and "ERR_" in error else None, confidence="High" if result_status == "PASS" else "Medium", recommendation="Inspect Playwright network errors." if result_status != "PASS" else "Navigation succeeded.")})
                timings.append({"url": url, "elapsed_ms": elapsed})
            browsers["chromium"] = {"status": "PASS", "version": browser.version, "visits": visit_results, "failed_requests": failed, "blocked_requests": [item for item in failed if "BLOCKED" in str(item.get("failure", "")).upper()], "security_errors": security, "certificate_errors": [item for item in security if "CERT" in str(item.get("failure", "")).upper()], "console": console, "page_errors": page_errors, "request_timing": timings, "proxy_detected": bool(os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("ALL_PROXY")), "offline": not bool(page.evaluate("() => navigator.onLine"))}
            context.close()
            browser.close()
        except Exception as exc:
            browsers["chromium"] = {"status": "FAIL", "version": None, "visits": [], "error": str(exc), "failed_requests": [], "blocked_requests": [], "security_errors": [], "certificate_errors": [], "console": [], "page_errors": [], "request_timing": [], "proxy_detected": bool(os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("ALL_PROXY")), "offline": None}
    return {"timestamp": now_iso(), "playwright_version": importlib.metadata.version("playwright"), "browsers": browsers}


def _summary(system: dict[str, Any], dns: dict[str, Any], tls: dict[str, Any], http: dict[str, Any], browser: dict[str, Any], experiment_id: str) -> dict[str, Any]:
    subsystem = {
        "system": "PASS",
        "dns": "PASS" if dns["status_counts"]["PASS"] else "FAIL" if dns["status_counts"]["FAIL"] else "UNKNOWN",
        "tls": "PASS" if tls["status_counts"]["PASS"] else "FAIL" if tls["status_counts"]["FAIL"] else "UNKNOWN",
        "http": "PASS" if http["status_counts"]["PASS"] else "FAIL" if http["status_counts"]["FAIL"] else "UNKNOWN",
        "browser_network": "PASS" if any(value.get("status") == "PASS" for value in browser.get("browsers", {}).values()) else "FAIL",
    }
    if any(status == "FAIL" for status in subsystem.values()):
        overall = "FAIL"
    elif any(status == "UNKNOWN" for status in subsystem.values()):
        overall = "UNKNOWN"
    elif any(status == "WARNING" for status in subsystem.values()):
        overall = "WARNING"
    else:
        overall = "PASS"
    if subsystem["dns"] == "FAIL":
        cause = {"root_cause": "DNS resolution failed", "confidence": "High", "recommendation": "Check resolver addresses, DNS egress, and host resolver configuration."}
    elif subsystem["tls"] == "FAIL":
        cause = {"root_cause": "TLS handshake or certificate validation failed", "confidence": "High", "recommendation": "Check trust store, clock, proxy interception, SNI, and TLS policy."}
    elif subsystem["http"] == "FAIL":
        cause = {"root_cause": "HTTP server or network path failed", "confidence": "High", "recommendation": "Inspect status, headers, redirect chain, firewall, and proxy policy."}
    elif subsystem["browser_network"] == "FAIL":
        cause = {"root_cause": "Playwright browser launch or network path failed", "confidence": "High", "recommendation": "Check browser installation and Playwright request failures."}
    elif subsystem["http"] == "UNKNOWN" or subsystem["tls"] == "UNKNOWN":
        cause = {"root_cause": "VPS cannot establish a reliable HTTPS session", "confidence": "High", "recommendation": "Repeat from an unrestricted network and inspect socket/TLS diagnostics."}
    else:
        cause = {"root_cause": "No single environment root cause observed", "confidence": "Low", "recommendation": "Retain this artifact and compare repeated runs."}
    return {"experiment": "Phase 4 - Network & Environment Diagnostic Suite", "experiment_id": experiment_id, "created_at": now_iso(), "analysis_only": True, "subsystem_status": subsystem, "overall_status": overall, "root_cause": cause, "statistics": {"dns": dns["status_counts"], "tls": tls["status_counts"], "http": http["status_counts"]}}


def _render(system: dict[str, Any], dns: dict[str, Any], tls: dict[str, Any], http: dict[str, Any], browser: dict[str, Any], summary: dict[str, Any], output: Path) -> str:
    lines = [
        "# Phase 4 - Network & Environment Diagnostic Suite", "",
        "Diagnostic-only output. No browser fingerprint, stealth module, scoring, or Cloudflare behavior was modified.", f"\nOutput: `{output}`", "",
        "## Subsystem Status", "", "| Subsystem | Status |", "|---|---|",
    ]
    for key, value in summary["subsystem_status"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend([f"| **Overall** | **{summary['overall_status']}** |", "", "## Root Cause", "", f"**{summary['root_cause']['root_cause']}** ({summary['root_cause']['confidence']} confidence)", "", summary["root_cause"]["recommendation"], "", "## DNS", "", "| Target | Status | Addresses | Latency ms |", "|---|---|---|---:|"])
    for url, item in dns["checks"].items():
        value = item.get("value") or {}
        lines.append(f"| {url} | {item['status']} | {', '.join(value.get('addresses', [])) or '-'} | {value.get('latency_ms', '-')} |")
    local = dns.get("local_ip", {})
    public = dns.get("public_ip", {})
    lines.extend([
        "",
        f"Resolver(s): `{', '.join(dns.get('resolver', [])) or 'unknown'}`",
        f"Local IPv4: `{', '.join(local.get('ipv4', [])) or '-'}`; IPv6: `{', '.join(local.get('ipv6', [])) or '-'}`",
        f"Public IP: `{(public.get('value') or {}).get('ip') if isinstance(public.get('value'), dict) else '-'}` ({public.get('status', 'UNKNOWN')})",
        "",
        "| TCP Target | Status | Latency ms |",
        "|---|---|---:|",
    ])
    for url, item in dns.get("tcp_connectivity", {}).items():
        lines.append(f"| {url} | {item.get('status')} | {(item.get('value') or {}).get('latency_ms', '-')} |")
    lines.extend(["", "## TLS", "", "| Target | Status | TLS | Cipher | ALPN | Validation | Handshake ms |", "|---|---|---|---|---|---|---:|"])
    for url, item in tls["checks"].items():
        value = item.get("value") or {}
        lines.append(f"| {url} | {item['status']} | {value.get('tls_version','-')} | {value.get('cipher','-')} | {value.get('alpn','-')} | {value.get('validation','-')} | {value.get('handshake_ms','-')} |")
    lines.extend(["", "## HTTP", "", "| Target | GET | HEAD | Redirects | gzip | brotli | HTTP/2 | HTTP/3 |", "|---|---|---|---:|---|---|---|---|"])
    for url, methods in http["checks"].items():
        get, head = methods["GET"], methods["HEAD"]
        value = get.get("value") or {}
        lines.append(f"| {url} | {get['status']} | {head['status']} | {value.get('redirect_count','-')} | {value.get('gzip','-')} | {value.get('brotli','-')} | {value.get('http2','-')} | {value.get('http3','-')} |")
    lines.extend(["", "## Browser Network", "", "| Browser | Status | Version | Failed requests | Blocked | Security errors | Certificate errors |", "|---|---|---|---:|---:|---:|---:|"])
    for name, item in browser.get("browsers", {}).items():
        lines.append(f"| {name} | {item.get('status')} | {item.get('version','-')} | {len(item.get('failed_requests', []))} | {len(item.get('blocked_requests', []))} | {len(item.get('security_errors', []))} | {len(item.get('certificate_errors', []))} |")
    lines.extend(["", "## System", "", f"- OS/kernel: `{system['os']['system']} {system['os']['release']}` / `{system['os']['kernel']}`", f"- CPU: `{system['cpu']['logical_count']}` logical cores", f"- RAM: `{system['ram']}`", f"- Container/VM markers: `{system['container_vm']}`", f"- Proxy environment detected: `{bool(system['proxy_environment'])}`", "", "## Recommendations", "", "Repeat this suite from a permitted network and compare DNS, TCP, TLS, HTTP, and browser outcomes before attributing Cloudflare behavior to fingerprinting.", ""])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase 4 network diagnostics.")
    parser.add_argument("--url", action="append", dest="urls", help="Target URL; may be repeated")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--wait", type=int, default=300)
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def run(settings: Settings) -> int:
    experiment = Experiment.create(settings.output)
    output = experiment.directory / "network"
    output.mkdir(parents=True, exist_ok=True)
    system = _system(settings)
    dns = collect_dns(settings)
    tls = collect_tls(settings)
    http = collect_http(settings)
    browser = _browser_network(settings)
    summary = _summary(system, dns, tls, http, browser, experiment.experiment_id)
    write_json_exclusive(output / "dns.json", dns)
    write_json_exclusive(output / "tls.json", tls)
    write_json_exclusive(output / "http.json", http)
    write_json_exclusive(output / "browser_network.json", browser)
    write_json_exclusive(output / "summary.json", summary)
    report = _render(system, dns, tls, http, browser, summary, output)
    write_text_exclusive(output / "network_report.md", report)
    print(report)
    return 0


def main() -> int:
    args = build_parser().parse_args()
    configure_console_error_handling()
    if args.timeout <= 0 or args.wait < 0:
        raise SystemExit("--timeout must be positive and --wait non-negative")
    root = project_root()
    reports_dir = args.reports_dir or root / "reports" / "experiments"
    if not reports_dir.is_absolute():
        reports_dir = root / reports_dir
    target_urls = tuple(args.urls or DEFAULT_TARGETS)
    settings = Settings(root=root, output=reports_dir.resolve(), targets=target_urls, timeout=args.timeout, wait_ms=args.wait, headless=not args.no_headless)
    return run(settings)


if __name__ == "__main__":
    raise SystemExit(main())
