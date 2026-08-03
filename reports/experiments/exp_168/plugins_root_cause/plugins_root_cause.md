# Experiment 043 - Plugins Difference Root Cause Analyzer

Offline, deterministic analysis of immutable Plugins artifacts. No browser, Playwright, network, or stealth code was used.

## Executive Summary

- Result: **SUCCESS**
- Remaining differences analyzed: **639**
- Unique root causes: **7**
- Estimated removable differences: **638**
- Estimated similarity opportunity (risk evidence plus conservative fallback): **3.3379%**

## Root Cause Ranking

| Rank | Root Cause | Object | Differences | Severity | Complexity | Gain | CF Impact | ROI | Action |
|---:|---|---|---:|---|---|---:|---:|---:|---|
| 1 | `wrong_native_function_surface` | Plugin | 14 | CRITICAL | Hard | 2.0328% | 82.00 | 0.58 | INVESTIGATE |
| 2 | `module_added_nonbaseline_surface` | Plugin | 333 | CRITICAL | Medium | 0.6660% | 66.92 | 0.33 | INVESTIGATE |
| 3 | `module_missing_baseline_surface` | Plugin | 125 | CRITICAL | Medium | 0.2500% | 62.00 | 0.12 | INVESTIGATE |
| 4 | `wrong_descriptor` | Plugin | 98 | CRITICAL | Hard | 0.1960% | 62.00 | 0.06 | INVESTIGATE |
| 5 | `wrong_prototype_chain` | Plugin | 60 | CRITICAL | Hard | 0.1200% | 62.00 | 0.03 | INVESTIGATE |
| 6 | `cross_reference_inconsistency` | MimeType | 8 | CRITICAL | Hard | 0.0160% | 62.00 | 0.00 | INVESTIGATE |
| 7 | `aggregate_fingerprint_mismatch` | Fingerprint aggregate | 1 | HIGH | Very Hard | 0.0571% | 15.00 | 0.01 | NEVER_PATCH |

## Cascade and Dependencies

| Root Cause | Depends On | Cascade Effects |
|---|---|---|
| `wrong_native_function_surface` | wrong_prototype_chain | aggregate_fingerprint_mismatch |
| `module_added_nonbaseline_surface` | wrong_prototype_chain | aggregate_fingerprint_mismatch |
| `module_missing_baseline_surface` | wrong_prototype_chain | aggregate_fingerprint_mismatch |
| `wrong_descriptor` | wrong_prototype_chain | aggregate_fingerprint_mismatch |
| `wrong_prototype_chain` | - | aggregate_fingerprint_mismatch, module_added_nonbaseline_surface, module_missing_baseline_surface, wrong_descriptor, wrong_native_function_surface |
| `cross_reference_inconsistency` | - | aggregate_fingerprint_mismatch |
| `aggregate_fingerprint_mismatch` | cross_reference_inconsistency, module_added_nonbaseline_surface, module_missing_baseline_surface, wrong_descriptor, wrong_native_function_surface, wrong_prototype_chain | - |

## Simulations

| Scenario | Differences Removed | Expected Gain | Predicted Overall | Best Case | Worst Case | Confidence |
|---|---:|---:|---:|---:|---:|---|
| `sim_aggregate_fingerprint_mismatch` | 1 | 0.0571% | 74.2371% | 0.0714% | 0.0285% | High |
| `sim_cross_reference_inconsistency` | 8 | 0.0160% | 74.1960% | 0.0182% | 0.0044% | Low |
| `sim_module_added_nonbaseline_surface` | 333 | 0.6660% | 74.8460% | 0.7576% | 0.1832% | Low |
| `sim_module_missing_baseline_surface` | 125 | 0.2500% | 74.4300% | 0.2844% | 0.0688% | Low |
| `sim_wrong_descriptor` | 98 | 0.1960% | 74.3760% | 0.2230% | 0.0539% | Low |
| `sim_wrong_native_function_surface` | 14 | 2.0328% | 76.2128% | 2.5410% | 1.0164% | High |
| `sim_wrong_prototype_chain` | 60 | 0.1200% | 74.3000% | 0.1365% | 0.0330% | Low |

## Grouped Findings

### By Property

- `plugins.items`: 305
- `mime_types.items`: 202
- `methods.plugin_prototypes`: 75
- `methods.mime_prototypes`: 56
- `fingerprint.sha256`: 1

### By Object

- `Plugin`: 380
- `MimeType`: 258
- `Fingerprint aggregate`: 1

### By Prototype

- `module_added_nonbaseline_surface`: 333
- `module_missing_baseline_surface`: 125
- `wrong_descriptor`: 98
- `wrong_prototype_chain`: 60
- `wrong_native_function_surface`: 14
- `cross_reference_inconsistency`: 8

### By Descriptor

- `module_added_nonbaseline_surface`: 261
- `module_missing_baseline_surface`: 115
- `wrong_descriptor`: 98
- `cross_reference_inconsistency`: 8
- `wrong_native_function_surface`: 7

### By Method

- `module_added_nonbaseline_surface`: 117
- `wrong_native_function_surface`: 14

### By Cross Reference

- `module_missing_baseline_surface`: 10
- `cross_reference_inconsistency`: 8

### By Plugin

- `plugins`: 305

### By Mimetype

- `mime_types`: 202

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
| Browser Launches | PASS |
| Network Requests | PASS |

## Final Conclusion

Root causes were identified deterministically from the enabled-capture remainder; aggregate hash mismatch is treated as a downstream symptom and not a patch target.
