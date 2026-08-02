/*
 * stealth/modules/window.js
 *
 * A profile-aware Window surface adapter. Chromium exposes the viewport and
 * window-state accessors as configurable own properties on the Window proxy;
 * this module therefore patches the existing owner while retaining its native
 * descriptor flags, setter, and getter source. visualViewport remains backed
 * by the browser's VisualViewport instance and is only proxied when a profile
 * supplies viewport values.
 */
(function windowStealthModule() {
  "use strict";

  if (typeof window === "undefined" || typeof Window === "undefined") return;

  const marker = Symbol.for("cemeru.stealth.window.v1");
  if (window[marker]) return;

  const profile = globalThis.__stealth &&
    globalThis.__stealth.windowProfile &&
    typeof globalThis.__stealth.windowProfile === "object"
    ? globalThis.__stealth.windowProfile
    : {};

  function findDescriptor(object, property) {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Reflect.getOwnPropertyDescriptor(owner, property);
      if (value) return { owner, value };
    }
    return null;
  }

  function nativeValue(property) {
    const found = findDescriptor(window, property);
    try {
      if (found && typeof found.value.get === "function") {
        return Reflect.apply(found.value.get, window, []);
      }
      return Reflect.get(window, property);
    } catch (_error) {
      return undefined;
    }
  }

  function finiteNumber(value, fallback, minimum = -Infinity) {
    return typeof value === "number" && Number.isFinite(value) && value >= minimum
      ? value : fallback;
  }

  function hasOwn(object, property) {
    return Object.prototype.hasOwnProperty.call(object, property);
  }

  // Navigator's module installs this state first in the normal full stack.
  // Window reuses it when available; standalone window application gets its
  // own intrinsic wrapper and remains independently callable.
  const toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
  const shared = globalThis.__stealth && globalThis.__stealth.navigatorFunctionState;
  const existing = shared && shared.sources && typeof shared.sources.set === "function" &&
    typeof shared.original === "function" && typeof shared.replacement === "function"
    ? shared : (globalThis.__stealth && globalThis.__stealth.windowFunctionState);
  const functionState = existing && existing.sources && typeof existing.sources.set === "function" &&
    typeof existing.original === "function" && typeof existing.replacement === "function"
    ? existing : (() => {
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
          Object.defineProperty(globalThis.__stealth, "windowFunctionState", {
            value: state,
            writable: false,
            enumerable: false,
            configurable: false,
          });
        } catch (_error) { /* an earlier realm initializer owns the state */ }
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
    } catch (_error) { /* hardened realms may reject this optional masking */ }
  }

  function nativeSource(functionValue, fallbackName) {
    if (typeof functionValue === "function") {
      try { return Reflect.apply(functionState.original, functionValue, []); } catch (_error) { /* fallback */ }
    }
    return `function ${fallbackName}() { [native code] }`;
  }

  if (!functionState.sources.has(functionState.replacement)) {
    functionState.sources.set(
      functionState.replacement,
      nativeSource(functionState.original, "toString"),
    );
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
    const found = findDescriptor(window, property);
    if (!found || found.value.configurable === false || typeof found.value.get !== "function") {
      return false;
    }
    const original = found.value;
    const getter = nativeCallable(
      original.get,
      function getWindowProperty() {
        if (this !== window && !(this instanceof Window)) throw new TypeError("Illegal invocation");
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
    outerWidth: nativeValue("outerWidth"),
    outerHeight: nativeValue("outerHeight"),
    innerWidth: nativeValue("innerWidth"),
    innerHeight: nativeValue("innerHeight"),
    devicePixelRatio: nativeValue("devicePixelRatio"),
    screenX: nativeValue("screenX"),
    screenY: nativeValue("screenY"),
    pageXOffset: nativeValue("pageXOffset"),
    pageYOffset: nativeValue("pageYOffset"),
    scrollX: nativeValue("scrollX"),
    scrollY: nativeValue("scrollY"),
    visualViewport: nativeValue("visualViewport"),
    length: nativeValue("length"),
    closed: nativeValue("closed"),
    name: nativeValue("name"),
  };

  const profileViewport = profile.visualViewport && typeof profile.visualViewport === "object"
    ? profile.visualViewport : {};
  const hasProfileValues = Object.keys(profile).length > 0;
  const innerWidth = finiteNumber(profile.innerWidth, finiteNumber(native.innerWidth, 0, 0), 0);
  const innerHeight = finiteNumber(profile.innerHeight, finiteNumber(native.innerHeight, 0, 0), 0);
  const outerWidth = Math.max(
    innerWidth,
    finiteNumber(profile.outerWidth, finiteNumber(native.outerWidth, innerWidth, 0), 0),
  );
  const outerHeight = Math.max(
    innerHeight,
    finiteNumber(profile.outerHeight, finiteNumber(native.outerHeight, innerHeight, 0), 0),
  );
  const devicePixelRatio = finiteNumber(
    profile.devicePixelRatio,
    finiteNumber(native.devicePixelRatio, 1, Number.MIN_VALUE),
    Number.MIN_VALUE,
  );
  const screenX = finiteNumber(profile.screenX, finiteNumber(native.screenX, 0));
  const screenY = finiteNumber(profile.screenY, finiteNumber(native.screenY, 0));

  const scrollX = finiteNumber(
    hasOwn(profile, "scrollX") ? profile.scrollX : profile.pageXOffset,
    finiteNumber(native.scrollX, finiteNumber(native.pageXOffset, 0)),
  );
  const scrollY = finiteNumber(
    hasOwn(profile, "scrollY") ? profile.scrollY : profile.pageYOffset,
    finiteNumber(native.scrollY, finiteNumber(native.pageYOffset, 0)),
  );
  // scrollX/pageXOffset and scrollY/pageYOffset are aliases in a real
  // Window. Keep each pair canonical even if an embedding profile supplied
  // conflicting members.
  const pageXOffset = scrollX;
  const pageYOffset = scrollY;
  const length = Number.isInteger(profile.length) && profile.length >= 0
    ? profile.length : (Number.isInteger(native.length) ? native.length : 0);
  const closed = typeof profile.closed === "boolean" ? profile.closed : Boolean(native.closed);

  let windowName = typeof profile.name === "string" ? profile.name : String(native.name || "");
  const visualViewportValues = {
    width: finiteNumber(profileViewport.width, innerWidth, 0),
    height: finiteNumber(profileViewport.height, innerHeight, 0),
    scale: finiteNumber(profileViewport.scale, devicePixelRatio, Number.MIN_VALUE),
    offsetLeft: finiteNumber(profileViewport.offsetLeft, 0),
    offsetTop: finiteNumber(profileViewport.offsetTop, 0),
    pageLeft: pageXOffset,
    pageTop: pageYOffset,
  };

  let visualViewport = native.visualViewport;
  if (hasProfileValues && native.visualViewport && typeof native.visualViewport === "object") {
    const target = native.visualViewport;
    visualViewport = new Proxy(target, {
      get(inner, property, receiver) {
        if (Object.prototype.hasOwnProperty.call(visualViewportValues, property)) {
          return visualViewportValues[property];
        }
        return Reflect.get(inner, property, receiver);
      },
    });
  }

  const values = {
    outerWidth: () => outerWidth,
    outerHeight: () => outerHeight,
    innerWidth: () => innerWidth,
    innerHeight: () => innerHeight,
    devicePixelRatio: () => devicePixelRatio,
    screenX: () => screenX,
    screenY: () => screenY,
    pageXOffset: () => pageXOffset,
    pageYOffset: () => pageYOffset,
    scrollX: () => scrollX,
    scrollY: () => scrollY,
    visualViewport: () => visualViewport,
    length: () => length,
    closed: () => closed,
    name: () => windowName,
  };

  for (const [property, factory] of Object.entries(values)) {
    installGetter(property, factory);
  }

  // Keep Window.name's native setter semantics while making the profile value
  // stable and mutable like the real property.
  const nameDescriptor = findDescriptor(window, "name");
  if (nameDescriptor && typeof nameDescriptor.value.set === "function" && nameDescriptor.value.configurable) {
    const originalSetter = nameDescriptor.value.set;
    const setter = nativeCallable(originalSetter, function setWindowName(value) {
      windowName = String(value);
      try { Reflect.apply(originalSetter, window, [value]); } catch (_error) { /* detached realm */ }
    }, "set name");
    const current = Reflect.getOwnPropertyDescriptor(nameDescriptor.owner, "name");
    if (current && current.get) {
      Reflect.defineProperty(nameDescriptor.owner, "name", {
        get: current.get,
        set: setter,
        enumerable: current.enumerable,
        configurable: current.configurable,
      });
    }
  }

  Object.defineProperty(window, marker, {
    value: Object.freeze({ version: "1.0.0", profile: hasProfileValues }),
    writable: false,
    enumerable: false,
    configurable: false,
  });
}());
