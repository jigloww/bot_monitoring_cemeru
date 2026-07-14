// stealth/runtime/utils.js — Utility functions for value rendering and type checking.
(() => {
  'use strict';
  const s = window.__stealth = window.__stealth || {};

  // Check if value is a plain object
  s.isPlainObject = v => v !== null && typeof v === 'object' && !Array.isArray(v);

  // Clamp a number between min and max
  s.clamp = (v, min, max) => Math.min(Math.max(v, min), max);

  // Return a frozen copy of an array (for array properties)
  s.frozenArray = arr => Object.freeze([...arr]);

  // Wrap a getter with error suppression
  s.safeGet = (fn, fallback = null) => {
    try { return fn(); } catch(e) { return fallback; }
  };
})();
