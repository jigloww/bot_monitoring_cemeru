// stealth/runtime/hooks.js — Function hook utilities for runtime spoofing.
// PLACEHOLDER — implement when needed for:
//   - performance.now() jitter suppression
//   - Date.now() consistency
//   - chrome.loadTimes() / chrome.csi() spoofing
//   - canvas.toDataURL() noise injection
//   - WebGL getParameter() spoofing
//
// Hook pattern:
//
// const _realNow = performance.now.bind(performance);
// performance.now = window.__stealth.mockFn('now', () => {
//   return _realNow() + __stealth_now_offset;
// });
//
// This module provides the infrastructure; values come from patches.json.

// Future: window.__stealth.hookMethod(obj, method, replacement)
