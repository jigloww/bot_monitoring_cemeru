// stealth/runtime/helpers.js — Shared helper utilities for stealth modules.
// Loaded first so all modules can use these helpers.
(() => {
  'use strict';

  // Safe defineProperty — won't throw if property is non-configurable
  window.__stealth = window.__stealth || {};
  window.__stealth.define = (obj, prop, val) => {
    try {
      Object.defineProperty(obj, prop, { get: () => val, configurable: true, enumerable: true });
    } catch(e) {
      // Property is non-configurable in this context — skip silently
    }
  };

  // Safe function replacement — preserves Function.prototype.toString
  window.__stealth.mockFn = (name, fn) => {
    try {
      Object.defineProperty(fn, 'name', { value: name, configurable: true });
      fn.toString = () => `function ${name}() { [native code] }`;
    } catch(e) {}
    return fn;
  };

  // Deep freeze guard — check if property can be modified
  window.__stealth.canDefine = (obj, prop) => {
    try {
      const desc = Object.getOwnPropertyDescriptor(obj, prop);
      return !desc || desc.configurable === true;
    } catch(e) { return false; }
  };

  // Log helper (no-op in production, enable with __stealth_debug = true)
  window.__stealth.log = (...args) => {
    if (window.__stealth_debug) console.log('[stealth]', ...args);
  };
})();
