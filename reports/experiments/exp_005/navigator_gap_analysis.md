# Experiment 003 — Navigator Gap Analysis

Reference: `reports\fingerprint\fingerprint_real.json`  
Navigator Module: `reports\experiments\exp_001\navigator\fingerprint.json`  
Plain Context: `reports\experiments\exp_001\plain\fingerprint.json`

## Summary

| Metric | Value |
|---|---:|
| Navigator Success % | 84.55% |
| Navigator Properties | 110 |
| Equal | 93 |
| Remaining Difference | 11 |
| Regression | 1 |
| Unexpected Difference | 5 |
| Remaining Critical | 9 |
| Remaining High | 0 |
| Remaining Medium | 1 |
| Remaining Low | 7 |

## Property Analysis

| Property | Reference | Navigator | Severity | Reason | Possible Cause | Recommended Fix | Confidence |
|---|---|---|---|---|---|---|---|
| `navigator.appCodeName` | "Mozilla" | "Mozilla" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.appName` | "Netscape" | "Netscape" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.appVersion` | "5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.… | "5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/… | Low | The module changed or exposed a difference outside its declared Navigator target surface. | Cross-property inconsistency | Align UA, platform, vendor, and UA-CH as one browser profile. | Medium |
| `navigator.connection` | {"effectiveType":"4g","downlink":10,"rtt":50,"saveData":false,"type":null} | {"effectiveType":"4g","downlink":9.4,"rtt":0,"saveData":false,"type":null} | Low | The module changed or exposed a difference outside its declared Navigator target surface. | Dynamic value | Do not hardcode network telemetry; collect or model it consistently for the environment. | Medium |
| `navigator.connection.downlink` | 10 | 9.4 | Low | Plain matched the reference, but the Navigator module changed this property away from it. | Dynamic value | Do not hardcode network telemetry; collect or model it consistently for the environment. | Medium |
| `navigator.connection.effectiveType` | "4g" | "4g" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.connection.rtt` | 50 | 0 | Low | The module changed or exposed a difference outside its declared Navigator target surface. | Dynamic value | Do not hardcode network telemetry; collect or model it consistently for the environment. | Medium |
| `navigator.connection.saveData` | false | false | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.connection.type` | null | null | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.cookieEnabled` | true | true | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.deviceMemory` | 8 | 8 | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.doNotTrack` | null | null | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.hardwareConcurrency` | 12 | 12 | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.javaEnabled` | false | false | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.keys` | [] | [] | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.language` | "en-US" | "en-GB" | Low | Navigator value remains different from the reference after the module was applied. | Cross-property inconsistency | Derive this value from the same locale, OS, and browser profile. | Medium |
| `navigator.languages` | ["en-US","en","id"] | ["en-GB"] | Medium | Navigator value remains different from the reference after the module was applied. | Cross-property inconsistency | Derive this value from the same locale, OS, and browser profile. | Medium |
| `navigator.maxTouchPoints` | 0 | 0 | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.onLine` | true | true | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.oscpu` | null | null | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.pdfViewerEnabled` | true | true | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.platform` | "Win32" | "Win32" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.product` | "Gecko" | "Gecko" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.productSub` | "20030107" | "20030107" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.prototype_keys` | ["vendorSub","productSub","vendor","maxTouchPoints","scheduling","userActivation","geoloc… | ["vendorSub","productSub","vendor","maxTouchPoints","scheduling","userActivation","geoloc… | Low | The module changed or exposed a difference outside its declared Navigator target surface. | Wrong prototype | Compare the Navigator prototype chain and enumerable own-key surface. | High |
| `navigator.userAgent` | "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/… | "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Headles… | Low | The module changed or exposed a difference outside its declared Navigator target surface. | Cross-property inconsistency | Align UA, platform, vendor, and UA-CH as one browser profile. | Medium |
| `navigator.userAgentData` | {"brands":[{"brand":"Not;A=Brand","version":"8"},{"brand":"Chromium","version":"150"},{"b… | {"brands":[{"brand":"Not;A=Brand","version":"8"},{"brand":"Chromium","version":"149"},{"b… | Critical | Navigator value remains different from the reference after the module was applied. | Cross-property inconsistency | Keep UA-CH brands, platform, mobile, and high-entropy values coherent. | Medium |
| `navigator.userAgentData.brands[0].brand` | "Not;A=Brand" | "Not;A=Brand" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.brands[0].version` | "8" | "8" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.brands[1].brand` | "Chromium" | "Chromium" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.brands[1].version` | "150" | "149" | Critical | Navigator supplied a value that was absent in Plain, but it still does not match the reference. | Cross-property inconsistency | Keep UA-CH brands, platform, mobile, and high-entropy values coherent. | Medium |
| `navigator.userAgentData.brands[2].brand` | "Google Chrome" | "Google Chrome" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.brands[2].version` | "150" | "149" | Critical | Navigator supplied a value that was absent in Plain, but it still does not match the reference. | Cross-property inconsistency | Keep UA-CH brands, platform, mobile, and high-entropy values coherent. | Medium |
| `navigator.userAgentData.high_entropy.architecture` | "x86" | "x86" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.bitness` | "64" | "64" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.brands[0].brand` | "Not;A=Brand" | "Not;A=Brand" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.brands[0].version` | "8" | "8" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.brands[1].brand` | "Chromium" | "Chromium" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.brands[1].version` | "150" | "149" | Critical | Navigator supplied a value that was absent in Plain, but it still does not match the reference. | Cross-property inconsistency | Keep UA-CH brands, platform, mobile, and high-entropy values coherent. | Medium |
| `navigator.userAgentData.high_entropy.brands[2].brand` | "Google Chrome" | "Google Chrome" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.brands[2].version` | "150" | "149" | Critical | Navigator supplied a value that was absent in Plain, but it still does not match the reference. | Cross-property inconsistency | Keep UA-CH brands, platform, mobile, and high-entropy values coherent. | Medium |
| `navigator.userAgentData.high_entropy.fullVersionList[0].brand` | "Not;A=Brand" | "Not;A=Brand" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.fullVersionList[0].version` | "8.0.0.0" | "8.0.0.0" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.fullVersionList[1].brand` | "Chromium" | "Chromium" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.fullVersionList[1].version` | "150.0.7871.115" | "149.0.0.0" | Critical | Navigator supplied a value that was absent in Plain, but it still does not match the reference. | Cross-property inconsistency | Keep UA-CH brands, platform, mobile, and high-entropy values coherent. | Medium |
| `navigator.userAgentData.high_entropy.fullVersionList[2].brand` | "Google Chrome" | "Google Chrome" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.fullVersionList[2].version` | "150.0.7871.115" | "149.0.0.0" | Critical | Navigator supplied a value that was absent in Plain, but it still does not match the reference. | Cross-property inconsistency | Keep UA-CH brands, platform, mobile, and high-entropy values coherent. | Medium |
| `navigator.userAgentData.high_entropy.mobile` | false | false | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.model` | "" | "" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.platform` | "Windows" | "Windows" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.high_entropy.platformVersion` | "19.0.0" | "" | Critical | Navigator supplied a value that was absent in Plain, but it still does not match the reference. | Cross-property inconsistency | Keep UA-CH brands, platform, mobile, and high-entropy values coherent. | Medium |
| `navigator.userAgentData.high_entropy.uaFullVersion` | "150.0.7871.115" | "149.0.0.0" | Critical | Navigator supplied a value that was absent in Plain, but it still does not match the reference. | Cross-property inconsistency | Keep UA-CH brands, platform, mobile, and high-entropy values coherent. | Medium |
| `navigator.userAgentData.mobile` | false | false | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.userAgentData.platform` | "Windows" | "Windows" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.vendor` | "Google Inc." | "Google Inc." | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.vendorSub` | "" | "" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `navigator.webdriver` | false | false | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.mime_count` | 2 | 2 | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.mime_types[0].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.mime_types[0].suffixes` | "pdf" | "pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.mime_types[0].type` | "application/pdf" | "application/pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.mime_types[1].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.mime_types[1].suffixes` | "pdf" | "pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.mime_types[1].type` | "text/pdf" | "text/pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugin_count` | 5 | 5 | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[0].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[0].filename` | "internal-pdf-viewer" | "internal-pdf-viewer" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[0].mimes[0].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[0].mimes[0].suffixes` | "pdf" | "pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[0].mimes[0].type` | "application/pdf" | "application/pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[0].mimes[1].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[0].mimes[1].suffixes` | "pdf" | "pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[0].mimes[1].type` | "text/pdf" | "text/pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[0].name` | "PDF Viewer" | "PDF Viewer" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[1].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[1].filename` | "internal-pdf-viewer" | "internal-pdf-viewer" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[1].mimes[0].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[1].mimes[0].suffixes` | "pdf" | "pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[1].mimes[0].type` | "application/pdf" | "application/pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[1].mimes[1].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[1].mimes[1].suffixes` | "pdf" | "pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[1].mimes[1].type` | "text/pdf" | "text/pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[1].name` | "Chrome PDF Viewer" | "Chrome PDF Viewer" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[2].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[2].filename` | "internal-pdf-viewer" | "internal-pdf-viewer" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[2].mimes[0].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[2].mimes[0].suffixes` | "pdf" | "pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[2].mimes[0].type` | "application/pdf" | "application/pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[2].mimes[1].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[2].mimes[1].suffixes` | "pdf" | "pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[2].mimes[1].type` | "text/pdf" | "text/pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[2].name` | "Chromium PDF Viewer" | "Chromium PDF Viewer" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[3].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[3].filename` | "internal-pdf-viewer" | "internal-pdf-viewer" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[3].mimes[0].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[3].mimes[0].suffixes` | "pdf" | "pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[3].mimes[0].type` | "application/pdf" | "application/pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[3].mimes[1].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[3].mimes[1].suffixes` | "pdf" | "pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[3].mimes[1].type` | "text/pdf" | "text/pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[3].name` | "Microsoft Edge PDF Viewer" | "Microsoft Edge PDF Viewer" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[4].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[4].filename` | "internal-pdf-viewer" | "internal-pdf-viewer" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[4].mimes[0].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[4].mimes[0].suffixes` | "pdf" | "pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[4].mimes[0].type` | "application/pdf" | "application/pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[4].mimes[1].description` | "Portable Document Format" | "Portable Document Format" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[4].mimes[1].suffixes` | "pdf" | "pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[4].mimes[1].type` | "text/pdf" | "text/pdf" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |
| `plugins.plugins[4].name` | "WebKit built-in PDF" | "WebKit built-in PDF" | Low | Navigator value matches the reference. | Unknown | No gap remains; no root-cause investigation is required. | High |

## Top 10 Easiest Fixes

- `navigator.appVersion` (Low, Cross-property inconsistency): Align UA, platform, vendor, and UA-CH as one browser profile.
- `navigator.connection` (Low, Dynamic value): Do not hardcode network telemetry; collect or model it consistently for the environment.
- `navigator.connection.downlink` (Low, Dynamic value): Do not hardcode network telemetry; collect or model it consistently for the environment.
- `navigator.connection.rtt` (Low, Dynamic value): Do not hardcode network telemetry; collect or model it consistently for the environment.
- `navigator.language` (Low, Cross-property inconsistency): Derive this value from the same locale, OS, and browser profile.
- `navigator.prototype_keys` (Low, Wrong prototype): Compare the Navigator prototype chain and enumerable own-key surface.
- `navigator.userAgent` (Low, Cross-property inconsistency): Align UA, platform, vendor, and UA-CH as one browser profile.
- `navigator.languages` (Medium, Cross-property inconsistency): Derive this value from the same locale, OS, and browser profile.
- `navigator.userAgentData` (Critical, Cross-property inconsistency): Keep UA-CH brands, platform, mobile, and high-entropy values coherent.
- `navigator.userAgentData.brands[1].version` (Critical, Cross-property inconsistency): Keep UA-CH brands, platform, mobile, and high-entropy values coherent.

## Top 10 Highest Impact Fixes

- `navigator.userAgentData` (Critical, Cross-property inconsistency): Keep UA-CH brands, platform, mobile, and high-entropy values coherent.
- `navigator.userAgentData.brands[1].version` (Critical, Cross-property inconsistency): Keep UA-CH brands, platform, mobile, and high-entropy values coherent.
- `navigator.userAgentData.brands[2].version` (Critical, Cross-property inconsistency): Keep UA-CH brands, platform, mobile, and high-entropy values coherent.
- `navigator.userAgentData.high_entropy.brands[1].version` (Critical, Cross-property inconsistency): Keep UA-CH brands, platform, mobile, and high-entropy values coherent.
- `navigator.userAgentData.high_entropy.brands[2].version` (Critical, Cross-property inconsistency): Keep UA-CH brands, platform, mobile, and high-entropy values coherent.
- `navigator.userAgentData.high_entropy.fullVersionList[1].version` (Critical, Cross-property inconsistency): Keep UA-CH brands, platform, mobile, and high-entropy values coherent.
- `navigator.userAgentData.high_entropy.fullVersionList[2].version` (Critical, Cross-property inconsistency): Keep UA-CH brands, platform, mobile, and high-entropy values coherent.
- `navigator.userAgentData.high_entropy.platformVersion` (Critical, Cross-property inconsistency): Keep UA-CH brands, platform, mobile, and high-entropy values coherent.
- `navigator.userAgentData.high_entropy.uaFullVersion` (Critical, Cross-property inconsistency): Keep UA-CH brands, platform, mobile, and high-entropy values coherent.
- `navigator.languages` (Medium, Cross-property inconsistency): Derive this value from the same locale, OS, and browser profile.
