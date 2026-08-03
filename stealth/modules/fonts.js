/*
 * Profile-aware Font Loading API compatibility layer.
 *
 * Chromium already exposes a high fidelity FontFace/FontFaceSet
 * implementation.  This module deliberately leaves that implementation
 * alone unless a profile supplies values which need to be represented.  In
 * that case methods and accessors are wrapped on their native prototypes;
 * synthetic faces still inherit from the browser's FontFace.prototype.
 * No font is installed or removed from the operating system.
 */
(function fontsStealthModule() {
  "use strict";

  if (typeof document === "undefined" || typeof Document === "undefined") return;
  const fontSet = document.fonts;
  if (!fontSet || typeof fontSet !== "object") return;

  const fontSetPrototype = Object.getPrototypeOf(fontSet);
  const fontFacePrototype = typeof FontFace !== "undefined" && FontFace.prototype;
  if (!fontSetPrototype || !fontFacePrototype) return;

  const marker = Symbol.for("cemeru.stealth.fonts.v1");
  if (fontSetPrototype[marker] || fontFacePrototype[marker]) return;

  const stealth = globalThis.__stealth && typeof globalThis.__stealth === "object"
    ? globalThis.__stealth : null;
  const profile = stealth && stealth.fontProfile &&
    typeof stealth.fontProfile === "object" ? stealth.fontProfile : {};

  const own = (object, property) =>
    Object.prototype.hasOwnProperty.call(object, property);

  function descriptor(object, property) {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Object.getOwnPropertyDescriptor(owner, property);
      if (value) return { owner, value };
    }
    return null;
  }

  function objectValue(value) {
    return value && typeof value === "object" ? value : null;
  }

  function listValue(...names) {
    for (const name of names) {
      if (!own(profile, name)) continue;
      const value = profile[name];
      if (Array.isArray(value)) return value.filter((item) => typeof item === "string");
    }
    return [];
  }

  const detectedFamilies = listValue("detected", "families", "available", "installed");
  const detectedSet = new Set(detectedFamilies.map((family) => family.toLocaleLowerCase()));
  const profileChecks = objectValue(profile.check) || objectValue(profile.checks) || {};
  const faceEntries = Array.isArray(profile.faces)
    ? profile.faces.filter((entry) => entry && typeof entry === "object")
    : [];
  const hasProfile = Object.keys(profile).length > 0;
  const hasSetProfile = detectedFamilies.length > 0 || Object.keys(profileChecks).length > 0 ||
    faceEntries.length > 0 || own(profile, "status") || own(profile, "size") || own(profile, "ready");

  /* Share the native-source wrapper installed by the other completed modules. */
  const toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
  const isState = (state) => state && state.sources &&
    typeof state.sources.set === "function" && typeof state.original === "function" &&
    typeof state.replacement === "function";
  const shared = hasSetProfile && isState(stealth && stealth.navigatorFunctionState)
    ? stealth.navigatorFunctionState
    : (hasSetProfile && isState(stealth && stealth.windowFunctionState)
      ? stealth.windowFunctionState
      : (hasSetProfile && isState(stealth && stealth.screenFunctionState)
        ? stealth.screenFunctionState
        : (hasSetProfile && isState(stealth && stealth.chromeFunctionState)
          ? stealth.chromeFunctionState
          : (hasSetProfile && isState(stealth && stealth.permissionsFunctionState)
            ? stealth.permissionsFunctionState
            : null))));
  const functionState = hasSetProfile && (shared || (() => {
    const original = toStringDescriptor && toStringDescriptor.value;
    if (typeof original !== "function") return null;
    const sources = new WeakMap();
    const replacement = new Proxy(original, {
      apply(target, thisArg, args) {
        if (sources.has(thisArg)) return sources.get(thisArg);
        return Reflect.apply(target, thisArg, args);
      },
    });
    const state = { original, sources, replacement };
    if (stealth) {
      try {
        Object.defineProperty(stealth, "fontsFunctionState", {
          value: state, writable: false, enumerable: false, configurable: false,
        });
      } catch (_error) { /* hardened realms may refuse optional state storage */ }
    }
    return state;
  })());

  if (functionState && toStringDescriptor && toStringDescriptor.configurable &&
      toStringDescriptor.value !== functionState.replacement) {
    try {
      Object.defineProperty(Function.prototype, "toString", {
        value: functionState.replacement,
        writable: toStringDescriptor.writable,
        enumerable: toStringDescriptor.enumerable,
        configurable: toStringDescriptor.configurable,
      });
    } catch (_error) { /* optional native-source masking */ }
  }
  if (functionState && !functionState.sources.has(functionState.replacement)) {
    functionState.sources.set(functionState.replacement, "function toString() { [native code] }");
  }

  function nativeSource(value, fallback) {
    if (functionState && typeof value === "function") {
      try { return Reflect.apply(functionState.original, value, []); }
      catch (_error) { /* fall through */ }
    }
    return fallback;
  }

  function callable(nativeFunction, implementation, name, fallbackSource) {
    if (!functionState) return nativeFunction;
    if (typeof nativeFunction !== "function") return nativeFunction;
    const result = new Proxy(nativeFunction, {
      apply(_target, thisArg, args) {
        return Reflect.apply(implementation, thisArg, args);
      },
    });
    functionState.sources.set(
      result,
      nativeSource(nativeFunction, fallbackSource || `function ${name}() { [native code] }`),
    );
    return result;
  }

  function validFontStatus(value) {
    return value === "loaded" || value === "loading" || value === "unloaded";
  }

  function validFaceValue(value, fallback) {
    return typeof value === "string" ? value : fallback;
  }

  const faceRecords = new WeakMap();

  function makeFace(entry) {
    const face = Object.create(fontFacePrototype);
    const record = {
      family: validFaceValue(entry.family, "sans-serif"),
      style: validFaceValue(entry.style, "normal"),
      weight: validFaceValue(entry.weight, "normal"),
      stretch: validFaceValue(entry.stretch, "normal"),
      unicodeRange: validFaceValue(entry.unicodeRange, "U+0-10FFFF"),
      variant: validFaceValue(entry.variant, "normal"),
      featureSettings: validFaceValue(entry.featureSettings, "normal"),
      display: validFaceValue(entry.display, "auto"),
      status: validFontStatus(entry.status) ? entry.status : "loaded",
      loadedPromise: null,
    };
    faceRecords.set(face, record);
    return face;
  }

  const virtualFaces = faceEntries.map(makeFace);

  function isFontSetReceiver(value) {
    return value === fontSet;
  }

  function isKnownFamily(value) {
    const text = String(value || "").toLocaleLowerCase();
    for (const family of detectedSet) {
      if (text.includes(family)) return true;
    }
    return false;
  }

  function explicitCheck(value) {
    const text = String(value || "");
    if (own(profileChecks, text)) return Boolean(profileChecks[text]);
    const normalized = text.toLocaleLowerCase();
    for (const key of Object.keys(profileChecks)) {
      if (key.toLocaleLowerCase() === normalized) return Boolean(profileChecks[key]);
    }
    return undefined;
  }

  function virtualEntries() {
    return virtualFaces.length > 0 ? virtualFaces : null;
  }

  function virtualIterator(kind) {
    const values = virtualEntries() || [];
    let index = 0;
    return {
      next() {
        if (index >= values.length) return { value: undefined, done: true };
        const face = values[index++];
        if (kind === "entries") return { value: [face, face], done: false };
        return { value: face, done: false };
      },
      [Symbol.iterator]() { return this; },
    };
  }

  function setProperty(property, implementation) {
    const found = descriptor(fontSetPrototype, property);
    if (!found || !found.value || found.value.configurable === false) return;
    if (typeof found.value.get !== "function") return;
    const getter = callable(
      found.value.get,
      implementation,
      found.value.get.name || `get ${String(property)}`,
      `function get ${String(property)}() { [native code] }`,
    );
    if (typeof getter !== "function") return;
    Reflect.defineProperty(found.owner, property, {
      get: getter,
      set: found.value.set,
      enumerable: found.value.enumerable,
      configurable: found.value.configurable,
    });
  }

  function setMethod(property, implementation) {
    const found = descriptor(fontSetPrototype, property);
    if (!found || !found.value || found.value.configurable === false ||
        typeof found.value.value !== "function") return;
    const method = callable(
      found.value.value,
      implementation,
      found.value.value.name || String(property),
      `function ${String(property)}() { [native code] }`,
    );
    if (typeof method !== "function") return;
    Reflect.defineProperty(found.owner, property, {
      value: method,
      writable: found.value.writable,
      enumerable: found.value.enumerable,
      configurable: found.value.configurable,
    });
  }

  function faceProperty(property, implementation) {
    const found = descriptor(fontFacePrototype, property);
    if (!found || !found.value || found.value.configurable === false ||
        typeof found.value.get !== "function") return;
    const getter = callable(
      found.value.get,
      implementation,
      found.value.get.name || `get ${property}`,
      `function get ${property}() { [native code] }`,
    );
    let setter = found.value.set;
    if (typeof found.value.set === "function") {
      setter = callable(found.value.set, function setFace(value) {
        const record = faceRecords.get(this);
        if (record) {
          record[property] = String(value);
          return undefined;
        }
        return Reflect.apply(found.value.set, this, [value]);
      }, found.value.set.name || `set ${property}`, `function set ${property}() { [native code] }`);
    }
    Reflect.defineProperty(found.owner, property, {
      get: getter,
      set: setter,
      enumerable: found.value.enumerable,
      configurable: found.value.configurable,
    });
  }

  if (hasSetProfile) {
    const status = validFontStatus(profile.status) ? profile.status : null;
    if (status) setProperty("status", function getStatus() {
      if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
      return status;
    });

    if (own(profile, "ready")) setProperty("ready", function getReady() {
      if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
      return Promise.resolve(this);
    });

    if (typeof profile.size === "number" && Number.isFinite(profile.size)) {
      const size = Math.max(0, Math.floor(profile.size));
      setProperty("size", function getSize() {
        if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
        return size;
      });
    } else if (virtualFaces.length > 0) {
      setProperty("size", function getVirtualSize() {
        if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
        return virtualFaces.length;
      });
    }

    if (detectedFamilies.length > 0 || Object.keys(profileChecks).length > 0) {
      const nativeCheck = descriptor(fontSetPrototype, "check");
      setMethod("check", function check(font, text) {
        if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
        const explicit = explicitCheck(font);
        if (explicit !== undefined) return explicit;
        if (isKnownFamily(font)) return true;
        if (detectedFamilies.length > 0 && typeof font === "string") {
          const hasFontSize = /(?:^|\s)(?:\d+(?:\.\d+)?)(?:px|pt|pc|in|cm|mm|em|rem|ex|ch|vh|vw)(?:\s|$)/i.test(font);
          if (hasFontSize) return false;
        }
        if (nativeCheck && typeof nativeCheck.value.value === "function") {
          return Reflect.apply(nativeCheck.value.value, this, [font, text]);
        }
        return false;
      });
    }

    if (virtualFaces.length > 0) {
      setMethod("load", function load(font, text) {
        if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
        const requested = String(font || "").toLocaleLowerCase();
        const matches = virtualFaces.filter((face) => {
          const record = faceRecords.get(face);
          return !requested || requested.includes(record.family.toLocaleLowerCase());
        });
        return Promise.resolve(matches);
      });
      setMethod("values", function values() {
        if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
        return virtualIterator("values");
      });
      setMethod("keys", function keys() {
        if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
        return virtualIterator("values");
      });
      setMethod("entries", function entries() {
        if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
        return virtualIterator("entries");
      });
      setMethod("forEach", function forEach(callback, thisArg) {
        if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
        if (typeof callback !== "function") throw new TypeError("callback must be a function");
        virtualFaces.forEach((face) => callback.call(thisArg, face, face, this));
      });
      setMethod("add", function add(face) {
        if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
        if (!(face instanceof FontFace)) throw new TypeError("The value is not a FontFace");
        if (!virtualFaces.includes(face)) virtualFaces.push(face);
        return this;
      });
      setMethod("clear", function clear() {
        if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
        virtualFaces.length = 0;
      });
      const iterator = descriptor(fontSetPrototype, Symbol.iterator);
      if (iterator && iterator.value && iterator.value.configurable !== false) {
        const method = callable(
          iterator.value.value,
          function iteratorMethod() {
            if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
            return virtualIterator("values");
          },
          iterator.value.value.name || "values",
          "function values() { [native code] }",
        );
        Reflect.defineProperty(iterator.owner, Symbol.iterator, {
          value: method,
          writable: iterator.value.writable,
          enumerable: iterator.value.enumerable,
          configurable: iterator.value.configurable,
        });
      }
    }

    if (virtualFaces.length > 0) {
      const nativeHas = descriptor(fontSetPrototype, "has");
      const nativeDelete = descriptor(fontSetPrototype, "delete");
      setMethod("has", function has(face) {
        if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
        return virtualFaces.includes(face) || (nativeHas && Reflect.apply(nativeHas.value.value, this, [face]));
      });
      setMethod("delete", function deleteFace(face) {
        if (!isFontSetReceiver(this)) throw new TypeError("Illegal invocation");
        const index = virtualFaces.indexOf(face);
        if (index >= 0) { virtualFaces.splice(index, 1); return true; }
        return nativeDelete ? Reflect.apply(nativeDelete.value.value, this, [face]) : false;
      });
    }

    if (faceEntries.length > 0) {
      const properties = [
        "family", "style", "weight", "stretch", "unicodeRange", "variant",
        "featureSettings", "display",
      ];
      const nativeFaceDescriptors = Object.fromEntries(
        [...properties, "status", "loaded"].map((property) => [property, descriptor(fontFacePrototype, property)]),
      );
      for (const property of properties) {
        faceProperty(property, function getFaceProperty() {
          const record = faceRecords.get(this);
          if (record) return record[property];
          const native = nativeFaceDescriptors[property];
          return native && native.value.get ? Reflect.apply(native.value.get, this, []) : undefined;
        });
      }
      faceProperty("status", function getFaceStatus() {
        const record = faceRecords.get(this);
        if (record) return record.status;
        const native = nativeFaceDescriptors.status;
        return native && native.value.get ? Reflect.apply(native.value.get, this, []) : "unloaded";
      });
      faceProperty("loaded", function getFaceLoaded() {
        const record = faceRecords.get(this);
        if (record) {
          if (!record.loadedPromise) record.loadedPromise = Promise.resolve(this);
          return record.loadedPromise;
        }
        const native = nativeFaceDescriptors.loaded;
        return native && native.value.get ? Reflect.apply(native.value.get, this, []) : Promise.resolve(this);
      });
      const loadDescriptor = descriptor(fontFacePrototype, "load");
      if (loadDescriptor && loadDescriptor.value && loadDescriptor.value.configurable !== false &&
          typeof loadDescriptor.value.value === "function") {
        const method = callable(
          loadDescriptor.value.value,
          function loadFace() {
            const record = faceRecords.get(this);
            if (record) { record.status = "loaded"; record.loadedPromise = Promise.resolve(this); return record.loadedPromise; }
            return Reflect.apply(loadDescriptor.value.value, this, []);
          },
          loadDescriptor.value.value.name || "load",
          "function load() { [native code] }",
        );
        Reflect.defineProperty(loadDescriptor.owner, "load", {
          value: method,
          writable: loadDescriptor.value.writable,
          enumerable: loadDescriptor.value.enumerable,
          configurable: loadDescriptor.value.configurable,
        });
      }
    }
  }

  try {
    Object.defineProperty(fontSetPrototype, marker, {
      value: Object.freeze({ version: "1.0.0", profile: hasProfile }),
      writable: false,
      enumerable: false,
      configurable: false,
    });
    Object.defineProperty(fontFacePrototype, marker, {
      value: true,
      writable: false,
      enumerable: false,
      configurable: false,
    });
  } catch (_error) { /* hardened realms may refuse optional markers */ }
}());
