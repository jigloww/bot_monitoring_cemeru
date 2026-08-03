# Experiment 013 - Fingerprint Consistency Validator

Analysis-only validation; no browser or stealth code was modified.

Overall Consistency Score: **92.0%** (WARNING)

## Category Scores

| Domain | Score | Rules | PASS | WARNING | FAIL |
|---|---:|---:|---:|---:|---:|
| Navigator | 94.3% | 7 | 6 | 1 | 0 |
| Window | 100.0% | 3 | 3 | 0 | 0 |
| Screen | 100.0% | 3 | 3 | 0 | 0 |
| Chrome | 80.0% | 2 | 1 | 1 | 0 |
| Permissions | 60.0% | 1 | 0 | 1 | 0 |
| Fonts | 100.0% | 1 | 1 | 0 | 0 |
| Speech | 100.0% | 1 | 1 | 0 | 0 |
| Performance | 100.0% | 1 | 1 | 0 | 0 |
| Cross-Domain | 88.0% | 10 | 7 | 3 | 0 |

## Rule Results

| Rule | Status | Severity | Reason | Recommended Fix | Confidence |
|---|---|---|---|---|---|
| UA ↔ UA-CH consistency | PASS | Low | UA browser family/version agree with UA-CH brands. | No change required. | High |
| Platform ↔ UA consistency | PASS | Low | Platform agrees with the operating-system token in userAgent. | Keep navigator.platform and the UA operating-system token aligned. | High |
| Screen ↔ Window consistency | PASS | Low | Window viewport fits inside the reported screen. | Ensure outer/inner viewport and screen dimensions form a physically possible layout. | High |
| chrome.runtime ↔ browser consistency | WARNING | Low | window.chrome is present but chrome.runtime is absent; this can be valid on extension-free pages. | Only expose chrome.runtime when the target browser context requires it. | Medium |
| Languages ↔ language consistency | PASS | Low | Primary language is the first languages entry. | Set navigator.language equal to languages[0] and keep locale ordering coherent. | High |
| hardwareConcurrency ↔ deviceMemory consistency | PASS | Low | Hardware concurrency and memory are plausible together. | Use a profile with a realistic CPU/memory pairing. | Medium |
| performance.memory ↔ browser consistency | PASS | Low | Chrome exposes a coherent performance.memory object. | No change required. | High |
| Fonts ↔ platform consistency | PASS | Low | Font inventory is plausible for the reported platform. | No change required. | Medium |
| Speech voices ↔ platform consistency | PASS | Low | Speech voices contain platform-neutral, valid locale records. | Keep voice locale records complete and aligned with the platform/browser profile. | Medium |
| Viewport ↔ screen consistency | PASS | Low | Viewport fits inside the available screen area. | Keep inner viewport dimensions within screen.availWidth/availHeight. | High |
| DPR ↔ viewport consistency | PASS | Low | DPR and viewport dimensions form a plausible display relationship. | Keep devicePixelRatio, viewport, and screen dimensions from contradictory profiles. | Medium |
| navigator.vendor ↔ browser consistency | PASS | Low | Chrome UA and navigator.vendor agree. | No change required. | High |
| navigator.webdriver ↔ automation consistency | WARNING | Medium | Automation metadata is present while navigator.webdriver is hidden. | Treat webdriver spoofing as an intentional, documented stealth decision and keep other automation signals aligned. | High |
| Plugin count ↔ MIME type consistency | PASS | Low | Plugin and MIME type counts are mutually plausible. | Keep navigator.plugins and navigator.mimeTypes generated from one coherent profile. | High |
| Permissions ↔ secure context consistency | WARNING | Low | Secure-context status cannot be inferred from the recorded URL. | Record a secure-context signal or evaluate permissions on the target origin. | Low |

## Data Sources

- Reference: `reports\fingerprint\fingerprint_real.json`
- Candidate: `reports\experiments\exp_012\performance\performance\fingerprint.json`
- Candidate selection: latest completed Performance experiment artifact

## Counts

PASS: 12  |  WARNING: 3  |  FAIL: 0
