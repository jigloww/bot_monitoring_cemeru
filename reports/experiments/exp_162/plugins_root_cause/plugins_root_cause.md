# Experiment 043 - Plugins Difference Root Cause Analyzer

Offline, deterministic analysis of immutable Plugins artifacts. No browser, Playwright, network, or stealth code was used.

## Executive Summary

- Result: **SUCCESS**
- Remaining differences analyzed: **639**
- Unique root causes: **6**
- Estimated removable differences: **638**
- Estimated similarity opportunity from risk evidence: **2.0899%**

## Root Cause Ranking

| Rank | Root Cause | Object | Differences | Severity | Complexity | Gain | CF Impact | ROI | Action |
|---:|---|---|---:|---|---|---:|---:|---:|---|
| 1 | `wrong_descriptor` | MimeType | 105 | CRITICAL | Hard | 1.0164% | 82.00 | 0.29 | INVESTIGATE |
| 2 | `wrong_prototype_chain` | MimeType | 67 | CRITICAL | Hard | 1.0164% | 82.00 | 0.29 | INVESTIGATE |
| 3 | `aggregate_fingerprint_mismatch` | Fingerprint aggregate | 1 | HIGH | Very Hard | 0.0571% | 15.00 | 0.01 | NEVER_PATCH |
| 4 | `cross_reference_inconsistency` | Native descriptor | 8 | CRITICAL | Hard | 0.0000% | 0.00 | 0.00 | INVESTIGATE |
| 5 | `module_added_nonbaseline_surface` | MimeType | 333 | CRITICAL | Medium | 0.0000% | 0.00 | 0.00 | INVESTIGATE |
| 6 | `module_missing_baseline_surface` | Native descriptor | 125 | CRITICAL | Medium | 0.0000% | 0.00 | 0.00 | INVESTIGATE |

## Cascade and Dependencies

| Root Cause | Depends On | Cascade Effects |
|---|---|---|
| `wrong_descriptor` | wrong_prototype_chain | aggregate_fingerprint_mismatch, aggregate_fingerprint_mismatch |
| `wrong_prototype_chain` | - | aggregate_fingerprint_mismatch, aggregate_fingerprint_mismatch, module_added_nonbaseline_surface, module_missing_baseline_surface, wrong_descriptor |
| `aggregate_fingerprint_mismatch` | cross_reference_inconsistency, module_added_nonbaseline_surface, module_missing_baseline_surface, profile_value_mismatch, unexpected_method_surface, wrong_descriptor, wrong_native_function_surface, wrong_prototype_chain | - |
| `cross_reference_inconsistency` | profile_value_mismatch | aggregate_fingerprint_mismatch, aggregate_fingerprint_mismatch |
| `module_added_nonbaseline_surface` | wrong_prototype_chain | aggregate_fingerprint_mismatch, aggregate_fingerprint_mismatch |
| `module_missing_baseline_surface` | wrong_prototype_chain | aggregate_fingerprint_mismatch, aggregate_fingerprint_mismatch |

## Simulations

| Scenario | Differences Removed | Expected Gain | Best Case | Worst Case | Confidence |
|---|---:|---:|---:|---:|---|
| `sim_aggregate_fingerprint_mismatch` | 1 | 0.0571% | 0.0714% | 0.0285% | High |
| `sim_cross_reference_inconsistency` | 8 | 0.0000% | 0.0000% | 0.0000% | Low |
| `sim_module_added_nonbaseline_surface` | 333 | 0.0000% | 0.0000% | 0.0000% | Low |
| `sim_module_missing_baseline_surface` | 125 | 0.0000% | 0.0000% | 0.0000% | Low |
| `sim_wrong_descriptor` | 105 | 1.0164% | 1.2197% | 0.4066% | Medium |
| `sim_wrong_prototype_chain` | 67 | 1.0164% | 1.2197% | 0.4066% | Medium |

## Grouped Findings

### By Property

- `plugins.items`: 305
- `mime_types.items`: 202
- `methods.plugin_prototypes`: 75
- `methods.mime_prototypes`: 56
- `fingerprint.sha256`: 1

### By Object

- `Native descriptor`: 401
- `Prototype chain`: 106
- `Plugin`: 75
- `MimeType`: 56
- `Fingerprint aggregate`: 1

### By Prototype

- `module_added_nonbaseline_surface`: 72
- `wrong_prototype_chain`: 67
- `module_missing_baseline_surface`: 10

### By Descriptor

- `module_added_nonbaseline_surface`: 261
- `module_missing_baseline_surface`: 115
- `wrong_descriptor`: 105
- `cross_reference_inconsistency`: 8

### By Method


### By Cross Reference


### By Plugin


### By Mimetype


## Validation

| Check | Status |
|---|---|
| Python Compile | PASS |
| Json Validation | PASS |
| Deterministic Ordering | PASS |
| Root Cause Uniqueness | PASS |
| Cascade Validation | PASS |
| Dependency Validation | PASS |
| Simulation Consistency | PASS |
| Immutable Input Verification | PASS |
| Offline Only | PASS |
| Browser Launches | FAIL |
| Network Requests | FAIL |

## Final Conclusion

Root causes were identified deterministically from the enabled-capture remainder; aggregate hash mismatch is treated as a downstream symptom and not a patch target.
