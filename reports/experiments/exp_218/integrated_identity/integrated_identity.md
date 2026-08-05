# Experiment 060 - Integrated Fingerprint Collector

## Executive Summary

- Result: **PARTIAL**
- Identity UUID: `6fbc5d63-4fa3-5a10-ac3a-1ab5c284d3c5`
- Combined fingerprint: `d88ddd1daba76ecd6b5f47d89545b50682a6d3b6f1366e6d5299cf28c2caf637`
- Modules ready: **6/9**
- Verification capture: **SUCCESS**

## Fingerprint Registry

| Module | Status | Experiment | Fingerprint |
|---|---|---|---|
| `canvas` | UNVERIFIED | `exp_079` | `None` |
| `audio` | UNVERIFIED | `exp_080` | `None` |
| `client_hints` | UNVERIFIED | `exp_081` | `None` |
| `plugins` | READY | `exp_142` | `5f4ca489bc043291b820688bbee69dd425fbf002d97c3d026b4c82e84bdea9e9` |
| `webrtc` | READY | `exp_174` | `31b13feafe648f6b7ad5919b590023db273da27a7736f9a1490dbee4e9802419` |
| `navigator` | READY | `exp_197` | `f0f86803de2d0a223b4607031feebdd9445f8df3d831b736caad99bdba98d619` |
| `permissions` | READY | `exp_206` | `e9487413999f6ffb21bb5de85af23d04c9df554018fa46482a0c57f039bf03e4` |
| `screen` | READY | `exp_209` | `3e0ff0d3b5415773aab8789435a17101074812360417a9f91e423517ab8ba779` |
| `fonts` | READY | `exp_212` | `28eb83b77505a0bece1f2a6286d0fc35da47ef8f225005048599b0ff8ceb3718` |

## Consistency

| Rule | Status | Severity | Reason |
|---|---|---|---|
| `navigator_platform_matches_verification` | PASS | INFO | Navigator platform was compared with the single verification capture. |
| `screen_matches_viewport` | PASS | INFO | Screen dimensions were checked against the verification viewport. |
| `screen_avail_dimensions` | PASS | INFO | Screen dimensions must be greater than or equal to available dimensions. |
| `navigator_matches_client_hints` | UNKNOWN | LOW | Client Hints baseline is unavailable. |
| `fonts_match_canvas_metrics` | UNKNOWN | LOW | Fonts or Canvas baseline is unavailable. |
| `plugins_mimetypes_match_navigator` | PASS | INFO | Plugin baseline and Navigator baseline are both available. |
| `webrtc_matches_permissions` | PASS | INFO | WebRTC and Permissions baselines are both available for downstream behavioral comparison. |
| `module_fingerprint_uniqueness` | PASS | MEDIUM | No duplicate module fingerprint hashes were detected among available baselines. |

## Identity Graph

- Nodes: **10**
- Edges: **8**

## Module Fingerprints

- `audio`: `None`
- `canvas`: `None`
- `client_hints`: `None`
- `fonts`: `28eb83b77505a0bece1f2a6286d0fc35da47ef8f225005048599b0ff8ceb3718`
- `navigator`: `f0f86803de2d0a223b4607031feebdd9445f8df3d831b736caad99bdba98d619`
- `permissions`: `e9487413999f6ffb21bb5de85af23d04c9df554018fa46482a0c57f039bf03e4`
- `plugins`: `5f4ca489bc043291b820688bbee69dd425fbf002d97c3d026b4c82e84bdea9e9`
- `screen`: `3e0ff0d3b5415773aab8789435a17101074812360417a9f91e423517ab8ba779`
- `webrtc`: `31b13feafe648f6b7ad5919b590023db273da27a7736f9a1490dbee4e9802419`

## Read-only Boundary

Only immutable baseline artifacts and one browser identity verification capture were used. No module probe, network request, browser modification, stealth injection, or permission/media operation was performed.
