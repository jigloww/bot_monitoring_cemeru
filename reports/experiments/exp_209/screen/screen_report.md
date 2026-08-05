# Experiment 056 - Screen Collector

## Executive Summary

- Result: **SUCCESS**
- Screen API available: **True**
- Screen getters: **9**
- Orientation: `landscape-primary` / `0`
- Fingerprint: `3e0ff0d3b5415773aab8789435a17101074812360417a9f91e423517ab8ba779`

The collector ran on about:blank through Browser Platform and performed only read operations.

## Screen Properties

| Property | Value | Stable | Reference Stable |
|---|---|---:|---:|
| `availHeight` | `720` | True | None |
| `availLeft` | `0` | True | None |
| `availTop` | `0` | True | None |
| `availWidth` | `1280` | True | None |
| `colorDepth` | `24` | True | None |
| `height` | `720` | True | None |
| `isExtended` | `None` | True | None |
| `orientation` | `{'constructor': 'ScreenOrientation', 'objectToString': '[object ScreenOrientation]', 'ownProperties': [], 'type': 'object'}` | True | True |
| `pixelDepth` | `24` | True | None |
| `width` | `1280` | True | None |

## Window and Viewport Cross-check

| Field | Value |
|---|---|
| `devicePixelRatio` | `1` |
| `documentClientHeight` | `720` |
| `documentClientWidth` | `1280` |
| `innerHeight` | `720` |
| `innerWidth` | `1280` |
| `matchMedia` | `4 queries` |
| `outerHeight` | `720` |
| `outerWidth` | `1280` |
| `visualViewport` | `{'height': 720, 'offsetLeft': 0, 'offsetTop': 0, 'pageLeft': 0, 'pageTop': 0, 'scale': 1, 'width': 1280}` |

## Orientation

| Field | Value |
|---|---|
| `angle` | `0` |
| `type` | `landscape-primary` |

## Validation

| Check | Status |
|---|---|
| Python Compile | PASS |
| Json Validation | PASS |
| Deterministic Ordering | PASS |
| Prototype Validation | PASS |
| Descriptor Validation | PASS |
| Viewport Consistency | PASS |
| Orientation Validation | PASS |
| Fingerprint Validation | PASS |
| Browser Platform Verification | PASS |
| Read Only Verification | PASS |
| No Browser Modification | PASS |
| No Network Requests | PASS |
| Historical Artifacts Immutable | PASS |

## Read-only Boundary

No screen or window property was written. No stealth injection, navigation, permission prompt, media access, or network API was used.
