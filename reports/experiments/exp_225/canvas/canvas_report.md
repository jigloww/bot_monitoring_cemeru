# Experiment 060B - Canonical Canvas Baseline

## Executive Summary

- Result: **SUCCESS**
- Browser Platform status: **AVAILABLE**
- Browser launches: **1**
- Network requests: **0**
- Fingerprint SHA-256: `efe7866b40f92edecf52029cbf01c58c6c9be3f0b310fb248d39c16fd12c964e`

## Canvas Surface

- Supported: **True**
- Canvas object: `HTMLCanvasElement` / `[object HTMLCanvasElement]`
- Dimensions: **240 x 80**
- OffscreenCanvas: **True**

## Capabilities

| Capability | Value |
|---|---|
| `context2d` | `True` |
| `supportedFormats` | `[{'mime': 'image/png', 'supported': True}, {'mime': 'image/jpeg', 'supported': True}, {'mime': 'image/webp', 'supported': True}]` |
| `toBlob` | `True` |
| `toDataURL` | `True` |
| `webgl` | `True` |
| `webgl2` | `True` |

## Native Methods

| Group | Method | Available | Native source | Illegal invocation |
|---|---|---|---|---|
| `canvas` | `toBlob` | True | True | True |
| `canvas` | `toDataURL` | True | True | True |
| `constructor` | `CanvasRenderingContext2D` | True | True | None |
| `constructor` | `HTMLCanvasElement` | True | True | None |
| `constructor` | `OffscreenCanvas` | True | True | None |
| `context` | `getImageData` | True | True | True |
| `context` | `isPointInPath` | True | True | True |
| `context` | `isPointInStroke` | True | True | True |
| `context` | `measureText` | True | True | True |

## Validation

- Validation: **PASS**
- No stealth injection, canvas spoofing, network request, or historical artifact mutation was performed.
