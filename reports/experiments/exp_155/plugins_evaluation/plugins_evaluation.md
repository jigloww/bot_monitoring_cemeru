# Experiment 042 - Plugins Stealth Evaluation

## Executive Summary

- Result: **SUCCESS**
- Conclusion: **Plugins module improved similarity without stable regression.**
- Resolved differences: **249**
- Regression count: **0**
- Total diff: **275 -> 639 (+364)**

## Measured Similarity

| Mode | Overall | Plugin | MimeType | Prototype | Descriptor | Method | Cross-reference | Total Diff | Resolved | Regressions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Plain | 61.59% | 89.38% | 93.70% | 60.00% | 100.00% | 35.38% | 14.29% | 275 | 0 | 0 |
| Plugins | 74.18% | 72.74% | 49.25% | 100.00% | 100.00% | 71.46% | 100.00% | 639 | 249 | 0 |

## Delta

- Overall delta: **+12.59%**
- Plugin delta: **-16.64%**
- MimeType delta: **-44.45%**

## Difference Accounting

Stable regressions count only properties that were equal in Plain and became non-equal after enabling the module. Total diff is reported separately so object-shape changes remain visible.
- Plain non-equal properties: **275**
- Plugins non-equal properties: **639**
- Resolved Plain differences: **249**

## Validation

| Check | Status |
|---|---|
| Python Compile | PASS |
| Json Validation | PASS |
| Artifact Completeness | PASS |
| Deterministic Ordering | PASS |
| Prototype Validation | PASS |
| Descriptor Validation | PASS |
| Native Source Validation | PASS |
| Cross Reference Validation | PASS |
| Regression Detection | PASS |
| Browser Platform Verification | PASS |
| Plugins Module Only | PASS |
| Immutable Input Verification | PASS |
| Valid | PASS |

## Conclusion

Plugins module improved similarity without stable regression.

The evaluation uses the immutable Real Browser profile as input and applies only `stealth/modules/plugins.js`; no other browser or network surface is changed.
