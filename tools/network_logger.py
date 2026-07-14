"""
tools/network_logger.py — Capture all browser network traffic and save as HAR + JSON.

Usage:
    python tools/network_logger.py --url https://bromotenggersemeru.id --output reports/network/network.json
    python tools/network_logger.py --url https://target.com --channel chrome --no-headless --output network.json

--output specifies the JSON path; HAR is saved alongside with .har extension.
"""
from __future__ import annotations
import argparse, json, sys, time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from playwright.sync_api import sync_playwright, Request, Response
from tools._shared import (
    BrowserConfig,
    OUTPUT_DIR,
    ensure_output_dir,
    launch_browser,
    navigate,
    save_json,
    setup_logging,
    add_browser_args,
    add_output_arg
)

log = setup_logging("network_logger")

# ══════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════

@dataclass
class NetworkEntry:
    timestamp:     float
    method:        str
    url:           str
    resource_type: str
    request_headers: dict[str, str] = field(default_factory=dict)
    request_body:    str            = ""
    status:          int            = 0
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body:   str            = ""
    timing_ms:       float          = 0.0
    redirected_from: str            = ""
    redirected_to:   str            = ""
    error:           str            = ""


# ══════════════════════════════════════════════════════════════════
# EVENT HANDLERS
# ══════════════════════════════════════════════════════════════════

def attach_listeners(page, entries: list[NetworkEntry]) -> None:
    """Attach Playwright event listeners to capture all requests/responses."""
    pending: dict[str, float] = {}   # url → start time

    def on_request(req: Request) -> None:
        t0 = time.monotonic()
        pending[req.url] = t0
        entry = NetworkEntry(
            timestamp      = time.time(),
            method         = req.method,
            url            = req.url,
            resource_type  = req.resource_type,
            request_headers= dict(req.headers),
            request_body   = (req.post_data or "")[:2000],
            redirected_from= req.redirected_from.url if req.redirected_from else "",
        )
        entries.append(entry)
        log.debug("→ %s %s", req.method, req.url[:80])

    def on_response(resp: Response) -> None:
        t0 = pending.pop(resp.url, None)
        timing = (time.monotonic() - t0) * 1000 if t0 else 0.0

        # Find matching pending entry and update it
        for entry in reversed(entries):
            if entry.url == resp.url and entry.status == 0:
                entry.status           = resp.status
                entry.response_headers = dict(resp.headers)
                entry.timing_ms        = timing
                # Capture body for non-binary responses (max 4KB)
                try:
                    ct = resp.headers.get("content-type", "")
                    if any(k in ct for k in ("text", "json", "javascript", "html")):
                        entry.response_body = resp.text()[:4096]
                except Exception:
                    pass

                # Log CF-specific headers
                cf_ray = resp.headers.get("cf-ray", "")
                if cf_ray:
                    log.info("CF-Ray: %s  status=%d  %s", cf_ray, resp.status, resp.url[:60])

                # Log challenge-related redirects
                if "challenges.cloudflare.com" in resp.url or "cdn-cgi/challenge" in resp.url:
                    log.warning("CF challenge URL: %s", resp.url)

                if resp.status >= 400:
                    log.warning("HTTP %d ← %s", resp.status, resp.url[:80])
                break

    def on_request_failed(req: Request) -> None:
        for entry in reversed(entries):
            if entry.url == req.url and entry.status == 0:
                entry.error = req.failure or "unknown"
                log.warning("Request failed: %s — %s", req.url[:60], entry.error)
                break

    page.on("request",       on_request)
    page.on("response",      on_response)
    page.on("requestfailed", on_request_failed)


# ══════════════════════════════════════════════════════════════════
# HAR EXPORT
# ══════════════════════════════════════════════════════════════════

def to_har(entries: list[NetworkEntry], page_url: str) -> dict:
    """Convert entries to HAR 1.2 format."""
    def headers_list(d: dict) -> list:
        return [{"name": k, "value": v} for k, v in d.items()]

    har_entries = []
    for e in entries:
        har_entries.append({
            "startedDateTime": datetime.fromtimestamp(e.timestamp, tz=timezone.utc).isoformat(),
            "time":            e.timing_ms,
            "request": {
                "method":      e.method,
                "url":         e.url,
                "httpVersion": "HTTP/1.1",
                "headers":     headers_list(e.request_headers),
                "queryString": [],
                "postData":    {"mimeType": "", "text": e.request_body} if e.request_body else None,
                "cookies":     [],
                "headersSize": -1,
                "bodySize":    len(e.request_body),
            },
            "response": {
                "status":      e.status,
                "statusText":  "",
                "httpVersion": "HTTP/1.1",
                "headers":     headers_list(e.response_headers),
                "cookies":     [],
                "content": {
                    "mimeType": e.response_headers.get("content-type", ""),
                    "text":     e.response_body,
                    "size":     len(e.response_body),
                },
                "redirectURL": e.redirected_to,
                "headersSize": -1,
                "bodySize":    len(e.response_body),
            },
            "timings":  {"send": 0, "wait": e.timing_ms, "receive": 0},
            "cache":    {},
        })

    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "network_logger.py", "version": "1.0"},
            "pages": [{"startedDateTime": datetime.now(tz=timezone.utc).isoformat(),
                       "id": "page_1", "title": page_url, "pageTimings": {}}],
            "entries": har_entries,
        }
    }


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Log all browser network traffic (HAR + JSON).")
    add_browser_args(p)
    add_output_arg(p, default="")  # e.g. --output reports/network/network.json
    return p


def main() -> int:
    args     = build_parser().parse_args()
    headless = not args.no_headless
    cfg      = BrowserConfig(channel=args.channel, headless=headless, profile=args.profile,
                             url=args.url, wait_ms=args.wait)
    out_file = Path(args.output) if args.output else ensure_output_dir() / "network_log.json"
    out      = out_file.parent
    out.mkdir(parents=True, exist_ok=True)
    entries: list[NetworkEntry] = []

    log.info("Recording network traffic for: %s", cfg.url)

    with sync_playwright() as pw:
        handle, page, _ = launch_browser(pw, cfg)
        try:
            attach_listeners(page, entries)
            navigate(page, cfg.url, wait_ms=cfg.wait_ms)
        finally:
            handle.close()

    log.info("Captured %d network entries", len(entries))

    # Save JSON
    json_path = out_file
    save_json([e.__dict__ for e in entries], json_path)
    log.info("Saved JSON → %s", json_path)

    # Save HAR alongside JSON with .har extension
    har_path = json_path.with_suffix(".har")
    save_json(to_har(entries, cfg.url), har_path)
    log.info("Saved HAR  → %s", har_path)

    # Print CF headers summary
    cf_entries = [e for e in entries if e.response_headers.get("cf-ray")]
    log.info("CF-Ray entries: %d", len(cf_entries))
    for e in cf_entries[:5]:
        log.info("  %d  cf-ray=%s  %s", e.status, e.response_headers.get("cf-ray","?"), e.url[:60])

    return 0


if __name__ == "__main__":
    sys.exit(main())
