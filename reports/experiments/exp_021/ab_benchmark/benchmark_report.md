# Experiment 017 - Real Cloudflare A/B Benchmark

Benchmark-only report. No challenge or CAPTCHA was solved or bypassed.

Output: `D:\bot_monitoring_cemeru\reports\experiments\exp_021\ab_benchmark`

## Per Mode

| Mode | Classification | Success | Challenge | Clearance | Avg Nav ms | Avg Challenge ms | Failure | Crash | Timeout |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Plain Playwright (Chromium) | UNUSABLE | 0.0% | 0.0% | 0.0% | 557.65 | - | 0.0% | 0.0% | 0.0% |
| Playwright + playwright-stealth | UNUSABLE | 0.0% | 0.0% | 0.0% | 381.83 | - | 0.0% | 0.0% | 0.0% |
| Local Stealth Framework | UNUSABLE | 0.0% | 0.0% | 0.0% | 410.34 | - | 0.0% | 0.0% | 0.0% |
| Real Chrome via CDP | UNUSABLE | 0.0% | 0.0% | 0.0% | - | - | 0.0% | 0.0% | 0.0% |

## Per Run

| Run | Mode | Outcome | HTTP | Challenge | Clearance | Cookies | Elapsed ms | Final URL |
|---|---|---|---:|---|---|---:|---:|---|
| run_001_plain | Plain Playwright (Chromium) | UNKNOWN | - | False | False | 0 | 557.65 | chrome-error://chromewebdata/ |
| run_001_playwright_stealth | Playwright + playwright-stealth | UNKNOWN | - | False | False | 0 | 381.83 | chrome-error://chromewebdata/ |
| run_001_local_stealth | Local Stealth Framework | UNKNOWN | - | False | False | 0 | 410.34 | chrome-error://chromewebdata/ |
| run_001_chrome_cdp | Real Chrome via CDP | UNKNOWN | - | False | False | 0 | - | - |

## Overall Ranking

| Rank | Mode | Classification | Success rate | Reason |
|---:|---|---|---:|---|
| 1 | Plain Playwright (Chromium) | UNUSABLE | 0.0% | {'PASS': 0, 'WARNING': 0, 'FAIL': 0, 'UNKNOWN': 1} |
| 2 | Playwright + playwright-stealth | UNUSABLE | 0.0% | {'PASS': 0, 'WARNING': 0, 'FAIL': 0, 'UNKNOWN': 1} |
| 3 | Local Stealth Framework | UNUSABLE | 0.0% | {'PASS': 0, 'WARNING': 0, 'FAIL': 0, 'UNKNOWN': 1} |
| 4 | Real Chrome via CDP | UNUSABLE | 0.0% | {'PASS': 0, 'WARNING': 0, 'FAIL': 0, 'UNKNOWN': 1} |

## Interpretation

Total runs: **4**; PASS: **0**, WARNING: **0**, FAIL: **0**, UNKNOWN: **4**.

UNKNOWN means the environment did not provide a reliable HTTP outcome. It is not evidence that stealth succeeded or failed.

## Recommendations

Repeat the benchmark from a permitted network, keep the target and browser settings identical, and compare observed challenge/clearance rates rather than fingerprint similarity.
