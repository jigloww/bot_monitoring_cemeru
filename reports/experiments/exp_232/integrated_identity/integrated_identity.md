# Experiment 060 - Integrated Fingerprint Collector

## Executive Summary

- Result: **SUCCESS**
- Identity UUID: `da9bb9e7-c0b7-585f-a8f2-8d3dde55fd15`
- Combined fingerprint: `2891a6a4d84c20674ecde8a9340e49da5c63329bb1e99c276aa912f8a44648c3`
- Modules ready: **9/9**
- Verification capture: **SUCCESS**

## Fingerprint Registry

| Module | Status | Experiment | Fingerprint |
|---|---|---|---|
| `canvas` | READY | `exp_225` | `efe7866b40f92edecf52029cbf01c58c6c9be3f0b310fb248d39c16fd12c964e` |
| `audio` | READY | `exp_227` | `ea3f7220ff7a69c03e6a9abdf41da9d073649d29dd050113d546a9ab5cb1dcfe` |
| `client_hints` | READY | `exp_231` | `27bb275e5ba78cbf76f0db9648bb09ad9cb12044573b3ed5e59169b733a98e4f` |
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
| `navigator_matches_client_hints` | WARNING | MEDIUM | Client Hints baseline is available; semantic platform fields require schema-specific comparison. |
| `fonts_match_canvas_metrics` | WARNING | MEDIUM | Font and canvas baselines are present; exact rendering correlation requires matching probe metadata. |
| `plugins_mimetypes_match_navigator` | PASS | INFO | Plugin baseline and Navigator baseline are both available. |
| `webrtc_matches_permissions` | PASS | INFO | WebRTC and Permissions baselines are both available for downstream behavioral comparison. |
| `module_fingerprint_uniqueness` | PASS | MEDIUM | No duplicate module fingerprint hashes were detected among available baselines. |

## Identity Graph

- Nodes: **10**
- Edges: **8**

## Module Fingerprints

- `audio`: `ea3f7220ff7a69c03e6a9abdf41da9d073649d29dd050113d546a9ab5cb1dcfe`
- `canvas`: `efe7866b40f92edecf52029cbf01c58c6c9be3f0b310fb248d39c16fd12c964e`
- `client_hints`: `27bb275e5ba78cbf76f0db9648bb09ad9cb12044573b3ed5e59169b733a98e4f`
- `fonts`: `28eb83b77505a0bece1f2a6286d0fc35da47ef8f225005048599b0ff8ceb3718`
- `navigator`: `f0f86803de2d0a223b4607031feebdd9445f8df3d831b736caad99bdba98d619`
- `permissions`: `e9487413999f6ffb21bb5de85af23d04c9df554018fa46482a0c57f039bf03e4`
- `plugins`: `5f4ca489bc043291b820688bbee69dd425fbf002d97c3d026b4c82e84bdea9e9`
- `screen`: `3e0ff0d3b5415773aab8789435a17101074812360417a9f91e423517ab8ba779`
- `webrtc`: `31b13feafe648f6b7ad5919b590023db273da27a7736f9a1490dbee4e9802419`

## Read-only Boundary

Only immutable baseline artifacts and one browser identity verification capture were used. No module probe, network request, browser modification, stealth injection, or permission/media operation was performed.
