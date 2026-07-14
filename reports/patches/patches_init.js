// Auto-generated browser fingerprint init script
// Source: patch_generator.py
// Add via: page.add_init_script(script=this_file)
(() => {
  'use strict';

  // ── Navigator: Override navigator.webdriver to return false.
  try {
    Object.defineProperty(navigator,'webdriver',{get:()=>false,configurable:true});
  } catch(e) { console.warn('patch failed: navigator.webdriver', e); }

  // ── Navigator: Set navigator.deviceMemory to 8.
  try {
    Object.defineProperty(navigator,'deviceMemory',{get:()=>8,configurable:true});
  } catch(e) { console.warn('patch failed: navigator.deviceMemory', e); }

  // ── Window: Set window.outerHeight to 798 (0 in headless).
  try {
    Object.defineProperty(window,'outerHeight',{get:()=>798,configurable:true});
  } catch(e) { console.warn('patch failed: window.outerHeight', e); }

  // ── Window: Set window.outerWidth to 1051 (0 in headless).
  try {
    Object.defineProperty(window,'outerWidth',{get:()=>1051,configurable:true});
  } catch(e) { console.warn('patch failed: window.outerWidth', e); }

  // ── Navigator: Override navigator.languages to match real browser: ["en-US", "en", "id"].
  try {
    Object.defineProperty(navigator,'languages',{get:()=>["en-US", "en", "id"],configurable:true});
  } catch(e) { console.warn('patch failed: navigator.languages', e); }

})();