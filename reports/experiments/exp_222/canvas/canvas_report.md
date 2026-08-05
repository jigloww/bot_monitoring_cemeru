# Experiment 060B - Canonical Canvas Baseline

## Executive Summary

- Result: **SUCCESS**
- Browser Platform status: **AVAILABLE**
- Browser launches: **1**
- Network requests: **0**
- Fingerprint SHA-256: `b5c302448d4a02cc2d11fad220147bf98037bec418f31021665494a1c07afcc9`

## Canvas Surface

- Supported: **False**
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
| `webgl` | `False` |
| `webgl2` | `False` |

## Native Methods

| Group | Method | Available | Native source | Illegal invocation |
|---|---|---|---|---|
| `canvas` | `toBlob` | True | True | True |
| `canvas` | `toDataURL` | True | True | True |
| `constructor` | `CanvasRenderingContext2D` | None | True | None |
| `constructor` | `HTMLCanvasElement` | None | True | None |
| `constructor` | `OffscreenCanvas` | None | True | None |
| `context` | `getImageData` | True | True | True |
| `context` | `isPointInPath` | True | True | True |
| `context` | `isPointInStroke` | True | True | True |
| `context` | `measureText` | True | True | True |

## Validation

- Validation: **PASS**
- No stealth injection, canvas spoofing, network request, or historical artifact mutation was performed.
