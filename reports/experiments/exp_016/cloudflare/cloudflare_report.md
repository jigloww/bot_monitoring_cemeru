# Experiment 015 - Cloudflare Evaluation

Observational only: no challenge was clicked, solved, bypassed, or modified.

Output: `D:\bot_monitoring_cemeru\reports\experiments\exp_016\cloudflare`

## Runs

| Run | Status | HTTP | Challenge | Solved | Clearance | Final URL | Reason |
|---|---|---:|---|---|---|---|---|
| run_001 | UNKNOWN | - | False | False | False | chrome-error://chromewebdata/ | Browser or network error prevented an HTTP outcome from being observed. |

## Timeline

### run_001

| Event | Elapsed ms | Details |
|---|---:|---|
| navigation_start / navigation_end | - | See timeline.json |

## Cookies

Cookie values are redacted; presence, length, and SHA-256 are retained.

| Run | Cookie count | cf_clearance | __cf_bm |
|---|---:|---|---|
| run_001 | 0 | False | False |

## Headers

| Run | cf-ray | cf-cache-status | server |
|---|---|---|---|
| run_001 | - | - | - |

## Challenge Events

| Run | Detected | Solved | Timeout | Turnstile | CAPTCHA | Duration ms |
|---|---|---|---|---|---|---:|
| run_001 | False | False | False | False | False | - |

## Final Outcome

PASS: **0**, WARNING: **0**, FAIL: **0**, UNKNOWN: **1**

## Observed Risks

- A FAIL indicates an observed HTTP block, challenge timeout, or browser timeout; it is not a bypass attempt.
- UNKNOWN indicates that the environment did not provide a reliable HTTP outcome.
- Cloudflare cookies are redacted in reports to avoid persisting clearance tokens.

## Recommendations

- Repeat the same URL with controlled headed/headless and persistent-profile settings.
- Compare challenge and clearance rates over time; do not infer bypass success from fingerprint similarity.
- Investigate only observed network/browser failures; this evaluator does not alter challenge behavior.

## Statistics

Challenge success: N/A%
HTTP success: 0.0%
Clearance acquired: 0.0%
Mean challenge duration: N/A ms
