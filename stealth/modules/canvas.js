/*
 * Profile-aware Canvas fingerprint compatibility layer.
 *
 * The drawing pipeline and constructors remain native.  Only read/encode
 * surfaces commonly used for fingerprinting are wrapped, and only when an
 * explicit __stealth.canvasProfile is present.  Every variation is derived
 * from the profile seed; no Math.random(), timers, or machine-specific value
 * is used.
 */
(function canvasStealthModule() {
  "use strict";

  const root = typeof globalThis !== "undefined" ? globalThis : window;
  const stealth = root && root.__stealth && typeof root.__stealth === "object"
    ? root.__stealth : null;
  const profile = stealth && stealth.canvasProfile &&
    typeof stealth.canvasProfile === "object" ? stealth.canvasProfile : null;

  // Native fallback is intentional.  A context without a profile must remain
  // byte-for-byte native and should not expose a synthetic canvas signature.
  if (!profile || Object.keys(profile).length === 0) return;

  const HTMLCanvas = typeof root.HTMLCanvasElement !== "undefined"
    ? root.HTMLCanvasElement : null;
  const Offscreen = typeof root.OffscreenCanvas !== "undefined"
    ? root.OffscreenCanvas : null;
  const Context2D = typeof root.CanvasRenderingContext2D !== "undefined"
    ? root.CanvasRenderingContext2D : null;
  if (!HTMLCanvas && !Offscreen && !Context2D) return;

  const moduleMarker = Symbol.for("cemeru.stealth.canvas.v1");
  const methodMarker = Symbol.for("cemeru.stealth.canvas.methods.v1");
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

  function descriptor(object, property) {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Object.getOwnPropertyDescriptor(owner, property);
      if (value) return { owner, value };
    }
    return null;
  }

  // Reuse the source masker installed by the completed modules.  The local
  // fallback keeps canvas standalone when it is loaded by itself.
  const toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
  const isState = (state) => state && state.sources &&
    typeof state.sources.set === "function" && typeof state.original === "function" &&
    typeof state.replacement === "function";
  const shared = [
    "navigatorFunctionState", "windowFunctionState", "screenFunctionState",
    "chromeFunctionState", "permissionsFunctionState", "fontsFunctionState",
    "speechFunctionState", "performanceFunctionState", "webglFunctionState",
  ].map((name) => stealth && stealth[name]).find(isState);
  const functionState = shared || (() => {
    if (!toStringDescriptor || typeof toStringDescriptor.value !== "function") return null;
    const original = toStringDescriptor.value;
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
        Object.defineProperty(stealth, "canvasFunctionState", {
          value: state, writable: false, enumerable: false, configurable: false,
        });
      } catch (_error) { /* hardened realm */ }
    }
    return state;
  })();

  if (functionState && toStringDescriptor && toStringDescriptor.configurable &&
      toStringDescriptor.value !== functionState.replacement) {
    try {
      Object.defineProperty(Function.prototype, "toString", {
        value: functionState.replacement,
        writable: toStringDescriptor.writable,
        enumerable: toStringDescriptor.enumerable,
        configurable: toStringDescriptor.configurable,
      });
    } catch (_error) { /* optional native masking */ }
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

  function callable(nativeFunction, implementation, name) {
    if (typeof nativeFunction !== "function") return null;
    if (!functionState) return new Proxy(nativeFunction, {
      apply(_target, receiver, args) { return Reflect.apply(implementation, receiver, args); },
    });
    const wrapped = new Proxy(nativeFunction, {
      apply(_target, receiver, args) {
        return Reflect.apply(implementation, receiver, args);
      },
    });
    functionState.sources.set(wrapped, nativeSource(nativeFunction,
      `function ${name}() { [native code] }`));
    return wrapped;
  }

  function finite(value) { return typeof value === "number" && Number.isFinite(value); }
  function hashSeed(value) {
    const text = String(value === undefined ? "canvas" : value);
    let hash = 2166136261 >>> 0;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619) >>> 0;
    }
    return hash >>> 0;
  }

  const seed = hashSeed(own(profile, "noise_seed") ? profile.noise_seed :
    (own(profile, "hash") ? profile.hash : "canvas"));
  function variationAmount() {
    const value = profile.image_variation;
    if (finite(value)) return Math.max(0, Math.min(8, Math.floor(Math.abs(value))));
    if (value && typeof value === "object" && finite(value.intensity)) {
      return Math.max(0, Math.min(8, Math.floor(Math.abs(value.intensity))));
    }
    return own(profile, "noise_seed") || own(profile, "hash") ? 1 : 0;
  }
  const intensity = variationAmount();

  function nextByte(index) {
    let value = (seed ^ Math.imul(index + 1, 2654435761)) >>> 0;
    value ^= value << 13; value >>>= 0;
    value ^= value >>> 17; value >>>= 0;
    value ^= value << 5; value >>>= 0;
    return value & 0xff;
  }

  function validCanvas(value) {
    if (HTMLCanvas) { try { if (value instanceof HTMLCanvas) return true; } catch (_error) {} }
    if (Offscreen) { try { if (value instanceof Offscreen) return true; } catch (_error) {} }
    return false;
  }
  function validContext(value) {
    if (!Context2D) return false;
    try { return value instanceof Context2D; } catch (_error) { return false; }
  }
  function formatsAllow(mime) {
    const values = profile.supported_formats || profile.supportedFormats;
    if (!Array.isArray(values) || values.length === 0 || typeof mime !== "string") return true;
    return values.indexOf(mime.toLowerCase()) >= 0;
  }

  function varyBytes(data, offset) {
    if (!intensity || !data || typeof data.length !== "number") return;
    // Keep alpha untouched.  This cannot change dimensions or ImageData size.
    for (let index = 0; index + 3 < data.length; index += 4) {
      const delta = (nextByte(index + offset) % (intensity * 2 + 1)) - intensity;
      data[index] = Math.max(0, Math.min(255, data[index] + delta));
      data[index + 1] = Math.max(0, Math.min(255, data[index + 1] + (delta % 2)));
      data[index + 2] = Math.max(0, Math.min(255, data[index + 2] - (delta % 2)));
    }
  }

  function cloneImageData(image, offset) {
    if (!image || !image.data || !intensity || typeof root.ImageData !== "function") return image;
    const data = new Uint8ClampedArray(image.data);
    varyBytes(data, offset || 0);
    try {
      const options = image.colorSpace ? { colorSpace: image.colorSpace } : undefined;
      return options ? new root.ImageData(data, image.width, image.height, options) :
        new root.ImageData(data, image.width, image.height);
    } catch (_error) {
      try { return new root.ImageData(data, image.width, image.height); }
      catch (_error2) { return image; }
    }
  }

  function nativeCanvasDocument(source) {
    if (HTMLCanvas && source instanceof HTMLCanvas) {
      return source.ownerDocument || (root.document || null);
    }
    return null;
  }

  function temporaryCanvas(source) {
    const width = Number(source.width) || 0;
    const height = Number(source.height) || 0;
    let target = null;
    const document = nativeCanvasDocument(source);
    try {
      if (document && typeof document.createElement === "function") {
        target = document.createElement("canvas");
        target.width = width; target.height = height;
      } else if (Offscreen) {
        target = new Offscreen(width, height);
      }
      if (!target || typeof target.getContext !== "function") return null;
      const context = target.getContext("2d");
      if (!context) return null;
      return { canvas: target, context };
    } catch (_error) { return null; }
  }

  // Captured before installation so helper rendering never calls a wrapped
  // method recursively.
  const nativeDrawImage = Context2D && Context2D.prototype &&
    descriptor(Context2D.prototype, "drawImage");
  const nativeGetImageData = Context2D && Context2D.prototype &&
    descriptor(Context2D.prototype, "getImageData");
  const nativePutImageData = Context2D && Context2D.prototype &&
    descriptor(Context2D.prototype, "putImageData");

  function renderCopy(source) {
    if (!nativeDrawImage || typeof nativeDrawImage.value.value !== "function") return null;
    const copy = temporaryCanvas(source);
    if (!copy) return null;
    try {
      Reflect.apply(nativeDrawImage.value.value, copy.context, [source, 0, 0]);
      if (intensity && nativeGetImageData && nativePutImageData) {
        const image = Reflect.apply(nativeGetImageData.value.value, copy.context, [0, 0, copy.canvas.width, copy.canvas.height]);
        const changed = cloneImageData(image, 31);
        if (changed !== image) Reflect.apply(nativePutImageData.value.value, copy.context, [changed, 0, 0]);
      }
      return copy.canvas;
    } catch (_error) { return null; }
  }

  function installMethod(proto, property, implementationFactory) {
    if (!proto) return;
    const found = descriptor(proto, property);
    if (!found || !found.value || typeof found.value.value !== "function" ||
        found.value.configurable === false) return;
    let state = found.owner[methodMarker];
    if (state && state[property]) return;
    const nativeFunction = found.value.value;
    const implementation = implementationFactory(nativeFunction);
    const wrapped = callable(nativeFunction, implementation, nativeFunction.name || property);
    if (typeof wrapped !== "function") return;
    try {
      Object.defineProperty(found.owner, property, {
        value: wrapped, writable: found.value.writable,
        enumerable: found.value.enumerable, configurable: found.value.configurable,
      });
      if (!state) {
        state = {};
        Object.defineProperty(found.owner, methodMarker, {
          value: state, writable: false, enumerable: false, configurable: false,
        });
      }
      state[property] = true;
    } catch (_error) { /* hardened native prototype */ }
  }

  function installCanvasPrototype(proto) {
    if (!proto || proto[moduleMarker]) return;
    try {
      Object.defineProperty(proto, moduleMarker, {
        value: true, writable: false, enumerable: false, configurable: false,
      });
    } catch (_error) { return; }

    installMethod(proto, "toDataURL", (native) => function toDataURL(type, quality) {
      if (!validCanvas(this) || !formatsAllow(type || "image/png")) return Reflect.apply(native, this, arguments);
      const copy = renderCopy(this);
      if (!copy || typeof copy.toDataURL !== "function") return Reflect.apply(native, this, arguments);
      try { return Reflect.apply(native, copy, arguments); }
      catch (_error) { return Reflect.apply(native, this, arguments); }
    });

    installMethod(proto, "toBlob", (native) => function toBlob(callback, type, quality) {
      if (typeof callback !== "function" || !validCanvas(this) || !formatsAllow(type || "image/png")) {
        return Reflect.apply(native, this, arguments);
      }
      const copy = renderCopy(this);
      if (!copy || typeof copy.toBlob !== "function") return Reflect.apply(native, this, arguments);
      try { return Reflect.apply(native, copy, arguments); }
      catch (_error) { return Reflect.apply(native, this, arguments); }
    });
  }

  function metricOverrides(text) {
    const configured = profile.text_metrics || profile.textMetrics;
    if (!configured || typeof configured !== "object") return null;
    if (configured[text] && typeof configured[text] === "object") return configured[text];
    return configured;
  }

  function installContextPrototype(proto) {
    if (!proto || proto[moduleMarker]) return;
    try {
      Object.defineProperty(proto, moduleMarker, {
        value: true, writable: false, enumerable: false, configurable: false,
      });
    } catch (_error) { return; }
    installMethod(proto, "getImageData", (native) => function getImageData() {
      const image = Reflect.apply(native, this, arguments);
      if (!validContext(this)) return image;
      return cloneImageData(image, Number(arguments[0]) || 0);
    });
    installMethod(proto, "measureText", (native) => function measureText(text) {
      const metrics = Reflect.apply(native, this, arguments);
      const overrides = metricOverrides(String(text));
      if (!overrides || !metrics || typeof metrics !== "object") return metrics;
      return new Proxy(metrics, {
        get(target, property, receiver) {
          if (own(overrides, property) && (typeof overrides[property] === "number" || typeof overrides[property] === "string")) return overrides[property];
          return Reflect.get(target, property, receiver);
        },
      });
    });
    installMethod(proto, "isPointInPath", (native) => function isPointInPath() {
      const value = profile.isPointInPath;
      if (typeof value === "boolean" && validContext(this)) return value;
      return Reflect.apply(native, this, arguments);
    });
    installMethod(proto, "isPointInStroke", (native) => function isPointInStroke() {
      const value = profile.isPointInStroke;
      if (typeof value === "boolean" && validContext(this)) return value;
      return Reflect.apply(native, this, arguments);
    });
  }

  if (HTMLCanvas && HTMLCanvas.prototype) installCanvasPrototype(HTMLCanvas.prototype);
  if (Offscreen && Offscreen.prototype) installCanvasPrototype(Offscreen.prototype);
  if (Context2D && Context2D.prototype) installContextPrototype(Context2D.prototype);
})();
