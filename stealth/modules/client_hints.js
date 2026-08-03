/*
 * Profile-aware User-Agent Client Hints adapter.
 *
 * Only Navigator.prototype.userAgentData is wrapped.  The native
 * NavigatorUAData object remains the proxy target, so its prototype,
 * instanceof behavior, immutability, and browser security model are retained.
 * No user-agent string, request header, fetch, or XHR is changed.
 */
(function clientHintsStealthModule() {
  "use strict";

  if (typeof Navigator === "undefined" || typeof navigator === "undefined") return;
  const proto = Navigator.prototype;
  const marker = Symbol.for("cemeru.stealth.clientHints.v1");
  if (proto[marker]) return;

  const root = typeof globalThis !== "undefined" ? globalThis : window;
  const stealth = root && root.__stealth && typeof root.__stealth === "object" ? root.__stealth : null;
  const profile = stealth && stealth.clientHintsProfile && typeof stealth.clientHintsProfile === "object"
    ? stealth.clientHintsProfile : null;
  if (!profile || Object.keys(profile).length === 0) return;

  function descriptor(object, property) {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Object.getOwnPropertyDescriptor(owner, property);
      if (value) return { owner, value };
    }
    return null;
  }
  const found = descriptor(proto, "userAgentData");
  if (!found || !found.value || typeof found.value.get !== "function" || found.value.configurable === false) return;
  const nativeGetter = found.value.get;
  let nativeObject;
  try { nativeObject = Reflect.apply(nativeGetter, navigator, []); } catch (_error) { nativeObject = null; }
  if (!nativeObject || typeof nativeObject !== "object") return;

  const toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
  const validState = (state) => state && state.sources && typeof state.sources.set === "function" && typeof state.original === "function" && typeof state.replacement === "function";
  const shared = ["navigatorFunctionState", "windowFunctionState", "screenFunctionState", "chromeFunctionState", "permissionsFunctionState", "fontsFunctionState", "speechFunctionState", "performanceFunctionState", "webglFunctionState", "canvasFunctionState", "audioFunctionState"].map((key) => stealth && stealth[key]).find(validState);
  const functionState = shared || (() => {
    if (!toStringDescriptor || typeof toStringDescriptor.value !== "function") return null;
    const original = toStringDescriptor.value; const sources = new WeakMap();
    const replacement = new Proxy(original, { apply(target, thisArg, args) { return sources.has(thisArg) ? sources.get(thisArg) : Reflect.apply(target, thisArg, args); } });
    const state = { original, sources, replacement };
    if (stealth) { try { Object.defineProperty(stealth, "clientHintsFunctionState", { value: state, writable: false, enumerable: false, configurable: false }); } catch (_error) {} }
    return state;
  })();
  if (functionState && toStringDescriptor && toStringDescriptor.configurable && toStringDescriptor.value !== functionState.replacement) {
    try { Object.defineProperty(Function.prototype, "toString", { value: functionState.replacement, writable: toStringDescriptor.writable, enumerable: toStringDescriptor.enumerable, configurable: toStringDescriptor.configurable }); } catch (_error) {}
  }
  if (functionState && !functionState.sources.has(functionState.replacement)) functionState.sources.set(functionState.replacement, "function toString() { [native code] }");
  function nativeSource(value, fallback) { if (functionState && typeof value === "function") { try { return Reflect.apply(functionState.original, value, []); } catch (_error) {} } return fallback; }
  function callable(nativeFunction, implementation, name) {
    if (typeof nativeFunction !== "function") return implementation;
    const wrapped = new Proxy(nativeFunction, { apply(_target, receiver, args) { return Reflect.apply(implementation, receiver, args); } });
    if (functionState) functionState.sources.set(wrapped, nativeSource(nativeFunction, `function ${name}() { [native code] }`));
    return wrapped;
  }

  function profileValue(name, fallback) {
    const high = profile.high_entropy && typeof profile.high_entropy === "object" ? profile.high_entropy : {};
    if (Object.prototype.hasOwnProperty.call(profile, name)) return profile[name];
    if (Object.prototype.hasOwnProperty.call(high, name)) return high[name];
    return fallback;
  }
  function immutableBrands(value) {
    if (!Array.isArray(value)) return value;
    return Object.freeze(value.filter((entry) => entry && typeof entry === "object").map((entry) => Object.freeze({ brand: String(entry.brand || ""), version: String(entry.version || "") })));
  }
  function nativeRead(property) {
    try { return Reflect.get(nativeObject, property); } catch (_error) { return undefined; }
  }
  function lowEntropy(name) {
    const nativeValue = nativeRead(name);
    const value = profileValue(name, nativeValue);
    if (name === "brands" || name === "fullVersionList") return immutableBrands(value);
    if (name === "mobile") return typeof value === "boolean" ? value : nativeValue;
    return typeof value === "string" ? value : nativeValue;
  }
  function highEntropyObject(hints, nativeValue) {
    const result = {};
    const requested = Array.isArray(hints) ? hints : [];
    requested.forEach((name) => {
      const source = profileValue(name, nativeValue && nativeValue[name]);
      if (source !== undefined) result[name] = name === "brands" || name === "fullVersionList" ? immutableBrands(source) : source;
    });
    return result;
  }

  const proxyCache = new WeakMap();
  function wrappedData(nativeValue) {
    if (proxyCache.has(nativeValue)) return proxyCache.get(nativeValue);
    const nativeGetHigh = typeof nativeValue.getHighEntropyValues === "function" ? nativeValue.getHighEntropyValues : null;
    const nativeJSON = typeof nativeValue.toJSON === "function" ? nativeValue.toJSON : null;
    const wrapper = new Proxy(nativeValue, {
      get(target, property, receiver) {
        if (["brands", "mobile", "platform"].includes(property)) return lowEntropy(property);
        if (["architecture", "bitness", "model", "platformVersion", "uaFullVersion", "fullVersionList"].includes(property)) {
          const value = profileValue(property, Reflect.get(target, property, receiver));
          return property === "fullVersionList" ? immutableBrands(value) : value;
        }
        if (property === "getHighEntropyValues" && nativeGetHigh) {
          return callable(nativeGetHigh, function getHighEntropyValues(hints) {
            if (this !== wrapper && this !== nativeValue) throw new TypeError("Illegal invocation");
            const nativeResult = Reflect.apply(nativeGetHigh, nativeValue, [hints]);
            return Promise.resolve(nativeResult).then((value) => highEntropyObject(hints, value));
          }, nativeGetHigh.name || "getHighEntropyValues");
        }
        if (property === "toJSON" && nativeJSON) {
          return callable(nativeJSON, function toJSON() {
            if (this !== wrapper && this !== nativeValue) throw new TypeError("Illegal invocation");
            const value = Reflect.apply(nativeJSON, nativeValue, []);
            const result = value && typeof value === "object" ? Object.assign({}, value) : {};
            result.brands = lowEntropy("brands"); result.mobile = lowEntropy("mobile"); result.platform = lowEntropy("platform");
            return result;
          }, nativeJSON.name || "toJSON");
        }
        return Reflect.get(target, property, receiver);
      },
    });
    proxyCache.set(nativeValue, wrapper); return wrapper;
  }

  const getter = callable(nativeGetter, function getUserAgentData() {
    if (this !== navigator && !(this instanceof Navigator)) throw new TypeError("Illegal invocation");
    return wrappedData(Reflect.apply(nativeGetter, navigator, []));
  }, nativeGetter.name || "get userAgentData");
  try {
    Object.defineProperty(found.owner, "userAgentData", { get: getter, set: found.value.set, enumerable: found.value.enumerable, configurable: found.value.configurable });
    Object.defineProperty(proto, marker, { value: true, writable: false, enumerable: false, configurable: false });
  } catch (_error) { /* hardened Navigator prototype */ }
})();
