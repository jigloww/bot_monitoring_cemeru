# Experiment 016 - Environment Validation

Diagnostic-only report. No stealth module, fingerprint, scoring, or Cloudflare behavior was modified.

Output: `D:\bot_monitoring_cemeru\reports\experiments\exp_020\environment`

## Readiness

| Area | Status |
|---|---|
| Browser | PASS |
| Network | UNKNOWN |
| Cloudflare | UNKNOWN |
| Overall | **UNKNOWN** |

## Root Cause Assessment

**VPS network/DNS/TLS environment** (High confidence)

Validate DNS, egress firewall, proxy, certificate trust, and socket connectivity outside this sandbox.

## Browser Checks

| Browser | Launch | Version | about:blank | Google | Cloudflare | GitHub | Target |
|---|---|---|---|---|---|---|---|
| chromium | PASS | 149.0.7827.55 | PASS | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| chrome | PASS | 151.0.7922.72 | PASS | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

## Network Checks

| Check | PASS | WARNING | FAIL | UNKNOWN |
|---|---:|---:|---:|---:|
| dns | 4 | 0 | 0 | 0 |
| socket_https | 0 | 0 | 0 | 4 |
| https_connectivity | 0 | 0 | 0 | 4 |
| http_connectivity | 0 | 0 | 0 | 1 |
| certificate_validation | 0 | 0 | 0 | 4 |
| redirect_support | 0 | 0 | 0 | 4 |

## Profile Checks

| Probe | Status |
|---|---|
| Persistent context | PASS |
| Temporary context | PASS |

## System

- OS: `Windows 11` (64bit)
- CPU logical count: `12`
- Python: `3.12.10`
- Playwright: `1.61.0`
- Fonts detected: `432`
- DISPLAY: `None`; Xvfb: `None`
- DBUS available: `False`

## Recommendations

Use these diagnostics to separate host/network/browser failures from stealth fingerprint behavior. Repeat with headed mode, a controlled persistent profile, and an unrestricted network before drawing Cloudflare conclusions.
