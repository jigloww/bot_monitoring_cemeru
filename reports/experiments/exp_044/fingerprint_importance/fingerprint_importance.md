# Experiment 023 — Fingerprint Importance Analyzer

Analysis-only comparison of immutable fingerprint artifacts. No browser was launched.

## Executive Summary

Result: **SUCCESS**
Properties analyzed: **872**
Equal: **45.99%**
Estimated similarity gain: **100.0% weighted opportunity**

## Overall Importance Distribution

| Group | Count |
|---|---:|
| CRITICAL | 13 |
| HIGH | 0 |
| MEDIUM | 17 |
| LOW | 441 |
| INFORMATIONAL | 401 |

## Critical Findings

| Property | Category | Status | Importance | Confidence | Consistency |
|---|---|---|---:|---|---|
| navigator.language | Navigator | DIFFERENT | 95.0 | High | CONSISTENT |
| navigator.languages[0] | Navigator | DIFFERENT | 95.0 | High | CONSISTENT |
| navigator.languages[1] | Navigator | MISSING | 95.0 | High | CONSISTENT |
| navigator.languages[2] | Navigator | MISSING | 95.0 | High | CONSISTENT |
| navigator.userAgent | Navigator | DIFFERENT | 100.0 | Medium | INCONSISTENT |
| navigator.userAgentData.brands[1].version | Navigator | DIFFERENT | 100.0 | Medium | INCONSISTENT |
| navigator.userAgentData.brands[2].version | Navigator | DIFFERENT | 100.0 | Medium | INCONSISTENT |
| navigator.userAgentData.high_entropy.brands[1].version | Navigator | DIFFERENT | 100.0 | Medium | INCONSISTENT |
| navigator.userAgentData.high_entropy.brands[2].version | Navigator | DIFFERENT | 100.0 | Medium | INCONSISTENT |
| navigator.userAgentData.high_entropy.fullVersionList[1].version | Navigator | DIFFERENT | 100.0 | Medium | INCONSISTENT |
| navigator.userAgentData.high_entropy.fullVersionList[2].version | Navigator | DIFFERENT | 100.0 | Medium | INCONSISTENT |
| navigator.userAgentData.high_entropy.platformVersion | Navigator | DIFFERENT | 100.0 | Medium | INCONSISTENT |
| navigator.userAgentData.high_entropy.uaFullVersion | Navigator | DIFFERENT | 100.0 | Medium | INCONSISTENT |

## High Priority Findings

| Property | Category | Status | Importance | Confidence | Consistency |
|---|---|---|---:|---|---|
| — | — | none | 0 | — | — |

## Medium Findings

| Property | Category | Status | Importance | Confidence | Consistency |
|---|---|---|---:|---|---|
| canvas.hash | Other | DIFFERENT | 50.0 | High | UNKNOWN |
| canvas.length | Other | DIFFERENT | 50.0 | High | UNKNOWN |
| indexeddb | Storage | ADDED | 50.0 | High | UNKNOWN |
| indexeddb.count | Storage | MISSING | 50.0 | High | UNKNOWN |
| indexeddb.databases[0] | Storage | MISSING | 50.0 | High | UNKNOWN |
| indexeddb.databases[1] | Storage | MISSING | 50.0 | High | UNKNOWN |
| intl.collator.locale | Environment | DIFFERENT | 50.0 | High | UNKNOWN |
| intl.listFormat.locale | Environment | DIFFERENT | 50.0 | High | UNKNOWN |
| intl.numberFormat.locale | Environment | DIFFERENT | 50.0 | High | UNKNOWN |
| performance.now | Performance | DIFFERENT | 38.5 | Medium | INCONSISTENT |
| storage | Storage | ADDED | 50.0 | High | UNKNOWN |
| storage.caches_available | Storage | MISSING | 50.0 | High | UNKNOWN |
| storage.cookieStore_available | Storage | MISSING | 50.0 | High | UNKNOWN |
| storage.indexedDB_available | Storage | MISSING | 50.0 | High | UNKNOWN |
| storage.localStorage_length | Storage | MISSING | 50.0 | High | UNKNOWN |
| storage.sessionStorage_length | Storage | MISSING | 50.0 | High | UNKNOWN |
| timezone.locale | Environment | DIFFERENT | 50.0 | High | UNKNOWN |

## Low Findings

| Property | Category | Status | Importance | Confidence | Consistency |
|---|---|---|---:|---|---|
| battery | Other | ADDED | 25.0 | High | UNKNOWN |
| battery.charging | Other | MISSING | 25.0 | High | UNKNOWN |
| battery.chargingTime | Other | MISSING | 25.0 | High | UNKNOWN |
| battery.dischargingTime | Other | MISSING | 25.0 | High | UNKNOWN |
| battery.level | Other | MISSING | 25.0 | High | UNKNOWN |
| document | Other | ADDED | 25.0 | High | UNKNOWN |
| document.characterSet | Other | MISSING | 25.0 | High | UNKNOWN |
| document.compatMode | Other | MISSING | 25.0 | High | UNKNOWN |
| document.cookie_count | Other | MISSING | 25.0 | High | UNKNOWN |
| document.cookie_names[0] | Other | MISSING | 25.0 | High | UNKNOWN |
| document.cookie_names[1] | Other | MISSING | 25.0 | High | UNKNOWN |
| document.domain | Other | MISSING | 25.0 | High | UNKNOWN |
| document.readyState | Other | MISSING | 17.5 | Medium | UNKNOWN |
| document.referrer | Other | MISSING | 25.0 | High | UNKNOWN |
| document.title | Other | MISSING | 25.0 | High | UNKNOWN |
| document.visibilityState | Other | MISSING | 25.0 | High | UNKNOWN |
| features.ServiceWorker | Other | DIFFERENT | 25.0 | High | UNKNOWN |
| features.crypto_subtle | Other | DIFFERENT | 25.0 | High | UNKNOWN |
| features.notification_permission | Other | DIFFERENT | 25.0 | High | UNKNOWN |
| gpu.available | Other | DIFFERENT | 25.0 | High | UNKNOWN |
| hardware_apis.bluetooth | Other | DIFFERENT | 25.0 | High | UNKNOWN |
| hardware_apis.clipboard | Other | DIFFERENT | 25.0 | High | UNKNOWN |
| hardware_apis.hid | Other | DIFFERENT | 25.0 | High | UNKNOWN |
| hardware_apis.keyboard | Other | DIFFERENT | 25.0 | High | UNKNOWN |
| hardware_apis.serial | Other | DIFFERENT | 25.0 | High | UNKNOWN |
| hardware_apis.usb | Other | DIFFERENT | 25.0 | High | UNKNOWN |
| history.length | Other | DIFFERENT | 17.5 | Medium | UNKNOWN |
| media_capabilities.powerEfficient | Other | DIFFERENT | 25.0 | High | UNKNOWN |
| media_devices | Other | ADDED | 25.0 | High | UNKNOWN |
| media_devices[0].groupId | Other | MISSING | 25.0 | High | UNKNOWN |

## Estimated Similarity Gain

The estimate is the weighted share of currently non-equal properties. It is a prioritization signal, not a prediction of a future scorer result.

**100.0% weighted opportunity**

## Recommended Fix Order

| Priority | Property | Basis |
|---|---|---|
| CRITICAL | navigator.userAgent | Estimated importance 100.0 with Medium confidence. |
| CRITICAL | navigator.userAgentData.brands[1].version | Estimated importance 100.0 with Medium confidence. |
| CRITICAL | navigator.userAgentData.brands[2].version | Estimated importance 100.0 with Medium confidence. |
| CRITICAL | navigator.userAgentData.high_entropy.brands[1].version | Estimated importance 100.0 with Medium confidence. |
| CRITICAL | navigator.userAgentData.high_entropy.brands[2].version | Estimated importance 100.0 with Medium confidence. |
| CRITICAL | navigator.userAgentData.high_entropy.fullVersionList[1].version | Estimated importance 100.0 with Medium confidence. |
| CRITICAL | navigator.userAgentData.high_entropy.fullVersionList[2].version | Estimated importance 100.0 with Medium confidence. |
| CRITICAL | navigator.userAgentData.high_entropy.platformVersion | Estimated importance 100.0 with Medium confidence. |
| CRITICAL | navigator.userAgentData.high_entropy.uaFullVersion | Estimated importance 100.0 with Medium confidence. |
| CRITICAL | navigator.language | Estimated importance 95.0 with High confidence. |
| CRITICAL | navigator.languages[0] | Estimated importance 95.0 with High confidence. |
| CRITICAL | navigator.languages[1] | Estimated importance 95.0 with High confidence. |
| CRITICAL | navigator.languages[2] | Estimated importance 95.0 with High confidence. |
| MEDIUM | canvas.hash | Estimated importance 50.0 with High confidence. |
| MEDIUM | canvas.length | Estimated importance 50.0 with High confidence. |
| MEDIUM | indexeddb | Estimated importance 50.0 with High confidence. |
| MEDIUM | indexeddb.count | Estimated importance 50.0 with High confidence. |
| MEDIUM | indexeddb.databases[0] | Estimated importance 50.0 with High confidence. |
| MEDIUM | indexeddb.databases[1] | Estimated importance 50.0 with High confidence. |
| MEDIUM | intl.collator.locale | Estimated importance 50.0 with High confidence. |

## Validation

Validation details are recorded in `validation.json`; all source artifacts remain read-only.
