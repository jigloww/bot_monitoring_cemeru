/*
 * stealth/modules/screen.js
 *
 * Profile-aware Screen accessors. Chromium exposes these properties on
 * Screen.prototype, so the module keeps that owner and only proxies the
 * native ScreenOrientation object when a profile supplies orientation values.
 */
(function screenStealthModule() {
  "use strict";

  if (typeof screen === "undefined" || typeof Screen === "undefined") return;

  const marker = Symbol.for("cemeru.stealth.screen.v1");
  const screenPrototype = Screen.prototype;
  if (screenPrototype[marker]) return;

  const profile = globalThis.__stealth &&
    globalThis.__stealth.screenProfile &&
    typeof globalThis.__stealth.screenProfile === "object"
    ? globalThis.__stealth.screenProfile
    : {};

  function descriptor(object, property) {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Reflect.getOwnPropertyDescriptor(owner, property);
      if (value) return { owner, value };
    }
    return null;
  }

  function nativeValue(property) {
    const found = descriptor(screen, property);
    try {
      if (found && typeof found.value.get === "function") {
        return Reflect.apply(found.value.get, screen, []);
      }
      return Reflect.get(screen, property);
    } catch (_error) {
      return undefined;
    }
  }

  function finiteNumber(value, fallback, minimum = -Infinity) {
    return typeof value === "number" && Number.isFinite(value) && value >= minimum
      ? value : fallback;
  }

  function integer(value, fallback, minimum = 0) {
    return Number.isInteger(value) && value >= minimum ? value : fallback;
  }

  const toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
  const sharedNavigator = globalThis.__stealth && globalThis.__stealth.navigatorFunctionState;
  const sharedWindow = globalThis.__stealth && globalThis.__stealth.windowFunctionState;
  const valid = (state) => state && state.sources && typeof state.sources.set === "function" &&
    typeof state.original === "function" && typeof state.replacement === "function";
  const existing = valid(sharedNavigator) ? sharedNavigator : (valid(sharedWindow) ? sharedWindow : null);
  const functionState = existing || (() => {
    const original = toStringDescriptor.value;
    const sources = new WeakMap();
    const replacement = new Proxy(original, {
      apply(target, thisArg, args) {
        if (sources.has(thisArg)) return sources.get(thisArg);
        return Reflect.apply(target, thisArg, args);
      },
    });
    const state = { original, sources, replacement };
    if (globalThis.__stealth && typeof globalThis.__stealth === "object") {
      try {
        Object.defineProperty(globalThis.__stealth, "screenFunctionState", {
          value: state,
          writable: false,
          enumerable: false,
          configurable: false,
        });
      } catch (_error) { /* another module owns the intrinsic wrapper */ }
    }
    return state;
  })();

  if (toStringDescriptor && toStringDescriptor.configurable &&
      toStringDescriptor.value !== functionState.replacement) {
    try {
      Object.defineProperty(Function.prototype, "toString", {
        value: functionState.replacement,
        writable: toStringDescriptor.writable,
        enumerable: toStringDescriptor.enumerable,
        configurable: toStringDescriptor.configurable,
      });
    } catch (_error) { /* hardened realms may refuse optional masking */ }
  }

  function nativeSource(functionValue, fallbackName) {
    if (typeof functionValue === "function") {
      try { return Reflect.apply(functionState.original, functionValue, []); } catch (_error) { /* fallback */ }
    }
    return `function ${fallbackName}() { [native code] }`;
  }

  if (!functionState.sources.has(functionState.replacement)) {
    functionState.sources.set(functionState.replacement, nativeSource(functionState.original, "toString"));
  }

  function nativeCallable(nativeFunction, implementation, name) {
    const fallback = Object.getOwnPropertyDescriptor(Object.prototype, "__proto__").get;
    const target = typeof nativeFunction === "function" ? nativeFunction : fallback;
    const result = new Proxy(target, {
      apply(_target, thisArg, args) {
        return Reflect.apply(implementation, thisArg, args);
      },
    });
    functionState.sources.set(result, nativeSource(nativeFunction, name));
    return result;
  }

  function installGetter(property, factory) {
    const found = descriptor(screen, property);
    if (!found || found.value.configurable === false || typeof found.value.get !== "function") return false;
    const original = found.value;
    const getter = nativeCallable(
      original.get,
      function getScreenProperty() {
        if (this !== screen && !(this instanceof Screen)) throw new TypeError("Illegal invocation");
        return factory();
      },
      original.get.name || `get ${property}`,
    );
    return Reflect.defineProperty(found.owner, property, {
      get: getter,
      set: original.set,
      enumerable: original.enumerable,
      configurable: original.configurable,
    });
  }

  const native = {
    width: nativeValue("width"),
    height: nativeValue("height"),
    availWidth: nativeValue("availWidth"),
    availHeight: nativeValue("availHeight"),
    availLeft: nativeValue("availLeft"),
    availTop: nativeValue("availTop"),
    colorDepth: nativeValue("colorDepth"),
    pixelDepth: nativeValue("pixelDepth"),
    orientation: nativeValue("orientation"),
  };

  const width = Math.max(
    integer(profile.width, integer(native.width, 0), 0),
    integer(profile.availWidth, integer(native.availWidth, 0), 0),
  );
  const height = Math.max(
    integer(profile.height, integer(native.height, 0), 0),
    integer(profile.availHeight, integer(native.availHeight, 0), 0),
  );
  const availWidth = Math.min(
    width,
    integer(profile.availWidth, integer(native.availWidth, width), 0),
  );
  const availHeight = Math.min(
    height,
    integer(profile.availHeight, integer(native.availHeight, height), 0),
  );
  const availLeft = finiteNumber(profile.availLeft, finiteNumber(native.availLeft, 0));
  const availTop = finiteNumber(profile.availTop, finiteNumber(native.availTop, 0));
  const colorDepth = integer(profile.colorDepth, integer(native.colorDepth, 24, 1), 1);
  const pixelDepth = colorDepth;

  const nativeOrientation = native.orientation && typeof native.orientation === "object"
    ? native.orientation : null;
  const orientationProfile = profile.orientation && typeof profile.orientation === "object"
    ? profile.orientation : {};
  const orientationType = typeof orientationProfile.type === "string"
    ? orientationProfile.type
    : (nativeOrientation && typeof nativeOrientation.type === "string"
      ? nativeOrientation.type
      : (width >= height ? "landscape-primary" : "portrait-primary"));
  const orientationAngle = Number.isInteger(orientationProfile.angle)
    ? orientationProfile.angle
    : (nativeOrientation && Number.isInteger(nativeOrientation.angle) ? nativeOrientation.angle : 0);

  let orientation = nativeOrientation;
  if (nativeOrientation && (Object.keys(profile).length > 0 || Object.keys(orientationProfile).length > 0)) {
    orientation = new Proxy(nativeOrientation, {
      get(target, property, receiver) {
        if (property === "type") return orientationType;
        if (property === "angle") return orientationAngle;
        return Reflect.get(target, property, receiver);
      },
    });
  }

  const values = {
    width: () => width,
    height: () => height,
    availWidth: () => availWidth,
    availHeight: () => availHeight,
    availLeft: () => availLeft,
    availTop: () => availTop,
    colorDepth: () => colorDepth,
    pixelDepth: () => pixelDepth,
    orientation: () => orientation,
  };
  for (const [property, factory] of Object.entries(values)) installGetter(property, factory);

  Object.defineProperty(screenPrototype, marker, {
    value: Object.freeze({ version: "1.0.0", profile: Object.keys(profile).length > 0 }),
    writable: false,
    enumerable: false,
    configurable: false,
  });
}());
