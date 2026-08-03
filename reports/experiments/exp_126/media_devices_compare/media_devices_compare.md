# Experiment 036 — MediaDevices Comparator

## Executive Summary

- Result: **SUCCESS**
- Real baseline: **D:\bot_monitoring_cemeru\reports\experiments\exp_122\media_devices**
- Playwright capture: **SUCCESS**
- Overall similarity: **100.00%**

## Similarity

| Domain | Similarity |
|---|---:|
| Availability | 100.00% |
| Descriptors | 100.00% |
| Devices | 100.00% |
| Fingerprint | 100.00% |
| Methods | 100.00% |
| Permissions | 100.00% |
| Prototype | 100.00% |

## Differences

- Total compared properties: **229**
- Equal: **229**
- Different: **0**
- Missing: **0**
- Added: **0**

## Severity

| Severity | Count |
|---|---:|
| CRITICAL | 0 |
| HIGH | 0 |
| LOW | 0 |
| MEDIUM | 0 |

## Validation

| Check | Status |
|---|---|
| Python Compile | PASS |
| Json Validation | PASS |
| Artifact Completeness | PASS |
| Deterministic Ordering | PASS |
| Serialization | PASS |
| Read Only Verification | PASS |
| No Stealth Injection | PASS |
| No Media Request | PASS |
| Thread Safety | PASS |
| Graceful Degradation | PASS |
| Valid | PASS |

## Read-only Boundary

The comparator only reads the real artifacts and evaluates native MediaDevices APIs. It does not inject stealth, request permissions, modify browser prototypes, intercept network traffic, or call media capture APIs.
