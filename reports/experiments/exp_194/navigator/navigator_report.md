# Experiment 049 - Real Navigator Collector

## Executive Summary

- Result: **SUCCESS**
- Navigator fields: **21**
- Prototype properties: **37**
- Sub-APIs inspected: **19**
- Available sub-APIs: **3**
- Fingerprint: `f0f86803de2d0a223b4607031feebdd9445f8df3d831b736caad99bdba98d619`

The collector inspected `about:blank` through Browser Platform only. No permission query, media capture, network navigation, stealth injection, or browser mutation was performed.

## Primitive Values

| Property | Value |
|---|---|
| `appCodeName` | `Mozilla` |
| `appName` | `Netscape` |
| `appVersion` | `5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/151.0.0.0 Safari/537.36` |
| `buildID` | `None` |
| `cookieEnabled` | `True` |
| `deviceMemory` | `None` |
| `doNotTrack` | `None` |
| `hardwareConcurrency` | `12` |
| `language` | `en-US` |
| `languages` | `en-US, en` |
| `maxTouchPoints` | `0` |
| `onLine` | `True` |
| `oscpu` | `None` |
| `pdfViewerEnabled` | `True` |
| `platform` | `Win32` |
| `product` | `Gecko` |
| `productSub` | `20030107` |
| `userAgent` | `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/151.0.0.0 Safari/537.36` |
| `vendor` | `Google Inc.` |
| `vendorSub` | `` |
| `webdriver` | `True` |

## Sub-API Availability

| API | Available | Constructor | Methods |
|---|---|---|---:|
| `bluetooth` | False | `None` | 0 |
| `clipboard` | False | `None` | 0 |
| `connection` | True | `NetworkInformation` | 1 |
| `credentials` | False | `None` | 0 |
| `gpu` | False | `None` | 0 |
| `hid` | False | `None` | 0 |
| `keyboard` | False | `None` | 0 |
| `locks` | False | `None` | 0 |
| `mediaCapabilities` | True | `MediaCapabilities` | 3 |
| `mediaDevices` | False | `None` | 0 |
| `permissions` | True | `Permissions` | 2 |
| `presentation` | False | `None` | 0 |
| `serial` | False | `None` | 0 |
| `serviceWorker` | False | `None` | 0 |
| `storage` | False | `None` | 0 |
| `usb` | False | `None` | 0 |
| `virtualKeyboard` | False | `None` | 0 |
| `wakeLock` | False | `None` | 0 |
| `xr` | False | `None` | 0 |

## Statistics

| Metric | Value |
|---|---:|
| `available_subapi_count` | 3 |
| `browser_launches` | 1 |
| `capture_status` | SUCCESS |
| `descriptor_count` | 37 |
| `getter_count` | 31 |
| `getter_illegal_invocation_count` | 31 |
| `getter_illegal_throw_count` | 31 |
| `native_source_count` | 11 |
| `native_source_failures` | 0 |
| `navigator_inherited_property_count` | 48 |
| `navigator_method_count` | 5 |
| `navigator_own_property_count` | 0 |
| `network_requests` | 0 |
| `primitive_value_count` | 21 |
| `prototype_property_count` | 37 |
| `setter_count` | 0 |
| `subapi_count` | 19 |
| `subapi_method_count` | 6 |

## Validation

| Check | Status |
|---|---|
| Python Compile | PASS |
| Json Validation | PASS |
| Deterministic Ordering | PASS |
| Prototype Validation | PASS |
| Descriptor Validation | PASS |
| Native Source Validation | PASS |
| Browser Platform Verification | PASS |
| Read Only Verification | PASS |
| No Permission Prompts | PASS |
| No Media Capture | PASS |
| No Network Calls | PASS |
| Sha256 Validation | PASS |
| Historical Artifacts Modified | FAIL |

## Read-only Boundary

Only property reads, descriptor reads, native-source inspection, and illegal-receiver checks were performed. Sensitive sub-API methods were not invoked.
