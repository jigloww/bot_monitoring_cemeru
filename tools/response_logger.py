"""
tools/response_logger.py — Capture and log CF-specific response headers.

Focuses on: cf-ray, cf-cache-status, server, cf-mitigated, set-cookie,
            content-security-policy, report-to, nel, alt-svc.

Usage:
    python tools/response_logger.py --url https://bromotenggersemeru.id --output reports/network/response_headers.json
    python tools/response_logger.py --url https://target.com --wait 15000 --output response_headers.json
"""
from __future__ import annotations
import argparse, sys, time
from dataclasses import dataclass, field
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from playwright.sync_api import sync_playwright, Response
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

log = setup_logging("response_logger")

# CF and security headers of interest
INTERESTING_HEADERS = [
    "cf-ray", "cf-cache-status", "cf-mitigated", "cf-apo-via",
    "server", "set-cookie", "content-security-policy",
    "content-security-policy-report-only",
    "report-to", "nel", "alt-svc", "priority",
    "timing-allow-origin", "x-frame-options",
    "strict-transport-security", "x-content-type-options",
    "vary", "cache-control", "age", "expires",
    "x-powered-by", "x-robots-tag",
]


@dataclass
class ResponseRecord:
    timestamp:          float
    status:             int
    method:             str
    url:                str
    resource_type:      str
    headers:            dict[str, str] = field(default_factory=dict)
    cf_ray:             str = ""
    cf_cache_status:    str = ""
    cf_mitigated:       str = ""
    server:             str = ""
    is_cf_challenge:    bool = False


def attach_response_logger(page, records: list[ResponseRecord]) -> None:
    def on_response(resp: Response) -> None:
        try:
            h = {k.lower(): v for k, v in resp.headers.items()}
            interesting = {k: h[k] for k in INTERESTING_HEADERS if k in h}

            r = ResponseRecord(
                timestamp       = time.time(),
                status          = resp.status,
                method          = resp.request.method,
                url             = resp.url,
                resource_type   = resp.request.resource_type,
                headers         = interesting,
                cf_ray          = h.get("cf-ray", ""),
                cf_cache_status = h.get("cf-cache-status", ""),
                cf_mitigated    = h.get("cf-mitigated", ""),
                server          = h.get("server", ""),
                is_cf_challenge = (
                    "challenges.cloudflare.com" in resp.url
                    or "cdn-cgi/challenge" in resp.url
                    or resp.status in (403, 503) and "cf-ray" in h
                ),
            )
            records.append(r)

            # Always log CF headers
            if r.cf_ray:
                log.info("CF  %d  ray=%-22s  cache=%-12s  mitigated=%s  %s",
                         r.status, r.cf_ray, r.cf_cache_status, r.cf_mitigated or "-", r.url[:50])
            if r.is_cf_challenge:
                log.warning("CF CHALLENGE URL: %s", r.url[:80])
            if r.status >= 400:
                log.warning("HTTP %d ← %s", r.status, r.url[:60])

            # Log CSP if present
            if "content-security-policy" in interesting:
                log.debug("CSP: %s", interesting["content-security-policy"][:120])

        except Exception as e:
            log.debug("Response handler error: %s", e)

    page.on("response", on_response)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Capture and log CF-specific HTTP response headers.")
    add_browser_args(p)
    add_output_arg(p, default="")  # e.g. --output reports/network/response_headers.json
    return p


def main() -> int:
    args     = build_parser().parse_args()
    headless = not args.no_headless
    cfg      = BrowserConfig(channel=args.channel, headless=headless, profile=args.profile,
                             url=args.url, wait_ms=args.wait)
    out_file = Path(args.output) if args.output else ensure_output_dir() / "response_headers.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    records: list[ResponseRecord] = []

    with sync_playwright() as pw:
        handle, page, _ = launch_browser(pw, cfg)
        try:
            attach_response_logger(page, records)
            page.goto(cfg.url, wait_until="domcontentloaded", timeout=60_000)
            if cfg.wait_ms:
                page.wait_for_timeout(cfg.wait_ms)
        finally:
            handle.close()

    path = out_file
    save_json([r.__dict__ for r in records], path)
    log.info("Saved → %s  (%d responses)", path, len(records))

    # Summary
    cf_count = sum(1 for r in records if r.cf_ray)
    ch_count = sum(1 for r in records if r.is_cf_challenge)
    statuses = {}
    for r in records:
        statuses[r.status] = statuses.get(r.status, 0) + 1
    log.info("Total responses    : %d", len(records))
    log.info("With CF-Ray        : %d", cf_count)
    log.info("CF challenge URLs  : %d", ch_count)
    log.info("Status codes       : %s", statuses)
    return 0


if __name__ == "__main__":
    sys.exit(main())
