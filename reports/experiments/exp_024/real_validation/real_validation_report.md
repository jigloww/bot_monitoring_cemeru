# Experiment 018 — Real Browser Validation

This report is observational only. No CAPTCHA, Turnstile, Cloudflare challenge,
or booking interaction was automated. Cookie values are never persisted.

## Configuration

- Target: `https://bromotenggersemeru.id/`
- Runs per mode: `1`
- Headless: `True`
- Playwright: `unknown`
- Experiment allocation: `exp_024`

## Mode comparison

| Mode | Runs | Navigation success | Challenge rate | cf_clearance | 403 rate | Timeout | Crash | Avg load | Median load | Classification |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Plain Playwright | 1 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | — ms | — ms | UNUSABLE |
| playwright-stealth | 1 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | — ms | — ms | UNUSABLE |
| Local Stealth Framework | 1 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | — ms | — ms | UNUSABLE |
| Chrome via CDP | 1 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | — ms | — ms | UNUSABLE |
| Chrome Manual Profile | 1 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | — ms | — ms | UNUSABLE |

## Observed answers

- Most stable: **No mode with a completed run**
- Mode acquiring `cf_clearance`: **None observed**
- Most challenges: **No challenge observed**
- Fastest (median load): **No measurable load**
- Most failures: **No failures observed**
- Bot-monitoring candidate: **None from this sample**
- Booking suitability: **NOT_EVALUATED** — this experiment performs no booking or challenge interaction.

## Limitations and interpretation

Results are tied to the target URL, network, browser build, profile state, and
time of execution. `cf_clearance` acquisition is not a bypass guarantee, and
absence of a challenge in one run is not evidence of production reliability.
Use the mode marked for monitoring only as a hypothesis for further authorized
testing, with rate limits and manual review.

Generated at `2026-08-03T09:33:03.274646+07:00`.
