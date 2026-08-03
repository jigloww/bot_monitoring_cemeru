# Experiment 039 — Plugins & MimeTypes Comparator

## Executive Summary

- Result: **SUCCESS**
- Overall similarity: **61.34%**
- Real plugins / mimeTypes: **5 / 2**
- Playwright plugins / mimeTypes: **0 / 0**
- Total differences: **279**

## Similarity

| Domain | Similarity |
|---|---:|
| Plugins | 89.38% |
| Mime Types | 93.70% |
| Prototype | 60.00% |
| Descriptors | 100.00% |
| Methods | 35.17% |
| Cross Reference | 12.50% |
| Fingerprint | 0.00% |

## Difference Summary

| Status | Count |
|---|---:|
| Equal | 528 |
| Changed | 3 |
| Missing | 261 |
| Added | 8 |
| Removed | 7 |

## Critical Differences

| Path | Status | Reason |
|---|---|---|
| `methods.mime_prototypes` | ADDED | The property exists in Playwright but is absent from the Real Browser baseline. |
| `methods.mime_prototypes.0.constructor.available` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.0.constructor.descriptor.configurable` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.0.constructor.descriptor.enumerable` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.0.constructor.descriptor.getterSource` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.0.constructor.descriptor.hasGetter` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.0.constructor.descriptor.hasSetter` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.0.constructor.descriptor.setterSource` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.0.constructor.descriptor.valueSource` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.0.constructor.descriptor.valueType` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.0.constructor.descriptor.writable` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.0.constructor.nativeSource` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.0.constructor.source` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.0.constructor.typeof` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.1.constructor.available` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.1.constructor.descriptor.configurable` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.1.constructor.descriptor.enumerable` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.1.constructor.descriptor.getterSource` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.1.constructor.descriptor.hasGetter` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |
| `methods.mime_prototypes.1.constructor.descriptor.hasSetter` | MISSING | The property exists in the Real Browser baseline but is absent from Playwright. |

## Validation

| Check | Status |
|---|---|
| Python Compile | PASS |
| Json Validation | PASS |
| Artifact Completeness | PASS |
| Deterministic Ordering | PASS |
| Serialization | PASS |
| Graceful Missing Field Handling | PASS |
| Read Only Verification | PASS |
| No Stealth Injection | PASS |
| Immutable Inputs | PASS |
| Independent Inputs | PASS |
| Fingerprint Hash Validation | PASS |
| Browser Platform Entrypoint | PASS |
| Valid | PASS |

## Read-only Boundary

The comparator reads immutable artifacts and native browser observations only. It does not inject stealth, modify navigator prototypes, request permissions, or intercept network traffic.
