# Experiment 060A - Browser Identity Baseline Audit

## Executive Summary

- Result: **PARTIAL**
- Integrated Identity inspected: `exp_218`
- Modules audited: **3**
- Browser launches: **0**
- Network requests: **0**

## Per-module diagnosis

| Module | Experiment | Fingerprint | SHA-256 | Schema | Discovery status |
|---|---:|---|---|---|---|
| `canvas` | `exp_079` | yes | no | incompatible | **DISCOVERED_UNVERIFIED** |
| `audio` | `exp_080` | yes | no | incompatible | **DISCOVERED_UNVERIFIED** |
| `client_hints` | `exp_081` | yes | no | incompatible | **DISCOVERED_UNVERIFIED** |

## Exact reasons

### canvas

- Artifact directory: `D:\bot_monitoring_cemeru\reports\experiments\exp_079\canvas`
- Discovered by Integrated Identity: **True**
- Reason codes: `collector validation reports Playwright status UNKNOWN, fingerprint.json has no top-level data object, fingerprint.json has no top-level sha256, statistics.json is absent (not an integrated identity discovery gate), summary.json does not contain result="SUCCESS"`

### audio

- Artifact directory: `D:\bot_monitoring_cemeru\reports\experiments\exp_080\audio`
- Discovered by Integrated Identity: **True**
- Reason codes: `collector validation reports Playwright status UNKNOWN, fingerprint.json has no top-level data object, fingerprint.json has no top-level sha256, statistics.json is absent (not an integrated identity discovery gate), summary.json does not contain result="SUCCESS"`

### client_hints

- Artifact directory: `D:\bot_monitoring_cemeru\reports\experiments\exp_081\client_hints`
- Discovered by Integrated Identity: **True**
- Reason codes: `collector validation reports Playwright status UNKNOWN, fingerprint.json has no top-level data object, fingerprint.json has no top-level sha256, statistics.json is absent (not an integrated identity discovery gate), summary.json does not contain result="SUCCESS"`

## Integrated Identity schema

- Source: `D:\bot_monitoring_cemeru\experiments\integrated_identity.py`
- Mandatory discovery files: `fingerprint.json`
- Verified fingerprint fields: top-level `sha256` (64 hex characters) and `data` object.
- Successful candidate additionally requires `summary.json.result == "SUCCESS"` and `validation.json.valid == true`.
- Missing `statistics.json` is reported but is not a discovery gate.

## Registry check

- Registry valid: **True**
- Entries present: **True**
- Audit selection matches registry: **True**

## Recommendations

- **HIGH** `audio.baseline_capture`: Capture an independent real-browser baseline using the integrated identity schema. (collector validation reports Playwright status UNKNOWN; fingerprint.json has no top-level data object; fingerprint.json has no top-level sha256; statistics.json is absent (not an integrated identity discovery gate); summary.json does not contain result="SUCCESS")
- **HIGH** `canvas.baseline_capture`: Capture an independent real-browser baseline using the integrated identity schema. (collector validation reports Playwright status UNKNOWN; fingerprint.json has no top-level data object; fingerprint.json has no top-level sha256; statistics.json is absent (not an integrated identity discovery gate); summary.json does not contain result="SUCCESS")
- **HIGH** `client_hints.baseline_capture`: Capture an independent real-browser baseline using the integrated identity schema. (collector validation reports Playwright status UNKNOWN; fingerprint.json has no top-level data object; fingerprint.json has no top-level sha256; statistics.json is absent (not an integrated identity discovery gate); summary.json does not contain result="SUCCESS")
- **LOW** `audio.statistics_optional`: Add statistics.json to future baseline captures for audit completeness. (Statistics are not a discovery gate but are requested by the audit.)
- **LOW** `canvas.statistics_optional`: Add statistics.json to future baseline captures for audit completeness. (Statistics are not a discovery gate but are requested by the audit.)
- **LOW** `client_hints.statistics_optional`: Add statistics.json to future baseline captures for audit completeness. (Statistics are not a discovery gate but are requested by the audit.)
- **MEDIUM** `integrated_identity.rerun`: Rerun Experiment 060 only after all three schemas satisfy the source contract. (The current PARTIAL result is data-quality driven, not a browser consistency failure.)

## Validation

- Validation: **PASS**
- This report is read-only and contains no regenerated baseline data.
