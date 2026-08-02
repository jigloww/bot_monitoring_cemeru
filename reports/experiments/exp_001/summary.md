# Fingerprint Experiment exp_001

- **Status:** completed
- **Date:** 2026-08-02T22:50:43.445540+07:00
- **Label:** navigator-module-smoke
- **URL:** `about:blank`
- **Baseline:** `reports\fingerprint\fingerprint_real.json`
- **Patch version:** `ac1912381f5f`

## Score Summary

| Metric | Before | After | Delta |
|---|---:|---:|---:|
| Overall Score | 43.50% | 43.40% | -0.10 pp |
| CF Risk | 44.00% | 43.80% | -0.20 pp |
| Total Diffs | 257 | 258 | -1 |

## Metrics

| Metric | Value |
|---|---:|
| Patch targets | 0 |
| Patches successful | 0 |
| Patches failed | 0 |
| Patches with no effect | 0 |
| Diff reduction | -1 |
| Diff reduction percentage | -0.39% |
| Overall improvement | -0.10 percentage points |
| Relative overall improvement | -0.23% |

## Top Categories

| Category | Before | After | Delta |
|---|---:|---:|---:|
| Navigator | 33.90% | 32.10% | -1.80 pp |
| Window | 11.10% | 11.10% | 0.00 pp |
| Chrome | 0.00% | 0.00% | 0.00 pp |
| Permissions | 85.70% | 85.70% | 0.00 pp |
| Fonts | 100.00% | 100.00% | 0.00 pp |
| Speech | 0.00% | 0.00% | 0.00 pp |
| Battery | 0.00% | 0.00% | 0.00 pp |
| Performance | 10.00% | 10.00% | 0.00 pp |
| WebGL | 62.50% | 62.50% | 0.00 pp |
| Screen | 50.00% | 50.00% | 0.00 pp |

## Improved Keys

Count: **0**

- None

## Regressed Keys

Count: **1**

- `navigator.connection.downlink`

## Unchanged Keys

Count: **358**

- `audio.sample_sum`
- `audio.samples`
- `battery`
- `battery.charging`
- `battery.chargingTime`
- `battery.dischargingTime`
- `battery.level`
- `canvas.hash`
- `canvas.length`
- `canvas.prefix`
- `canvas.supported`
- `chrome.app.present`
- `chrome.csi.present`
- `chrome.csi.value.onloadT`
- `chrome.csi.value.pageT`
- `chrome.csi.value.startE`
- `chrome.keys`
- `chrome.loadTimes.present`
- `chrome.loadTimes.value.requestTime`
- `chrome.loadTimes.value.startLoadTime`
- `chrome.present`
- `chrome.runtime.has_connect`
- `chrome.runtime.has_send`
- `chrome.runtime.id`
- `chrome.runtime.present`
- `chrome.webstore.present`
- `css.forced_colors`
- `css.hover_hover`
- `css.pointer_events`
- `css.prefers_dark`
- `css.reduced_motion`
- `css.supports.aspect-ratio`
- `css.supports.backdrop-filter`
- `css.supports.container`
- `css.supports.flex`
- `css.supports.grid`
- `css.supports.has-selector`
- `css.supports.variables`
- `css.touch_support`
- `document`
- `document.characterSet`
- `document.compatMode`
- `document.cookie_count`
- `document.cookie_names`
- `document.domain`
- `document.readyState`
- `document.referrer`
- `document.title`
- `document.visibilityState`
- `features.AbortController`
- ... and 308 more (available in `summary.json`)

## Top 20 Remaining Differences

| Priority | Category | Key | Reference | After |
|---:|---|---|---|---|
| 5 | Chrome | `chrome.csi.present` | `true` | `"<missing>"` |
| 5 | Chrome | `chrome.loadTimes.present` | `true` | `"<missing>"` |
| 5 | Chrome | `chrome.present` | `true` | `false` |
| 5 | Chrome | `chrome.runtime.present` | `false` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData` | `"<missing>"` | `null` |
| 5 | Navigator | `navigator.userAgentData.brands[0].brand` | `"Not;A=Brand"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.brands[0].version` | `"8"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.brands[1].brand` | `"Chromium"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.brands[1].version` | `"150"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.brands[2].brand` | `"Google Chrome"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.brands[2].version` | `"150"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.high_entropy.architecture` | `"x86"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.high_entropy.bitness` | `"64"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.high_entropy.brands[0].brand` | `"Not;A=Brand"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.high_entropy.brands[0].version` | `"8"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.high_entropy.brands[1].brand` | `"Chromium"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.high_entropy.brands[1].version` | `"150"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.high_entropy.brands[2].brand` | `"Google Chrome"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.high_entropy.brands[2].version` | `"150"` | `"<missing>"` |
| 5 | Navigator | `navigator.userAgentData.high_entropy.fullVersionList[0].brand` | `"Not;A=Brand"` | `"<missing>"` |
