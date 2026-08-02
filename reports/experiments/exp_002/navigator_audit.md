# Experiment 002 — Navigator Audit

Reference: `reports\fingerprint\fingerprint_real.json`  
Plain: `reports\fingerprint\fingerprint_playwright.json`  
Patched: `reports\fingerprint\fingerprint_playwright_patched.json`

## Warnings

- Patched input metadata identifies generated patches only; it does not prove that the Navigator module was applied.

## Summary

| Metric | Value |
|---|---:|
| Jumlah key Navigator | 110 |
| Navigator Success Rate | 83.64% |
| Repair Rate (initial differences) | 58.33% |
| Critical Remaining | 8 |
| Regression Count | 3 |
| Improvement Count | 21 |
| Still Different | 15 |
| Missing | 0 |
| Equal | 71 |

## Property Audit

| Property | Plain | Patched | Reference | Status | Severity | Recommendation |
|---|---|---|---|---|---|---|
| `navigator.appCodeName` | "Mozilla" | "Mozilla" | "Mozilla" | Equal | Low | No patch required; matches the reference. |
| `navigator.appName` | "Netscape" | "Netscape" | "Netscape" | Equal | Low | No patch required; matches the reference. |
| `navigator.appVersion` | "5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/150.0.0.0 … | "5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/150.0.0.0 Safari/537… | "5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/5… | Still Different | Low | Review this Navigator value against the selected browser profile. |
| `navigator.connection` | {"effectiveType":"4g","downlink":1.65,"rtt":50,"saveData":false,"type":null} | {"effectiveType":"4g","downlink":1.5,"rtt":0,"saveData":false,"type":null} | {"effectiveType":"4g","downlink":10,"rtt":50,"saveData":false,"type":null} | Still Different | Low | Review this Navigator value against the selected browser profile. |
| `navigator.connection.downlink` | 1.65 | 1.5 | 10 | Still Different | Low | Review this Navigator value against the selected browser profile. |
| `navigator.connection.effectiveType` | "4g" | "4g" | "4g" | Equal | Low | No patch required; matches the reference. |
| `navigator.connection.rtt` | 50 | 0 | 50 | Regression | Low | Review this Navigator value against the selected browser profile. |
| `navigator.connection.saveData` | false | false | false | Equal | Low | No patch required; matches the reference. |
| `navigator.connection.type` | null | null | null | Equal | Low | No patch required; matches the reference. |
| `navigator.cookieEnabled` | true | true | true | Equal | Low | No patch required; matches the reference. |
| `navigator.deviceMemory` | null | 2 | 8 | Still Different | High | Use a realistic Chromium memory bucket. |
| `navigator.doNotTrack` | null | null | null | Equal | Low | No patch required; matches the reference. |
| `navigator.hardwareConcurrency` | 12 | 2 | 12 | Regression | High | Use a realistic logical-core value for the profile. |
| `navigator.javaEnabled` | false | false | false | Equal | Low | No patch required; matches the reference. |
| `navigator.keys` | [] | [] | [] | Equal | Low | No patch required; matches the reference. |
| `navigator.language` | "en-US" | "en-US" | "en-US" | Equal | Low | No patch required; matches the reference. |
| `navigator.languages` | ["en-US","en"] | ["en-US","en"] | ["en-US","en","id"] | Still Different | Medium | Align the frozen language list with the browser locale profile. |
| `navigator.maxTouchPoints` | 0 | 0 | 0 | Equal | Low | No patch required; matches the reference. |
| `navigator.onLine` | true | true | true | Equal | Low | No patch required; matches the reference. |
| `navigator.oscpu` | null | null | null | Equal | Low | No patch required; matches the reference. |
| `navigator.pdfViewerEnabled` | true | true | true | Equal | Low | No patch required; matches the reference. |
| `navigator.platform` | "Win32" | "Linux x86_64" | "Win32" | Regression | High | Keep consistent with the UA and UA-CH platform. |
| `navigator.product` | "Gecko" | "Gecko" | "Gecko" | Equal | Low | No patch required; matches the reference. |
| `navigator.productSub` | "20030107" | "20030107" | "20030107" | Equal | Low | No patch required; matches the reference. |
| `navigator.prototype_keys` | ["vendorSub","productSub","vendor","maxTouchPoints","scheduling","userActivation","geolocation","do… | ["vendorSub","productSub","vendor","maxTouchPoints","scheduling","userActivation","geolocation","do… | ["vendorSub","productSub","vendor","maxTouchPoints","scheduling","userActivation","geolocation","do… | Still Different | Low | Review this Navigator value against the selected browser profile. |
| `navigator.userAgent` | "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/15… | "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/150.0.0.0 Sa… | "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 … | Still Different | Low | Review this Navigator value against the selected browser profile. |
| `navigator.userAgentData` | null | {"brands":[{"brand":"Not;A=Brand","version":"8"},{"brand":"Chromium","version":"150"},{"brand":"Goo… | {"brands":[{"brand":"Not;A=Brand","version":"8"},{"brand":"Chromium","version":"150"},{"brand":"Goo… | Still Different | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.brands[0].brand` | "<missing>" | "Not;A=Brand" | "Not;A=Brand" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.brands[0].version` | "<missing>" | "8" | "8" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.brands[1].brand` | "<missing>" | "Chromium" | "Chromium" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.brands[1].version` | "<missing>" | "150" | "150" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.brands[2].brand` | "<missing>" | "Google Chrome" | "Google Chrome" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.brands[2].version` | "<missing>" | "150" | "150" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.architecture` | "<missing>" | "x86" | "x86" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.bitness` | "<missing>" | "64" | "64" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.brands[0].brand` | "<missing>" | "Not;A=Brand" | "Not;A=Brand" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.brands[0].version` | "<missing>" | "8" | "8" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.brands[1].brand` | "<missing>" | "Chromium" | "Chromium" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.brands[1].version` | "<missing>" | "150" | "150" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.brands[2].brand` | "<missing>" | "Google Chrome" | "Google Chrome" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.brands[2].version` | "<missing>" | "150" | "150" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.fullVersionList[0].brand` | "<missing>" | "Not;A=Brand" | "Not;A=Brand" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.fullVersionList[0].version` | "<missing>" | "8.0.0.0" | "8.0.0.0" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.fullVersionList[1].brand` | "<missing>" | "Chromium" | "Chromium" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.fullVersionList[1].version` | "<missing>" | "150.0.7871.114" | "150.0.7871.115" | Still Different | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.fullVersionList[2].brand` | "<missing>" | "Google Chrome" | "Google Chrome" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.fullVersionList[2].version` | "<missing>" | "150.0.7871.114" | "150.0.7871.115" | Still Different | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.mobile` | "<missing>" | false | false | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.model` | "<missing>" | "" | "" | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.platform` | "<missing>" | "Linux" | "Windows" | Still Different | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.platformVersion` | "<missing>" | "" | "19.0.0" | Still Different | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.high_entropy.uaFullVersion` | "<missing>" | "150.0.7871.114" | "150.0.7871.115" | Still Different | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.mobile` | "<missing>" | false | false | Improved | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.userAgentData.platform` | "<missing>" | "Linux" | "Windows" | Still Different | Critical | Keep brands, platform, mobile, and high-entropy hints coherent. |
| `navigator.vendor` | "Google Inc." | "Google Inc." | "Google Inc." | Equal | Low | No patch required; matches the reference. |
| `navigator.vendorSub` | "" | "" | "" | Equal | Low | No patch required; matches the reference. |
| `navigator.webdriver` | true | true | false | Still Different | Critical | Keep false and expose it as a Navigator.prototype getter. |
| `plugins.mime_count` | 2 | 2 | 2 | Equal | Low | No patch required; matches the reference. |
| `plugins.mime_types[0].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.mime_types[0].suffixes` | "pdf" | "pdf" | "pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.mime_types[0].type` | "application/pdf" | "application/pdf" | "application/pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.mime_types[1].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.mime_types[1].suffixes` | "pdf" | "pdf" | "pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.mime_types[1].type` | "text/pdf" | "text/pdf" | "text/pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugin_count` | 5 | 5 | 5 | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[0].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[0].filename` | "internal-pdf-viewer" | "internal-pdf-viewer" | "internal-pdf-viewer" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[0].mimes[0].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[0].mimes[0].suffixes` | "pdf" | "pdf" | "pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[0].mimes[0].type` | "application/pdf" | "application/pdf" | "application/pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[0].mimes[1].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[0].mimes[1].suffixes` | "pdf" | "pdf" | "pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[0].mimes[1].type` | "text/pdf" | "text/pdf" | "text/pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[0].name` | "PDF Viewer" | "PDF Viewer" | "PDF Viewer" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[1].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[1].filename` | "internal-pdf-viewer" | "internal-pdf-viewer" | "internal-pdf-viewer" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[1].mimes[0].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[1].mimes[0].suffixes` | "pdf" | "pdf" | "pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[1].mimes[0].type` | "application/pdf" | "application/pdf" | "application/pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[1].mimes[1].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[1].mimes[1].suffixes` | "pdf" | "pdf" | "pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[1].mimes[1].type` | "text/pdf" | "text/pdf" | "text/pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[1].name` | "Chrome PDF Viewer" | "Chrome PDF Viewer" | "Chrome PDF Viewer" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[2].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[2].filename` | "internal-pdf-viewer" | "internal-pdf-viewer" | "internal-pdf-viewer" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[2].mimes[0].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[2].mimes[0].suffixes` | "pdf" | "pdf" | "pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[2].mimes[0].type` | "application/pdf" | "application/pdf" | "application/pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[2].mimes[1].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[2].mimes[1].suffixes` | "pdf" | "pdf" | "pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[2].mimes[1].type` | "text/pdf" | "text/pdf" | "text/pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[2].name` | "Chromium PDF Viewer" | "Chromium PDF Viewer" | "Chromium PDF Viewer" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[3].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[3].filename` | "internal-pdf-viewer" | "internal-pdf-viewer" | "internal-pdf-viewer" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[3].mimes[0].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[3].mimes[0].suffixes` | "pdf" | "pdf" | "pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[3].mimes[0].type` | "application/pdf" | "application/pdf" | "application/pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[3].mimes[1].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[3].mimes[1].suffixes` | "pdf" | "pdf" | "pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[3].mimes[1].type` | "text/pdf" | "text/pdf" | "text/pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[3].name` | "Microsoft Edge PDF Viewer" | "Microsoft Edge PDF Viewer" | "Microsoft Edge PDF Viewer" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[4].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[4].filename` | "internal-pdf-viewer" | "internal-pdf-viewer" | "internal-pdf-viewer" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[4].mimes[0].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[4].mimes[0].suffixes` | "pdf" | "pdf" | "pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[4].mimes[0].type` | "application/pdf" | "application/pdf" | "application/pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[4].mimes[1].description` | "Portable Document Format" | "Portable Document Format" | "Portable Document Format" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[4].mimes[1].suffixes` | "pdf" | "pdf" | "pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[4].mimes[1].type` | "text/pdf" | "text/pdf" | "text/pdf" | Equal | Low | No patch required; matches the reference. |
| `plugins.plugins[4].name` | "WebKit built-in PDF" | "WebKit built-in PDF" | "WebKit built-in PDF" | Equal | Low | No patch required; matches the reference. |

## Top 20 Properties Still Different

- `navigator.userAgentData` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.fullVersionList[1].version` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.fullVersionList[2].version` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.platform` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.platformVersion` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.uaFullVersion` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.platform` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.webdriver` (Critical): Keep false and expose it as a Navigator.prototype getter.
- `navigator.deviceMemory` (High): Use a realistic Chromium memory bucket.
- `navigator.hardwareConcurrency` (High): Use a realistic logical-core value for the profile.
- `navigator.platform` (High): Keep consistent with the UA and UA-CH platform.
- `navigator.languages` (Medium): Align the frozen language list with the browser locale profile.
- `navigator.appVersion` (Low): Review this Navigator value against the selected browser profile.
- `navigator.connection` (Low): Review this Navigator value against the selected browser profile.
- `navigator.connection.downlink` (Low): Review this Navigator value against the selected browser profile.
- `navigator.connection.rtt` (Low): Review this Navigator value against the selected browser profile.
- `navigator.prototype_keys` (Low): Review this Navigator value against the selected browser profile.
- `navigator.userAgent` (Low): Review this Navigator value against the selected browser profile.

## Top Regression

- `navigator.hardwareConcurrency` (High): Use a realistic logical-core value for the profile.
- `navigator.platform` (High): Keep consistent with the UA and UA-CH platform.
- `navigator.connection.rtt` (Low): Review this Navigator value against the selected browser profile.

## Top Improvement

- `navigator.userAgentData.brands[0].brand` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.brands[0].version` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.brands[1].brand` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.brands[1].version` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.brands[2].brand` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.brands[2].version` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.architecture` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.bitness` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.brands[0].brand` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.brands[0].version` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.brands[1].brand` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.brands[1].version` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.brands[2].brand` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.brands[2].version` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.fullVersionList[0].brand` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.fullVersionList[0].version` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.fullVersionList[1].brand` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.fullVersionList[2].brand` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.mobile` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
- `navigator.userAgentData.high_entropy.model` (Critical): Keep brands, platform, mobile, and high-entropy hints coherent.
