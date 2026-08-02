/*
 * Navigator profile adapter.
 *
 * This module deliberately patches Navigator.prototype (where Chromium puts
 * these members), rather than putting enumerable properties on navigator.
 * Values are derived from the browser's native UA/context and can optionally
 * be supplied by an embedding profile at window.__stealth.navigatorProfile.
 * The default is therefore a coherent browser family, not a laptop-specific
 * fingerprint.
 */
(function navigatorStealthModule() {
  "use strict";

  if (typeof Navigator === "undefined" || typeof navigator === "undefined") return;

  const marker = Symbol.for("cemeru.stealth.navigator.v1");
  const proto = Navigator.prototype;
  if (proto[marker]) return;

  const profile = globalThis.__stealth &&
    globalThis.__stealth.navigatorProfile &&
    typeof globalThis.__stealth.navigatorProfile === "object"
    ? globalThis.__stealth.navigatorProfile
    : {};

  // Chromium's Function#toString intentionally hides the target name when
  // called on a Proxy. Keep a private WeakMap of our Proxies and preserve the
  // exact native source captured from the original browser function. The
  // hook is installed once, non-enumerably, and delegates every other call to
  // the original intrinsic.
  const toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
  const stealthState = globalThis.__stealth && globalThis.__stealth.navigatorFunctionState;
  const functionState = stealthState && stealthState.sources &&
      typeof stealthState.sources.set === "function" &&
      typeof stealthState.original === "function" &&
      typeof stealthState.replacement === "function"
    ? stealthState
    : (() => {
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
          Object.defineProperty(globalThis.__stealth, "navigatorFunctionState", {
            value: state,
            writable: false,
            enumerable: false,
            configurable: false,
          });
        } catch (_error) { /* another init script installed it first */ }
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
    } catch (_error) { /* hardened realms may refuse this optional polish */ }
  }

  function nativeSource(functionValue, fallbackName) {
    if (typeof functionValue === "function") {
      try { return Reflect.apply(functionState.original, functionValue, []); } catch (_error) { /* fall through */ }
    }
    return `function ${fallbackName}() { [native code] }`;
  }
  // Masking the intrinsic must not make the intrinsic itself look anonymous.
  if (!functionState.sources.has(functionState.replacement)) {
    functionState.sources.set(
      functionState.replacement,
      nativeSource(functionState.original, "toString"),
    );
  }

  function descriptor(object, property) {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Reflect.getOwnPropertyDescriptor(owner, property);
      if (value) return { owner, value };
    }
    return null;
  }

  function nativeValue(property) {
    const found = descriptor(navigator, property);
    try {
      if (found && typeof found.value.get === "function") {
        return Reflect.apply(found.value.get, navigator, []);
      }
      return Reflect.get(navigator, property);
    } catch (_error) {
      return undefined;
    }
  }

  function callable(nativeFunction, implementation, name, length) {
    // Proxying the browser's actual function preserves its native name and
    // Function#toString source while allowing the implementation to enforce
    // the desired result. Do not bind/replace the target: bound functions lose
    // the original source spelling (for example, ``get webdriver``).
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
    const found = descriptor(navigator, property);
    const owner = found ? found.owner : proto;
    const original = found && found.value;
    if (original && original.configurable === false) return false;
    const getter = callable(
      original && original.get,
      function getNavigatorProperty() {
        if (this !== navigator && !(this instanceof Navigator)) {
          throw new TypeError("Illegal invocation");
        }
        return factory();
      },
      original && original.get ? original.get.name : `get ${property}`,
      0,
    );
    return Reflect.defineProperty(owner, property, {
      get: getter,
      set: original && Object.prototype.hasOwnProperty.call(original, "set")
        ? original.set : undefined,
      enumerable: original ? original.enumerable : true,
      configurable: original ? original.configurable : true,
    });
  }

  function stringOr(value, fallback) {
    return typeof value === "string" && value ? value : fallback;
  }

  function boolOr(value, fallback) {
    return typeof value === "boolean" ? value : fallback;
  }

  function integerOr(value, fallback, minimum) {
    return Number.isInteger(value) && value >= minimum ? value : fallback;
  }

  function freezeArray(values) {
    return Object.freeze(Array.from(values));
  }

  function brandsFrom(value) {
    if (!Array.isArray(value)) return [];
    return value.filter((entry) => entry && typeof entry.brand === "string")
      .map((entry) => Object.freeze({ brand: entry.brand, version: String(entry.version || "") }));
  }

  const native = {
    userAgent: nativeValue("userAgent"),
    userAgentData: nativeValue("userAgentData"),
    webdriver: nativeValue("webdriver"),
    languages: nativeValue("languages"),
    language: nativeValue("language"),
    platform: nativeValue("platform"),
    vendor: nativeValue("vendor"),
    deviceMemory: nativeValue("deviceMemory"),
    hardwareConcurrency: nativeValue("hardwareConcurrency"),
    plugins: nativeValue("plugins"),
    mimeTypes: nativeValue("mimeTypes"),
    pdfViewerEnabled: nativeValue("pdfViewerEnabled"),
    maxTouchPoints: nativeValue("maxTouchPoints"),
    cookieEnabled: nativeValue("cookieEnabled"),
    onLine: nativeValue("onLine"),
    doNotTrack: nativeValue("doNotTrack"),
  };

  const ua = stringOr(native.userAgent, "");
  const nativeUAData = native.userAgentData && typeof native.userAgentData === "object"
    ? native.userAgentData : null;
  const nativeUAPlatform = nativeUAData ? stringOr(nativeUAData.platform, "") : "";
  const configuredMobile = profile.userAgentData && profile.userAgentData.mobile;
  const mobile = typeof configuredMobile === "boolean" ? configuredMobile
    : (nativeUAData && typeof nativeUAData.mobile === "boolean"
      ? nativeUAData.mobile : /Android|Mobile|iPhone|iPad/i.test(ua));
  const chromium = /(?:Chrome|Chromium)\//i.test(ua) ||
    /Google Inc\./i.test(String(native.vendor || "")) ||
    brandsFrom(nativeUAData && nativeUAData.brands)
      .some((entry) => /Chrome|Chromium|Edge/i.test(entry.brand));

  function operatingSystem() {
    const value = `${nativeUAPlatform} ${ua}`;
    if (/Android/i.test(value)) return "Android";
    if (/Windows/i.test(value)) return "Windows";
    if (/iPhone|iPad|iPod/i.test(value)) return "iOS";
    if (/Macintosh|Mac OS X|macOS/i.test(value)) return "macOS";
    if (/Linux|X11/i.test(value)) return "Linux";
    return "Unknown";
  }

  const os = operatingSystem();
  const platform = stringOr(profile.platform, (() => {
    if (os === "Windows") return "Win32";
    if (os === "macOS" || os === "iOS") return "MacIntel";
    if (os === "Android") return "Linux armv8l";
    return stringOr(native.platform, os === "Linux" ? "Linux x86_64" : "Win32");
  })());

  function normaliseLanguages() {
    const configured = Array.isArray(profile.languages) ? profile.languages : null;
    const source = configured && configured.length ? configured
      : (Array.isArray(native.languages) ? native.languages : []);
    const values = source.filter((value, index) => typeof value === "string" && value &&
      source.indexOf(value) === index);
    const primary = stringOr(profile.language, stringOr(native.language, values[0] || "en-US"));
    if (!values.includes(primary)) values.unshift(primary);
    else if (values[0] !== primary) {
      values.splice(values.indexOf(primary), 1);
      values.unshift(primary);
    }
    return freezeArray(values);
  }

  const languages = normaliseLanguages();
  const language = languages[0];
  const vendor = stringOr(profile.vendor,
    chromium ? "Google Inc." : stringOr(native.vendor, ""));
  const hardwareConcurrency = integerOr(
    profile.hardwareConcurrency,
    integerOr(native.hardwareConcurrency, mobile ? 4 : 8, 1),
    1,
  );
  const memoryCandidate = profile.deviceMemory ?? native.deviceMemory;
  const memoryBuckets = [0.25, 0.5, 1, 2, 4, 8];
  const deviceMemory = memoryBuckets.includes(memoryCandidate)
    ? memoryCandidate : (mobile ? 4 : 8);
  const maxTouchPoints = integerOr(
    profile.maxTouchPoints,
    integerOr(native.maxTouchPoints, mobile ? 5 : 0, 0),
    0,
  );
  const cookieEnabled = boolOr(profile.cookieEnabled, boolOr(native.cookieEnabled, true));
  const onLine = boolOr(profile.onLine, boolOr(native.onLine, true));
  const doNotTrack = profile.doNotTrack === null || ["0", "1", "unspecified"].includes(profile.doNotTrack)
    ? profile.doNotTrack
    : (native.doNotTrack === null || ["0", "1", "unspecified"].includes(native.doNotTrack)
      ? native.doNotTrack : null);

  function majorVersion() {
    const match = ua.match(/(?:Chrome|Chromium)\/(\d+(?:\.\d+){0,3})/i);
    return match ? match[1].split(".")[0] : "0";
  }

  function fourPartVersion(value) {
    const parts = String(value).split(".");
    while (parts.length < 4) parts.push("0");
    return parts.slice(0, 4).join(".");
  }

  const nativeBrands = brandsFrom(nativeUAData && nativeUAData.brands);
  const configuredBrands = brandsFrom(profile.userAgentData && profile.userAgentData.brands);
  const brands = freezeArray(configuredBrands.length ? configuredBrands
    : (nativeBrands.length ? nativeBrands : (chromium && majorVersion() !== "0"
      ? [
        { brand: "Not;A=Brand", version: "8" },
        { brand: "Chromium", version: majorVersion() },
        { brand: "Google Chrome", version: majorVersion() },
      ].map((entry) => Object.freeze(entry)) : [])));
  const configuredUAPlatform = profile.userAgentData && profile.userAgentData.platform;
  const platformHint = profile.platform === "Win32" || profile.platform === "Win64"
    ? "Windows" : (profile.platform === "MacIntel" ? "macOS" :
      (/Linux/i.test(String(profile.platform || "")) ? "Linux" : ""));
  const uaPlatform = stringOr(
    configuredUAPlatform,
    nativeUAPlatform || platformHint || ({ Windows: "Windows", macOS: "macOS", iOS: "iOS", Android: "Android" }[os] || "Linux"),
  );

  function highEntropy(key) {
    const supplied = profile.userAgentData && profile.userAgentData.highEntropy;
    if (supplied && Object.prototype.hasOwnProperty.call(supplied, key)) return supplied[key];
    if (key === "architecture") return /arm|aarch/i.test(`${platform} ${ua}`) ? "arm" : "x86";
    if (key === "bitness") return /64|x64|aarch64|arm64/i.test(`${platform} ${ua}`) ? "64" : "32";
    if (key === "brands") return brands;
    if (key === "fullVersionList") return freezeArray(brands.map((entry) => Object.freeze({
      brand: entry.brand,
      version: /Chrome|Chromium/i.test(entry.brand) ? fourPartVersion(majorVersion()) : fourPartVersion(entry.version),
    })));
    if (key === "mobile") return mobile;
    if (key === "model") return mobile ? stringOr(supplied && supplied.model, "") : "";
    if (key === "platform") return uaPlatform;
    if (key === "platformVersion") return stringOr(supplied && supplied.platformVersion, "");
    if (key === "uaFullVersion") return fourPartVersion(majorVersion());
    if (key === "wow64") return false;
    return undefined;
  }

  function makeUAData() {
    const target = nativeUAData || (typeof NavigatorUAData === "function"
      ? Object.create(NavigatorUAData.prototype) : Object.create(null));
    const nativeHighEntropy = nativeUAData && typeof nativeUAData.getHighEntropyValues === "function"
      ? nativeUAData.getHighEntropyValues : null;
    const nativeJSON = nativeUAData && typeof nativeUAData.toJSON === "function"
      ? nativeUAData.toJSON : null;
    const getHighEntropyValues = callable(nativeHighEntropy, function getHighEntropyValues(hints) {
      if (typeof NavigatorUAData === "function" && !(this instanceof NavigatorUAData)) {
        throw new TypeError("Illegal invocation");
      }
      if (!Array.isArray(hints)) throw new TypeError("The hints argument must be an array");
      const requested = hints.map(String);
      const result = nativeHighEntropy
        ? Reflect.apply(nativeHighEntropy, nativeUAData, [requested]) : Promise.resolve({});
      return Promise.resolve(result).then((value) => {
        const output = Object.assign({}, value, { brands, mobile, platform: uaPlatform });
        for (const key of requested) {
          const generated = highEntropy(key);
          if (generated !== undefined) output[key] = generated;
        }
        return output;
      });
    }, "getHighEntropyValues", 1);
    const toJSON = callable(nativeJSON, function toJSON() {
      if (typeof NavigatorUAData === "function" && !(this instanceof NavigatorUAData)) {
        throw new TypeError("Illegal invocation");
      }
      return { brands, mobile, platform: uaPlatform };
    }, "toJSON", 0);
    return new Proxy(target, {
      get(inner, property, receiver) {
        if (property === "brands") return brands;
        if (property === "mobile") return mobile;
        if (property === "platform") return uaPlatform;
        if (property === "getHighEntropyValues") return getHighEntropyValues;
        if (property === "toJSON") return toJSON;
        return Reflect.get(inner, property, receiver);
      },
    });
  }

  const userAgentData = chromium || nativeUAData ? makeUAData() : nativeUAData;

  function collectionDescriptor(value, enumerable) {
    return { value, writable: false, enumerable, configurable: true };
  }

  function keysFor(entries, name) {
    const keys = entries.map((_value, index) => String(index));
    for (const entry of entries) {
      const key = name(entry);
      if (key && !keys.includes(key)) keys.push(key);
    }
    return keys;
  }

  function method(nativeMethod, implementation, name, length) {
    return callable(nativeMethod, implementation, name, length);
  }

  function createMimeType(type, pluginRef) {
    const target = Object.create(typeof MimeType === "function" ? MimeType.prototype : Object.prototype);
    const values = { type, suffixes: "pdf", description: "Portable Document Format" };
    return new Proxy(target, {
      get(inner, property, receiver) {
        if (property === "enabledPlugin") return pluginRef();
        if (Object.prototype.hasOwnProperty.call(values, property)) return values[property];
        return Reflect.get(inner, property, receiver);
      },
    });
  }

  function createPlugin(definition, mimeEntries) {
    const target = Object.create(typeof Plugin === "function" ? Plugin.prototype : Object.prototype);
    const item = method(target.item, (index) => mimeEntries[Number(index)] || null, "item", 1);
    const namedItem = method(target.namedItem, (name) => mimeEntries.find((entry) => entry.type === String(name)) || null, "namedItem", 1);
    const iterator = method(Array.prototype[Symbol.iterator], () => mimeEntries[Symbol.iterator](), "values", 0);
    const values = { name: definition.name, filename: definition.filename, description: definition.description };
    return new Proxy(target, {
      get(inner, property, receiver) {
        if (property === "length") return mimeEntries.length;
        if (property === "item") return item;
        if (property === "namedItem") return namedItem;
        if (property === Symbol.iterator) return iterator;
        if (/^\d+$/.test(String(property))) return mimeEntries[Number(property)];
        if (Object.prototype.hasOwnProperty.call(values, property)) return values[property];
        if (typeof property === "string") return mimeEntries.find((entry) => entry.type === property) || Reflect.get(inner, property, receiver);
        return Reflect.get(inner, property, receiver);
      },
      ownKeys() { return keysFor(mimeEntries, (entry) => entry.type); },
      getOwnPropertyDescriptor(_inner, property) {
        if (/^\d+$/.test(String(property))) {
          const value = mimeEntries[Number(property)];
          return value === undefined ? undefined : collectionDescriptor(value, true);
        }
        const value = mimeEntries.find((entry) => entry.type === property);
        return value ? collectionDescriptor(value, false) : undefined;
      },
    });
  }

  function createPdfCollections() {
    let primaryPlugin = null;
    const mimeTypes = ["application/pdf", "text/pdf"].map((type) => createMimeType(type, () => primaryPlugin));
    const definitions = [
      "PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer",
      "Microsoft Edge PDF Viewer", "WebKit built-in PDF",
    ].map((name) => ({ name, filename: "internal-pdf-viewer", description: "Portable Document Format" }));
    const plugins = definitions.map((definition) => createPlugin(definition, mimeTypes));
    primaryPlugin = plugins[0];

    function collection(target, entries, prototype, name, hasRefresh) {
      const item = method(prototype && prototype.item, (index) => entries[Number(index)] || null, "item", 1);
      const namedItem = method(prototype && prototype.namedItem, (value) => entries.find((entry) => name(entry) === String(value)) || null, "namedItem", 1);
      const iterator = method(prototype && prototype[Symbol.iterator], () => entries[Symbol.iterator](), "values", 0);
      const refresh = hasRefresh ? method(prototype && prototype.refresh, () => undefined, "refresh", 0) : null;
      return new Proxy(target, {
        get(inner, property, receiver) {
          if (property === "length") return entries.length;
          if (property === "item") return item;
          if (property === "namedItem") return namedItem;
          if (property === "refresh" && refresh) return refresh;
          if (property === Symbol.iterator) return iterator;
          if (/^\d+$/.test(String(property))) return entries[Number(property)];
          if (typeof property === "string") return entries.find((entry) => name(entry) === property) || Reflect.get(inner, property, receiver);
          return Reflect.get(inner, property, receiver);
        },
        ownKeys() { return keysFor(entries, name); },
        getOwnPropertyDescriptor(_inner, property) {
          if (/^\d+$/.test(String(property))) {
            const value = entries[Number(property)];
            return value === undefined ? undefined : collectionDescriptor(value, true);
          }
          const value = entries.find((entry) => name(entry) === property);
          return value ? collectionDescriptor(value, false) : undefined;
        },
      });
    }

    const pluginTarget = native.plugins && typeof native.plugins === "object" ? native.plugins
      : Object.create(typeof PluginArray === "function" ? PluginArray.prototype : Object.prototype);
    const mimeTarget = native.mimeTypes && typeof native.mimeTypes === "object" ? native.mimeTypes
      : Object.create(typeof MimeTypeArray === "function" ? MimeTypeArray.prototype : Object.prototype);
    return {
      plugins: collection(pluginTarget, plugins, Reflect.getPrototypeOf(pluginTarget), (entry) => entry.name, true),
      mimeTypes: collection(mimeTarget, mimeTypes, Reflect.getPrototypeOf(mimeTarget), (entry) => entry.type, false),
    };
  }

  const nativePluginCount = native.plugins && Number.isInteger(native.plugins.length) ? native.plugins.length : 0;
  const nativeMimeCount = native.mimeTypes && Number.isInteger(native.mimeTypes.length) ? native.mimeTypes.length : 0;
  // Headless Chromium commonly reports no PDF plugins and false here even
  // though the headed Chrome profile exposes its built-in PDF viewer. Treat
  // that as a missing capability, not as a user preference. An explicit
  // profile value still wins.
  const exposePdf = typeof profile.pdfViewerEnabled === "boolean"
    ? profile.pdfViewerEnabled
    : (chromium && !mobile);
  const collections = chromium && !mobile && exposePdf && nativePluginCount === 0 && nativeMimeCount === 0
    ? createPdfCollections() : null;
  const plugins = collections ? collections.plugins : native.plugins;
  const mimeTypes = collections ? collections.mimeTypes : native.mimeTypes;

  const values = {
    webdriver: () => false,
    languages: () => languages,
    language: () => language,
    platform: () => platform,
    vendor: () => vendor,
    deviceMemory: () => deviceMemory,
    hardwareConcurrency: () => hardwareConcurrency,
    userAgentData: () => userAgentData,
    plugins: () => plugins,
    mimeTypes: () => mimeTypes,
    pdfViewerEnabled: () => Boolean(exposePdf && plugins && plugins.length),
    maxTouchPoints: () => maxTouchPoints,
    cookieEnabled: () => cookieEnabled,
    onLine: () => onLine,
    doNotTrack: () => doNotTrack,
  };
  for (const [property, factory] of Object.entries(values)) installGetter(property, factory);

  Object.defineProperty(proto, marker, {
    value: Object.freeze({ version: "1.0.0", os }),
    writable: false,
    enumerable: false,
    configurable: false,
  });
}());
