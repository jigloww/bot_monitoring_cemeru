# Experiment 024 — Fingerprint Risk Predictor

Analysis-only prediction from immutable fingerprint artifacts. No browser, Playwright, spoofing, or fingerprint generation was used.

## Executive Summary

Result: **SUCCESS**
Analyzed differing properties: **471**
Estimated opportunity: **3.9232%** for the top 10 risk properties.

## Risk Distribution

| Group | Count |
|---|---:|
| Critical | 9 |
| High | 10 |
| Medium | 440 |
| Low | 12 |

## Top 10 Highest-Risk Properties

| Rank | Property | Domain | Status | Severity | Risk | Gain |
|---:|---|---|---|---|---:|---:|
| 1 | navigator.userAgent | Navigator | DIFFERENT | Critical | 81.6 | 0.3965% |
| 2 | navigator.userAgentData.brands[1].version | Navigator | DIFFERENT | Critical | 81.6 | 0.3965% |
| 3 | navigator.userAgentData.brands[2].version | Navigator | DIFFERENT | Critical | 81.6 | 0.3965% |
| 4 | navigator.userAgentData.high_entropy.brands[1].version | Navigator | DIFFERENT | Critical | 81.6 | 0.3965% |
| 5 | navigator.userAgentData.high_entropy.brands[2].version | Navigator | DIFFERENT | Critical | 81.6 | 0.3965% |
| 6 | navigator.userAgentData.high_entropy.fullVersionList[1].version | Navigator | DIFFERENT | Critical | 81.6 | 0.3965% |
| 7 | navigator.userAgentData.high_entropy.fullVersionList[2].version | Navigator | DIFFERENT | Critical | 81.6 | 0.3965% |
| 8 | navigator.userAgentData.high_entropy.platformVersion | Navigator | DIFFERENT | Critical | 81.6 | 0.3965% |
| 9 | navigator.userAgentData.high_entropy.uaFullVersion | Navigator | DIFFERENT | Critical | 81.6 | 0.3965% |
| 10 | navigator.languages[1] | Navigator | MISSING | High | 73.0 | 0.3547% |

## Top 10 Quick Wins

| Rank | Property | Risk | Gain | Effort |
|---:|---|---:|---:|---:|
| 1 | canvas.hash | 66.75 | 0.3243% | 1.0 |
| 2 | canvas.length | 66.75 | 0.3243% | 1.0 |
| 3 | intl.collator.locale | 60.75 | 0.2952% | 1.0 |
| 4 | intl.listFormat.locale | 60.75 | 0.2952% | 1.0 |
| 5 | intl.numberFormat.locale | 60.75 | 0.2952% | 1.0 |
| 6 | timezone.locale | 60.75 | 0.2952% | 1.0 |
| 7 | navigator.language | 72.0 | 0.3499% | 1.5 |
| 8 | navigator.languages[0] | 72.0 | 0.3499% | 1.5 |
| 9 | navigator.userAgent | 81.6 | 0.3965% | 1.75 |
| 10 | navigator.userAgentData.brands[1].version | 81.6 | 0.3965% | 1.75 |

## Estimated Improvement Opportunities

| Fix top N | Estimated similarity improvement |
|---:|---:|
| 5 | 1.9825% |
| 10 | 3.9232% |
| 20 | 7.0853% |

## Recommendations

- **Critical — navigator.userAgent**: Align UA, UA-CH brands, platform, vendor, and version fields as one coherent browser profile. (Risk 81.6; estimated gain 0.3965.)
- **Critical — navigator.userAgentData.brands[1].version**: Align UA, UA-CH brands, platform, vendor, and version fields as one coherent browser profile. (Risk 81.6; estimated gain 0.3965.)
- **Critical — navigator.userAgentData.brands[2].version**: Align UA, UA-CH brands, platform, vendor, and version fields as one coherent browser profile. (Risk 81.6; estimated gain 0.3965.)
- **Critical — navigator.userAgentData.high_entropy.brands[1].version**: Align UA, UA-CH brands, platform, vendor, and version fields as one coherent browser profile. (Risk 81.6; estimated gain 0.3965.)
- **Critical — navigator.userAgentData.high_entropy.brands[2].version**: Align UA, UA-CH brands, platform, vendor, and version fields as one coherent browser profile. (Risk 81.6; estimated gain 0.3965.)
- **Critical — navigator.userAgentData.high_entropy.fullVersionList[1].version**: Align UA, UA-CH brands, platform, vendor, and version fields as one coherent browser profile. (Risk 81.6; estimated gain 0.3965.)
- **Critical — navigator.userAgentData.high_entropy.fullVersionList[2].version**: Align UA, UA-CH brands, platform, vendor, and version fields as one coherent browser profile. (Risk 81.6; estimated gain 0.3965.)
- **Critical — navigator.userAgentData.high_entropy.platformVersion**: Align UA, UA-CH brands, platform, vendor, and version fields as one coherent browser profile. (Risk 81.6; estimated gain 0.3965.)
- **Critical — navigator.userAgentData.high_entropy.uaFullVersion**: Align UA, UA-CH brands, platform, vendor, and version fields as one coherent browser profile. (Risk 81.6; estimated gain 0.3965.)
- **High — navigator.languages[1]**: Restore navigator.languages[1] with the native Navigator prototype/descriptor shape before tuning values. (Risk 73.0; estimated gain 0.3547.)
- **High — navigator.languages[2]**: Restore navigator.languages[2] with the native Navigator prototype/descriptor shape before tuning values. (Risk 73.0; estimated gain 0.3547.)
- **High — navigator.language**: Review the Navigator surface for value, descriptor, prototype, and cross-property consistency. (Risk 72.0; estimated gain 0.3499.)
- **High — navigator.languages[0]**: Review the Navigator surface for value, descriptor, prototype, and cross-property consistency. (Risk 72.0; estimated gain 0.3499.)
- **High — canvas.hash**: Review the Other surface for value, descriptor, prototype, and cross-property consistency. (Risk 66.75; estimated gain 0.3243.)
- **High — canvas.length**: Review the Other surface for value, descriptor, prototype, and cross-property consistency. (Risk 66.75; estimated gain 0.3243.)
- **High — intl.collator.locale**: Review the Environment surface for value, descriptor, prototype, and cross-property consistency. (Risk 60.75; estimated gain 0.2952.)
- **High — intl.listFormat.locale**: Review the Environment surface for value, descriptor, prototype, and cross-property consistency. (Risk 60.75; estimated gain 0.2952.)
- **High — intl.numberFormat.locale**: Review the Environment surface for value, descriptor, prototype, and cross-property consistency. (Risk 60.75; estimated gain 0.2952.)
- **High — timezone.locale**: Review the Environment surface for value, descriptor, prototype, and cross-property consistency. (Risk 60.75; estimated gain 0.2952.)
- **Medium — indexeddb.databases[0]**: Restore indexeddb.databases[0] with the native Storage prototype/descriptor shape before tuning values. (Risk 57.25; estimated gain 0.2782.)

## Validation

Validation is recorded in `validation.json`; input artifacts remain unchanged.
