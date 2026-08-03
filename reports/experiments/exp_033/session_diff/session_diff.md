# Experiment 021 — Session Diff Analyzer

Analysis-only comparison. Source session artifacts were read but never changed.

## Executive Summary

Result: **DIFFERENT**
Session A: `reports\experiments\exp_031\session_profile`
Session B: `reports\experiments\exp_032\session_profile`
Overall similarity: **79.59%**

## Overall Similarity

| Metric | Similarity |
|---|---:|
| Overall | 79.59% |
| Fingerprint | 0.0% |
| Environment | 100.0% |
| Profile | None% |

## Browser Comparison

Similarity: **100.0%**

| Path | Status | Severity | Reason |
|---|---|---|---|
| `browser$.experiment_id` | UNKNOWN | INFO | Experiment metadata is intentionally excluded from similarity. |

## Navigator Comparison

Similarity: **100.0%**

| Path | Status | Severity | Reason |
|---|---|---|---|
| `navigator$.experiment_id` | UNKNOWN | INFO | Experiment metadata is intentionally excluded from similarity. |

## Storage Comparison

Similarity: **100.0%**

| Path | Status | Severity | Reason |
|---|---|---|---|
| `storage$.experiment_id` | UNKNOWN | INFO | Experiment metadata is intentionally excluded from similarity. |

## Permissions Comparison

Similarity: **100.0%**

| Path | Status | Severity | Reason |
|---|---|---|---|
| `permissions$.experiment_id` | UNKNOWN | INFO | Experiment metadata is intentionally excluded from similarity. |

## Environment Comparison

Similarity: **100.0%**

| Path | Status | Severity | Reason |
|---|---|---|---|
| `environment$.experiment_id` | UNKNOWN | INFO | Experiment metadata is intentionally excluded from similarity. |

## Fingerprint Comparison

Module match: **0.0%**

| Module | Status |
|---|---|
| environment | CHANGED |
| fonts | CHANGED |
| navigator | CHANGED |
| performance | CHANGED |
| permissions | CHANGED |
| screen | CHANGED |
| speech | CHANGED |
| storage | CHANGED |
| webgl | CHANGED |
| window | CHANGED |

## High Severity Changes

| Path | Status | Severity | Old | New |
|---|---|---|---|---|
| — | — | — | No high severity change | — |

## Recommendations

- No high-impact difference was observed; repeat with a valid browser session when optional APIs are available.

## Final Conclusion

Sessions are classified **DIFFERENT** based on comparable fields. Similarity is structural and does not prove browser equivalence or Cloudflare behavior.

Artifacts: `D:\bot_monitoring_cemeru\reports\experiments\exp_033\session_diff`
