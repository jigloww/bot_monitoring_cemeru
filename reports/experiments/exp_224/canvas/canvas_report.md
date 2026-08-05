# Experiment 060B - Canonical Canvas Baseline

## Executive Summary

- Result: **SUCCESS**
- Browser Platform status: **AVAILABLE**
- Browser launches: **1**
- Network requests: **0**
- Fingerprint SHA-256: `8d666c551c69df9c78ba7d8d1fdaa5214857dd582736b7530d7ab70f91928dac`

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
| `webgl` | `True` |
| `webgl2` | `True` |

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
