# Phase 4 - Network & Environment Diagnostic Suite

Diagnostic-only output. No browser fingerprint, stealth module, scoring, or Cloudflare behavior was modified.

Output: `D:\bot_monitoring_cemeru\reports\experiments\exp_022\network`

## Subsystem Status

| Subsystem | Status |
|---|---|
| system | PASS |
| dns | PASS |
| tls | UNKNOWN |
| http | UNKNOWN |
| browser_network | PASS |
| **Overall** | **UNKNOWN** |

## Root Cause

**VPS cannot establish a reliable HTTPS session** (High confidence)

Repeat from an unrestricted network and inspect socket/TLS diagnostics.

## DNS

| Target | Status | Addresses | Latency ms |
|---|---|---|---:|
| https://www.google.com/ | PASS | 142.251.150.119, 142.251.151.119, 142.251.152.119, 142.251.153.119, 142.251.154.119, 142.251.155.119, 142.251.156.119, 142.251.157.119 | 58.49 |
| https://cloudflare.com/ | PASS | 104.16.132.229, 104.16.133.229 | 6.5 |
| https://github.com/ | PASS | 20.205.243.166 | 5.77 |
| https://bromotenggersemeru.id/ | PASS | 104.21.17.119, 172.67.176.188 | 2.81 |

Resolver(s): `fe80::1%10`
Local IPv4: `169.254.5.186, 192.168.1.34`; IPv6: `fe80::29b4:cb6c:f6f9:6b15, fe80::b74:8632:8a10:fc26`
Public IP: `-` (UNKNOWN)

| TCP Target | Status | Latency ms |
|---|---|---:|
| https://www.google.com/ | UNKNOWN | - |
| https://cloudflare.com/ | UNKNOWN | - |
| https://github.com/ | UNKNOWN | - |
| https://bromotenggersemeru.id/ | UNKNOWN | - |

## TLS

| Target | Status | TLS | Cipher | ALPN | Validation | Handshake ms |
|---|---|---|---|---|---|---:|
| https://www.google.com/ | UNKNOWN | - | - | - | - | - |
| https://cloudflare.com/ | UNKNOWN | - | - | - | - | - |
| https://github.com/ | UNKNOWN | - | - | - | - | - |
| https://bromotenggersemeru.id/ | UNKNOWN | - | - | - | - | - |

## HTTP

| Target | GET | HEAD | Redirects | gzip | brotli | HTTP/2 | HTTP/3 |
|---|---|---|---:|---|---|---|---|
| https://www.google.com/ | UNKNOWN | UNKNOWN | - | - | - | - | - |
| https://cloudflare.com/ | UNKNOWN | UNKNOWN | - | - | - | - | - |
| https://github.com/ | UNKNOWN | UNKNOWN | - | - | - | - | - |
| https://bromotenggersemeru.id/ | UNKNOWN | UNKNOWN | - | - | - | - | - |

## Browser Network

| Browser | Status | Version | Failed requests | Blocked | Security errors | Certificate errors |
|---|---|---|---:|---:|---:|---:|
| chromium | PASS | 149.0.7827.55 | 4 | 0 | 0 | 0 |

## System

- OS/kernel: `Windows 11` / `11`
- CPU: `12` logical cores
- RAM: `{'source': 'unavailable'}`
- Container/VM markers: `{'container_env': False, 'docker_cgroup': False, 'vm_markers': []}`
- Proxy environment detected: `False`

## Recommendations

Repeat this suite from a permitted network and compare DNS, TCP, TLS, HTTP, and browser outcomes before attributing Cloudflare behavior to fingerprinting.
