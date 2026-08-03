/*
 * Profile-aware Performance API compatibility layer.
 *
 * The browser remains the source of truth when no profile is supplied.  With
 * a profile, only requested fields are represented: now() keeps using the
 * native monotonic clock with a fixed offset, while timing and entry objects
 * retain their native prototypes through prototype-backed proxies.
 */
(function performanceStealthModule() {
  "use strict";

  if (typeof performance === "undefined" || typeof Performance === "undefined") return;

  const perf = performance;
  const performancePrototype = Performance.prototype;
  const marker = Symbol.for("cemeru.stealth.performance.v1");
  if (performancePrototype[marker]) return;

  const stealth = globalThis.__stealth && typeof globalThis.__stealth === "object"
    ? globalThis.__stealth : null;
  const profile = stealth && stealth.performanceProfile &&
    typeof stealth.performanceProfile === "object" ? stealth.performanceProfile : {};
  const hasProfile = Object.keys(profile).length > 0;

  const own = (object, property) =>
    Object.prototype.hasOwnProperty.call(object, property);
  const finite = (value) => typeof value === "number" && Number.isFinite(value);

  function descriptor(object, property) {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Object.getOwnPropertyDescriptor(owner, property);
      if (value) return { owner, value };
    }
    return null;
  }

  function nativeRead(property) {
    try { return Reflect.get(perf, property); }
    catch (_error) { return undefined; }
  }

  /* Reuse the intrinsic source masker used by the other modules. */
  const toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
  const isState = (state) => state && state.sources &&
    typeof state.sources.set === "function" && typeof state.original === "function" &&
    typeof state.replacement === "function";
  const shared = hasProfile && isState(stealth && stealth.navigatorFunctionState)
    ? stealth.navigatorFunctionState
    : (hasProfile && isState(stealth && stealth.windowFunctionState)
      ? stealth.windowFunctionState
      : (hasProfile && isState(stealth && stealth.screenFunctionState)
        ? stealth.screenFunctionState
        : (hasProfile && isState(stealth && stealth.chromeFunctionState)
          ? stealth.chromeFunctionState
          : (hasProfile && isState(stealth && stealth.permissionsFunctionState)
            ? stealth.permissionsFunctionState
            : (hasProfile && isState(stealth && stealth.fontsFunctionState)
              ? stealth.fontsFunctionState
              : (hasProfile && isState(stealth && stealth.speechFunctionState)
                ? stealth.speechFunctionState : null))))));
  const functionState = hasProfile && (shared || (() => {
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
        Object.defineProperty(stealth, "performanceFunctionState", {
          value: state, writable: false, enumerable: false, configurable: false,
        });
      } catch (_error) { /* optional state storage */ }
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
    } catch (_error) { /* hardened realms may refuse optional masking */ }
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
    if (!functionState || typeof nativeFunction !== "function") return nativeFunction;
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

  function validReceiver(value) {
    if (value === perf) return true;
    try { return value instanceof Performance; }
    catch (_error) { return false; }
  }

  function installGetter(property, implementation) {
    const found = descriptor(performancePrototype, property);
    if (!found || !found.value || found.value.configurable === false ||
        typeof found.value.get !== "function") return null;
    const getter = callable(
      found.value.get,
      implementation,
      found.value.get.name || `get ${property}`,
      `function get ${property}() { [native code] }`,
    );
    if (typeof getter !== "function") return null;
    Reflect.defineProperty(found.owner, property, {
      get: getter,
      set: found.value.set,
      enumerable: found.value.enumerable,
      configurable: found.value.configurable,
    });
    return found.value.get;
  }

  function installMethod(property, implementation) {
    const found = descriptor(performancePrototype, property);
    if (!found || !found.value || found.value.configurable === false ||
        typeof found.value.value !== "function") return null;
    const method = callable(
      found.value.value,
      implementation,
      found.value.value.name || property,
      `function ${property}() { [native code] }`,
    );
    if (typeof method !== "function") return null;
    Reflect.defineProperty(found.owner, property, {
      value: method,
      writable: found.value.writable,
      enumerable: found.value.enumerable,
      configurable: found.value.configurable,
    });
    return found.value.value;
  }

  const nativeNowDescriptor = descriptor(performancePrototype, "now");
  const nativeNow = nativeNowDescriptor && nativeNowDescriptor.value.value;
  const nativeTimeOrigin = nativeRead("timeOrigin");
  const nativeTiming = nativeRead("timing");
  const nativeNavigation = nativeRead("navigation");
  const nativeMemory = nativeRead("memory");

  let lastNow = finite(nativeNow) ? nativeNow : 0;
  let nowOffset = 0;
  if (finite(profile.now) && typeof nativeNow === "function") {
    try { nowOffset = profile.now - Reflect.apply(nativeNow, perf, []); }
    catch (_error) { nowOffset = 0; }
    lastNow = profile.now - 0.001;
    installMethod("now", function now() {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      let value = Reflect.apply(nativeNow, this, []) + nowOffset;
      if (!finite(value)) value = lastNow + 0.001;
      if (value <= lastNow) value = lastNow + 0.001;
      lastNow = value;
      return value;
    });
  }

  if (finite(profile.timeOrigin)) {
    installGetter("timeOrigin", function getTimeOrigin() {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      return profile.timeOrigin;
    });
  }

  function timingValues() {
    const source = profile.timing && typeof profile.timing === "object" ? profile.timing : {};
    const order = [
      "navigationStart", "unloadEventStart", "unloadEventEnd", "redirectStart", "redirectEnd",
      "fetchStart", "domainLookupStart", "domainLookupEnd", "connectStart", "secureConnectionStart",
      "connectionEnd", "connectEnd", "requestStart", "responseStart", "responseEnd",
      "domInteractive", "domContentLoadedEventStart", "domContentLoadedEventEnd", "domComplete",
      "loadEventStart", "loadEventEnd",
    ];
    const result = {};
    let previous = null;
    for (const key of order) {
      let value;
      if (finite(source[key])) value = source[key];
      else if (key === "navigationStart" && finite(profile.timeOrigin)) value = profile.timeOrigin;
      else {
        try { value = nativeTiming && nativeTiming[key]; } catch (_error) { value = undefined; }
      }
      if (!finite(value)) value = previous == null ? 0 : previous + 0.001;
      if (previous != null && value <= previous) value = previous + 0.001;
      result[key] = value;
      previous = value;
    }
    return result;
  }

  function proxyWithValues(target, values, fallbackTarget) {
    const base = target && typeof target === "object"
      ? target : Object.create(fallbackTarget ? Object.getPrototypeOf(fallbackTarget) : Object.prototype);
    const nativeToJSON = target && typeof target.toJSON === "function" ? target.toJSON : null;
    const jsonFunction = callable(
      nativeToJSON,
      function toJSON() {
        const output = {};
        for (const key of Object.keys(values)) output[key] = values[key];
        return output;
      },
      "toJSON",
      "function toJSON() { [native code] }",
    ) || function toJSON() {
      const output = {};
      for (const key of Object.keys(values)) output[key] = values[key];
      return output;
    };
    return new Proxy(base, {
      get(inner, property, receiver) {
        if (own(values, property)) return values[property];
        if (property === "toJSON") return jsonFunction;
        return Reflect.get(inner, property, receiver);
      },
    });
  }

  if (hasProfile && (profile.timing || finite(profile.timeOrigin))) {
    const timing = proxyWithValues(nativeTiming, timingValues(), nativeTiming);
    installGetter("timing", function getTiming() {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      return timing;
    });
  }

  if (hasProfile && profile.navigation && typeof profile.navigation === "object") {
    const values = {
      type: profile.navigation.type !== undefined ? profile.navigation.type : nativeNavigation && nativeNavigation.type,
      redirectCount: finite(profile.navigation.redirectCount)
        ? profile.navigation.redirectCount : (nativeNavigation && nativeNavigation.redirectCount),
    };
    const navigation = proxyWithValues(nativeNavigation, values, nativeNavigation);
    installGetter("navigation", function getNavigation() {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      return navigation;
    });
  }

  if (hasProfile && profile.memory && typeof profile.memory === "object" && nativeMemory) {
    const memory = proxyWithValues(nativeMemory, profile.memory, nativeMemory);
    installGetter("memory", function getMemory() {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      return memory;
    });
  }

  const entryRecords = new WeakMap();
  const syntheticEntries = [];

  function entryPrototype(entryType) {
    const constructors = {
      navigation: typeof PerformanceNavigationTiming !== "undefined" && PerformanceNavigationTiming,
      resource: typeof PerformanceResourceTiming !== "undefined" && PerformanceResourceTiming,
      mark: typeof PerformanceMark !== "undefined" && PerformanceMark,
      measure: typeof PerformanceMeasure !== "undefined" && PerformanceMeasure,
    };
    const ctor = constructors[entryType] || PerformanceEntry;
    return ctor && ctor.prototype ? ctor.prototype : PerformanceEntry.prototype;
  }

  function makeEntry(input, fallbackType) {
    const data = input && typeof input === "object" ? input : {};
    const entryType = typeof data.entryType === "string" ? data.entryType : fallbackType;
    const target = Object.create(entryPrototype(entryType));
    const values = {
      name: typeof data.name === "string" ? data.name : "",
      entryType,
      startTime: finite(data.startTime) ? data.startTime : 0,
      duration: finite(data.duration) ? Math.max(0, data.duration) : 0,
    };
    for (const key of Object.keys(data)) {
      if (!(key in values)) values[key] = data[key];
    }
    const nativeToJSON = descriptor(Object.getPrototypeOf(target), "toJSON");
    const jsonFunction = callable(
      nativeToJSON && nativeToJSON.value.value,
      function toJSON() {
        const output = {};
        for (const key of Object.keys(values)) output[key] = values[key];
        return output;
      },
      "toJSON",
      "function toJSON() { [native code] }",
    ) || function toJSON() {
      const output = {};
      for (const key of Object.keys(values)) output[key] = values[key];
      return output;
    };
    const proxy = new Proxy(target, {
      get(inner, property, receiver) {
        if (own(values, property)) return values[property];
        if (property === "toJSON") return jsonFunction;
        return Reflect.get(inner, property, receiver);
      },
    });
    entryRecords.set(proxy, values);
    return proxy;
  }

  function navigationEntry() {
    const source = profile.navigation_timing && typeof profile.navigation_timing === "object"
      ? profile.navigation_timing : {};
    if (!Object.keys(source).length) return null;
    return makeEntry({
      name: typeof source.name === "string" ? source.name : "",
      entryType: "navigation",
      startTime: 0,
      duration: source.duration,
      type: source.type,
      domInteractive: source.domInteractive,
      domContentLoadedEventEnd: source.domContentLoadedEventEnd,
      loadEventEnd: source.loadEventEnd,
      unloadEventStart: source.unloadEventStart,
      unloadEventEnd: source.unloadEventEnd,
      fetchStart: source.fetchStart,
      responseStart: source.responseStart,
      responseEnd: source.responseEnd,
    }, "navigation");
  }

  function profileEntries() {
    const output = [];
    if (Array.isArray(profile.entries)) {
      for (const value of profile.entries) output.push(makeEntry(value, value && value.entryType || "resource"));
    } else {
      const navigation = navigationEntry();
      if (navigation) output.push(navigation);
      const resources = Array.isArray(profile.resources) ? profile.resources : [];
      const count = finite(profile.resource_count) ? Math.max(0, Math.floor(profile.resource_count)) : resources.length;
      for (let index = 0; index < count; index += 1) {
        output.push(makeEntry(resources[index] || {
          name: "",
          entryType: "resource",
          startTime: index * 0.001,
          duration: 0,
        }, "resource"));
      }
    }
    return output;
  }

  const profileEntriesOverride = hasProfile && (
    Array.isArray(profile.entries) || own(profile, "navigation_timing") ||
    own(profile, "resource_count") || Array.isArray(profile.resources)
  );
  if (profileEntriesOverride) {
    syntheticEntries.push(...profileEntries());
    const controlledEntryTypes = new Set();
    if (own(profile, "navigation_timing")) controlledEntryTypes.add("navigation");
    if (own(profile, "resource_count") || Array.isArray(profile.resources)) controlledEntryTypes.add("resource");
    for (const entry of syntheticEntries) {
      const record = entryRecords.get(entry);
      if (record) controlledEntryTypes.add(record.entryType);
    }
    const nativeEntries = {
      getEntries: descriptor(performancePrototype, "getEntries"),
      getEntriesByName: descriptor(performancePrototype, "getEntriesByName"),
      getEntriesByType: descriptor(performancePrototype, "getEntriesByType"),
      clearResourceTimings: descriptor(performancePrototype, "clearResourceTimings"),
      setResourceTimingBufferSize: descriptor(performancePrototype, "setResourceTimingBufferSize"),
    };
    installMethod("getEntries", function getEntries() {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      const native = nativeEntries.getEntries && typeof nativeEntries.getEntries.value.value === "function"
        ? Reflect.apply(nativeEntries.getEntries.value.value, this, []) : [];
      return syntheticEntries.concat(native.filter((entry) => !controlledEntryTypes.has(entry.entryType)));
    });
    installMethod("getEntriesByType", function getEntriesByType(type) {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      if (typeof type !== "string") throw new TypeError("The entry type must be a string");
      const matches = syntheticEntries.filter((entry) => {
        const record = entryRecords.get(entry);
        return record && record.entryType === type;
      });
      if (controlledEntryTypes.has(type)) return matches;
      return nativeEntries.getEntriesByType
        ? Reflect.apply(nativeEntries.getEntriesByType.value.value, this, [type]) : [];
    });
    installMethod("getEntriesByName", function getEntriesByName(name, type) {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      const matches = syntheticEntries.filter((entry) => {
        const record = entryRecords.get(entry);
        return record && record.name === name && (!type || record.entryType === type);
      });
      if (matches.length) return matches;
      return nativeEntries.getEntriesByName
        ? Reflect.apply(nativeEntries.getEntriesByName.value.value, this, [name, type]) : [];
    });
    installMethod("clearResourceTimings", function clearResourceTimings() {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      for (let index = syntheticEntries.length - 1; index >= 0; index -= 1) {
        if (entryRecords.get(syntheticEntries[index])?.entryType === "resource") syntheticEntries.splice(index, 1);
      }
      if (nativeEntries.clearResourceTimings && typeof nativeEntries.clearResourceTimings.value.value === "function") {
        return Reflect.apply(nativeEntries.clearResourceTimings.value.value, this, []);
      }
      return undefined;
    });
    installMethod("setResourceTimingBufferSize", function setResourceTimingBufferSize(size) {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      if (nativeEntries.setResourceTimingBufferSize && typeof nativeEntries.setResourceTimingBufferSize.value.value === "function") {
        return Reflect.apply(nativeEntries.setResourceTimingBufferSize.value.value, this, [size]);
      }
      return undefined;
    });
  }

  const hasSyntheticMarks = Array.isArray(profile.marks) || Array.isArray(profile.measures);
  if (hasProfile && hasSyntheticMarks) {
    const syntheticMarks = [];
    const syntheticMeasures = [];
    if (Array.isArray(profile.marks)) {
      for (const mark of profile.marks) syntheticMarks.push(makeEntry({ ...mark, entryType: "mark" }, "mark"));
    }
    if (Array.isArray(profile.measures)) {
      for (const measure of profile.measures) syntheticMeasures.push(makeEntry({ ...measure, entryType: "measure" }, "measure"));
    }
    const nativeMethods = {
      mark: descriptor(performancePrototype, "mark"),
      measure: descriptor(performancePrototype, "measure"),
      clearMarks: descriptor(performancePrototype, "clearMarks"),
      clearMeasures: descriptor(performancePrototype, "clearMeasures"),
    };
    installMethod("mark", function mark(name) {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      const entry = makeEntry({ name: String(name || ""), entryType: "mark", startTime: lastNow, duration: 0 }, "mark");
      syntheticMarks.push(entry);
      syntheticEntries.push(entry);
      return entry;
    });
    installMethod("measure", function measure(name) {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      const entry = makeEntry({ name: String(name || ""), entryType: "measure", startTime: 0, duration: lastNow }, "measure");
      syntheticMeasures.push(entry);
      syntheticEntries.push(entry);
      return entry;
    });
    installMethod("clearMarks", function clearMarks(name) {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      for (let index = syntheticMarks.length - 1; index >= 0; index -= 1) {
        if (name === undefined || entryRecords.get(syntheticMarks[index]).name === name) {
          const entry = syntheticMarks[index];
          syntheticMarks.splice(index, 1);
          const position = syntheticEntries.indexOf(entry);
          if (position >= 0) syntheticEntries.splice(position, 1);
        }
      }
    });
    installMethod("clearMeasures", function clearMeasures(name) {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      for (let index = syntheticMeasures.length - 1; index >= 0; index -= 1) {
        if (name === undefined || entryRecords.get(syntheticMeasures[index]).name === name) {
          const entry = syntheticMeasures[index];
          syntheticMeasures.splice(index, 1);
          const position = syntheticEntries.indexOf(entry);
          if (position >= 0) syntheticEntries.splice(position, 1);
        }
      }
    });
    // Keep native methods available if a profile did not provide a matching
    // synthetic collection; the wrappers above are intentionally no-op-safe.
    void nativeMethods;
  }

  try {
    Object.defineProperty(performancePrototype, marker, {
      value: Object.freeze({ version: "1.0.0", profile: hasProfile }),
      writable: false,
      enumerable: false,
      configurable: false,
    });
  } catch (_error) { /* hardened realms may refuse optional markers */ }
}());
