/*
 * Evidence-driven PluginArray / MimeTypeArray adapter.
 *
 * The only value-level mismatch identified by Experiments 039/040 was the
 * empty Playwright PluginArray.  This module therefore wraps the native
 * Navigator.prototype accessors only when an embedding profile explicitly
 * supplies plugin data.  Native prototypes, constructors, descriptors and
 * internal slots remain the targets of the proxies; no constructors are
 * replaced and no browser/network API is touched.
 */
(function pluginsStealthModule() {
  "use strict";

  if (typeof Navigator === "undefined" || typeof navigator === "undefined") return;

  const stealth = globalThis.__stealth;
  const profile = stealth && typeof stealth === "object" && stealth.pluginsProfile &&
    typeof stealth.pluginsProfile === "object" ? stealth.pluginsProfile : null;
  if (!profile || Object.keys(profile).length === 0) return;
  if (!Object.prototype.hasOwnProperty.call(profile, "plugins") &&
      !Object.prototype.hasOwnProperty.call(profile, "mimeTypes") &&
      !Object.prototype.hasOwnProperty.call(profile, "mime_types")) return;

  const marker = Symbol.for("cemeru.stealth.plugins.v1");
  const navigatorPrototype = Navigator.prototype;
  if (navigatorPrototype[marker]) return;

  function findDescriptor(object, property) {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Reflect.getOwnPropertyDescriptor(owner, property);
      if (value) return { owner, value };
    }
    return null;
  }

  function nativeValue(property) {
    const found = findDescriptor(navigator, property);
    try {
      if (found && found.value && typeof found.value.get === "function") {
        return Reflect.apply(found.value.get, navigator, []);
      }
      return Reflect.get(navigator, property);
    } catch (_error) {
      return undefined;
    }
  }

  const nativePlugins = nativeValue("plugins");
  const nativeMimeTypes = nativeValue("mimeTypes");
  if (!nativePlugins || !nativeMimeTypes) return;

  const pluginsPrototype = Reflect.getPrototypeOf(nativePlugins);
  const mimeTypesPrototype = Reflect.getPrototypeOf(nativeMimeTypes);
  if (!pluginsPrototype || !mimeTypesPrototype) return;

  // Reuse Navigator's intrinsic masking state when the full stack is loaded.
  // Standalone use creates one private state and stores it non-enumerably on
  // the existing __stealth namespace.
  const toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
  const sharedState = stealth.navigatorFunctionState;
  const functionState = sharedState && sharedState.sources &&
      typeof sharedState.sources.set === "function" &&
      typeof sharedState.original === "function" &&
      typeof sharedState.replacement === "function"
    ? sharedState
    : (() => {
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
      try {
        Object.defineProperty(stealth, "pluginsFunctionState", {
          value: state,
          writable: false,
          enumerable: false,
          configurable: false,
        });
      } catch (_error) { /* an earlier initializer may own the state */ }
      return state;
    })();
  if (!functionState) return;

  if (toStringDescriptor && toStringDescriptor.configurable &&
      toStringDescriptor.value !== functionState.replacement) {
    try {
      Object.defineProperty(Function.prototype, "toString", {
        value: functionState.replacement,
        writable: toStringDescriptor.writable,
        enumerable: toStringDescriptor.enumerable,
        configurable: toStringDescriptor.configurable,
      });
    } catch (_error) { /* hardened realms may reject optional masking */ }
  }

  function nativeSource(value, fallbackName) {
    if (typeof value === "function") {
      try { return Reflect.apply(functionState.original, value, []); } catch (_error) { /* fallback */ }
    }
    return `function ${fallbackName}() { [native code] }`;
  }

  if (!functionState.sources.has(functionState.replacement)) {
    functionState.sources.set(functionState.replacement, nativeSource(functionState.original, "toString"));
  }

  function callable(nativeFunction, implementation, fallbackName) {
    const target = typeof nativeFunction === "function"
      ? nativeFunction
      : function nativeFallback() {};
    const result = new Proxy(target, {
      apply(_target, thisArg, args) {
        return implementation(thisArg, args);
      },
    });
    functionState.sources.set(result, nativeSource(nativeFunction, fallbackName));
    return result;
  }

  function hasOwn(object, property) {
    return Object.prototype.hasOwnProperty.call(object, property);
  }

  function asString(value, fallback) {
    return typeof value === "string" ? value : fallback;
  }

  function uniqueStrings(values) {
    const result = [];
    const seen = new Set();
    for (const value of Array.isArray(values) ? values : []) {
      const item = String(value || "");
      if (item && !seen.has(item)) {
        seen.add(item);
        result.push(item);
      }
    }
    return result;
  }

  function normaliseMime(value) {
    if (typeof value === "string") return { type: value, suffixes: "", description: "" };
    if (!value || typeof value !== "object") return null;
    const type = asString(value.type, "");
    if (!type) return null;
    return Object.freeze({
      type,
      suffixes: asString(value.suffixes, ""),
      description: asString(value.description, ""),
      enabledPlugin: asString(value.enabledPlugin || value.enabledPluginName, ""),
    });
  }

  function nativePluginRecord(value, index) {
    if (!value) return null;
    const mimeTypes = [];
    try {
      for (let position = 0; position < Number(value.length || 0); position += 1) {
        const mime = value[position];
        if (mime && mime.type) {
          mimeTypes.push({
            type: String(mime.type),
            suffixes: String(mime.suffixes || ""),
            description: String(mime.description || ""),
          });
        }
      }
    } catch (_error) { /* native object may expose no readable entries */ }
    return {
      name: String(value.name || `Plugin ${index}`),
      filename: String(value.filename || ""),
      description: String(value.description || ""),
      mimeTypes,
    };
  }

  function profilePluginRecord(value, index) {
    const source = value && typeof value === "object" ? value : {};
    const native = nativePluginRecord(nativePlugins[index % Math.max(nativePlugins.length, 1)], index) || {
      name: `Plugin ${index}`, filename: "", description: "", mimeTypes: [],
    };
    const configuredMimeTypes = hasOwn(source, "mimeTypes") ? source.mimeTypes : (hasOwn(source, "mime_types") ? source.mime_types : native.mimeTypes);
    const mimeTypes = [];
    for (const item of Array.isArray(configuredMimeTypes) ? configuredMimeTypes : []) {
      const normalised = normaliseMime(item);
      if (normalised && !mimeTypes.some((existing) => existing.type === normalised.type)) mimeTypes.push(normalised);
    }
    return Object.freeze({
      name: asString(source.name, native.name),
      filename: asString(source.filename, native.filename),
      description: asString(source.description, native.description),
      mimeTypes: Object.freeze(mimeTypes),
    });
  }

  function nativeMimeRecord(value) {
    if (!value) return null;
    return {
      type: String(value.type || ""),
      suffixes: String(value.suffixes || ""),
      description: String(value.description || ""),
      enabledPlugin: value.enabledPlugin && String(value.enabledPlugin.name || ""),
    };
  }

  const configuredPlugins = hasOwn(profile, "plugins") && Array.isArray(profile.plugins)
    ? profile.plugins : null;
  const pluginRecords = Object.freeze((configuredPlugins || Array.from({ length: nativePlugins.length }, (_v, index) => nativePluginRecord(nativePlugins[index], index)))
    .map((value, index) => profilePluginRecord(value, index)));

  const profileMimeTypeList = hasOwn(profile, "mimeTypes") ? profile.mimeTypes : profile.mime_types;
  const configuredMimeTypes = Array.isArray(profileMimeTypeList)
    ? profileMimeTypeList.map(normaliseMime).filter(Boolean) : null;
  const mimeRecordsByType = new Map();
  const mimeRecords = [];
  function addMimeRecord(value, fallbackPlugin) {
    if (!value || !value.type || mimeRecordsByType.has(value.type)) return;
    const record = Object.freeze({
      type: value.type,
      suffixes: value.suffixes || "",
      description: value.description || "",
      enabledPlugin: value.enabledPlugin || fallbackPlugin || "",
    });
    mimeRecordsByType.set(record.type, record);
    mimeRecords.push(record);
  }
  if (configuredMimeTypes) {
    configuredMimeTypes.forEach((value) => addMimeRecord(value, ""));
  } else {
    for (const plugin of pluginRecords) {
      for (const mime of plugin.mimeTypes) addMimeRecord(mime, plugin.name);
    }
    if (!pluginRecords.length) {
      for (let index = 0; index < nativeMimeTypes.length; index += 1) {
        addMimeRecord(nativeMimeRecord(nativeMimeTypes[index]), "");
      }
    }
  }
  // Complete the profile's relationship graph from Plugin.mimeTypes, while
  // retaining an explicitly configured enabledPlugin name when supplied.
  for (const plugin of pluginRecords) {
    for (const mime of plugin.mimeTypes) {
      const existing = mimeRecordsByType.get(mime.type);
      if (!existing) addMimeRecord(mime, plugin.name);
    }
  }
  const orderedMimeRecords = Object.freeze(mimeRecords.slice());
  const effectivePluginRecords = Object.freeze(pluginRecords.map((plugin) => {
    const attached = plugin.mimeTypes.slice();
    for (const mime of orderedMimeRecords) {
      const targetName = mime.enabledPlugin || (pluginRecords[0] && pluginRecords[0].name) || "";
      if (targetName === plugin.name && !attached.some((entry) => entry.type === mime.type)) {
        attached.push(Object.freeze({ type: mime.type, suffixes: mime.suffixes, description: mime.description }));
      }
    }
    return Object.freeze({
      name: plugin.name,
      filename: plugin.filename,
      description: plugin.description,
      mimeTypes: Object.freeze(attached),
    });
  }));

  const pluginProxies = [];
  const mimeProxies = [];
  const pluginProxySet = new WeakSet();
  const mimeProxySet = new WeakSet();
  const pluginStates = new WeakMap();
  const pluginArrayStates = new WeakMap();
  const mimeArrayStates = new WeakMap();
  const pluginTemplateCount = Math.max(Number(nativePlugins.length || 0), 1);
  const mimeTemplateCount = Math.max(Number(nativeMimeTypes.length || 0), 1);

  function receiverIs(receiver, set, ctor) {
    if (set.has(receiver)) return true;
    try { return !!(ctor && receiver instanceof ctor); } catch (_error) { return false; }
  }

  function descriptorFor(target, property) {
    try { return Reflect.getOwnPropertyDescriptor(target, property); } catch (_error) { return undefined; }
  }

  function virtualDescriptor(value, enumerable) {
    return { value, writable: false, enumerable: enumerable !== false, configurable: true };
  }

  function pluginForName(name) {
    const index = effectivePluginRecords.findIndex((value) => value.name === name);
    return index >= 0 ? pluginProxies[index] : null;
  }

  function mimeForType(type) {
    const index = orderedMimeRecords.findIndex((value) => value.type === type);
    return index >= 0 ? mimeProxies[index] : null;
  }

  function makeMimeProxy(record, index) {
    // Playwright's empty MimeTypeArray has no item to use as a Proxy target.
    // Build a slot-free object with the native MimeType prototype instead of
    // falling back to MimeTypeArray.prototype (which leaks array methods and
    // produces the wrong constructor/source surface).
    const nativeTemplate = nativeMimeTypes[index % mimeTemplateCount];
    const mimePrototype = typeof MimeType === "function"
      ? MimeType.prototype
      : Reflect.getPrototypeOf(nativeMimeTypes);
    const target = nativeTemplate || Object.create(mimePrototype);
    const proxy = new Proxy(target, {
      get(inner, property, receiver) {
        if (property === "type") return record.type;
        if (property === "suffixes") return record.suffixes;
        if (property === "description") return record.description;
        if (property === "enabledPlugin") return pluginForName(record.enabledPlugin) || pluginProxies[0] || null;
        return Reflect.get(inner, property, receiver);
      },
      has(inner, property) {
        if (["type", "suffixes", "description", "enabledPlugin"].includes(property)) return true;
        return Reflect.has(inner, property);
      },
      set(inner, property, value, receiver) {
        if (["type", "suffixes", "description", "enabledPlugin"].includes(property)) return false;
        return Reflect.set(inner, property, value, receiver);
      },
    });
    mimeProxySet.add(proxy);
    // MimeType has no callable instance methods, but keeping the native
    // internal-slot target here lets enabledPlugin and instanceof remain
    // browser-native operations.
    return proxy;
  }

  function makePluginProxy(record, index) {
    // When the native PluginArray is empty, use a native Plugin prototype
    // target.  Using PluginArray.prototype here makes every synthetic plugin
    // look like an array and exposes refresh/array methods in the fingerprint.
    const nativeTemplate = nativePlugins[index % pluginTemplateCount];
    const pluginPrototype = typeof Plugin === "function"
      ? Plugin.prototype
      : Reflect.getPrototypeOf(nativePlugins);
    const target = nativeTemplate || Object.create(pluginPrototype);
    const methodCache = new Map();
    const profileMimeTypes = record.mimeTypes;
    const proxy = new Proxy(target, {
      get(inner, property, receiver) {
        if (property === "name") return record.name;
        if (property === "filename") return record.filename;
        if (property === "description") return record.description;
        if (property === "length") return profileMimeTypes.length;
        if (typeof property === "string") {
          if (/^\d+$/.test(property)) {
            const mime = profileMimeTypes[Number(property)];
            return mime ? mimeForType(mime.type) : undefined;
          }
          const mime = mimeForType(property);
          if (mime) return mime;
        }
        if (property === "item" || property === "namedItem") {
          if (!methodCache.has(property)) {
            const nativeFunction = Reflect.get(inner, property, inner);
            methodCache.set(property, callable(nativeFunction, (thisArg, args) => {
              if (!receiverIs(thisArg, pluginProxySet, typeof Plugin === "function" ? Plugin : null)) throw new TypeError("Illegal invocation");
              if (property === "item") return profileMimeTypes[Number(args[0])] ? mimeForType(profileMimeTypes[Number(args[0])].type) : null;
              const value = String(args[0] || "");
              return mimeForType(value);
            }, property));
          }
          return methodCache.get(property);
        }
        return Reflect.get(inner, property, receiver);
      },
      has(inner, property) {
        if (["name", "filename", "description", "length", "item", "namedItem"].includes(property)) return true;
        if (typeof property === "string" && (profileMimeTypes.some((mime) => mime.type === property) || /^\d+$/.test(property))) return true;
        return Reflect.has(inner, property);
      },
      ownKeys(inner) {
        const keys = Reflect.ownKeys(inner).filter((key) => {
          if (typeof key !== "string") return true;
          const descriptor = descriptorFor(inner, key);
          return descriptor && descriptor.configurable === false;
        });
        const additions = [];
        for (let position = 0; position < profileMimeTypes.length; position += 1) additions.push(String(position));
        for (const mime of profileMimeTypes) additions.push(mime.type);
        return [...new Set([...keys, ...additions])];
      },
      getOwnPropertyDescriptor(inner, property) {
        const nativeDescriptor = descriptorFor(inner, property);
        if (nativeDescriptor && (typeof property !== "string" || nativeDescriptor.configurable === false)) return nativeDescriptor;
        if (typeof property === "string" && /^\d+$/.test(property)) {
          const mime = profileMimeTypes[Number(property)];
          if (mime) return virtualDescriptor(mimeForType(mime.type), true);
        }
        if (typeof property === "string" && profileMimeTypes.some((mime) => mime.type === property)) {
          return virtualDescriptor(mimeForType(property), false);
        }
        return undefined;
      },
      set(inner, property, value, receiver) {
        if (property === "name" || property === "filename" || property === "description" || property === "length" || typeof property === "string" && (profileMimeTypes.some((mime) => mime.type === property) || /^\d+$/.test(property))) return false;
        return Reflect.set(inner, property, value, receiver);
      },
    });
    pluginProxySet.add(proxy);
    pluginStates.set(proxy, { record, proxy });
    return proxy;
  }

  // Construct in two passes so MimeType.enabledPlugin can return the exact
  // Plugin proxy object exposed by the corresponding PluginArray.
  pluginProxies.length = 0;
  for (let index = 0; index < effectivePluginRecords.length; index += 1) pluginProxies.push(makePluginProxy(effectivePluginRecords[index], index));
  for (let index = 0; index < orderedMimeRecords.length; index += 1) mimeProxies.push(null);
  for (let index = 0; index < orderedMimeRecords.length; index += 1) mimeProxies[index] = makeMimeProxy(orderedMimeRecords[index], index);

  function arrayProxy(nativeArray, records, proxies, ctor, methods) {
    const methodCache = new Map();
    let proxy;
    function validReceiver(receiver) {
      return receiver === proxy || receiverIs(receiver, new WeakSet(), ctor);
    }
    proxy = new Proxy(nativeArray, {
      get(inner, property, receiver) {
        if (property === "length") return records.length;
        if (typeof property === "string") {
          if (/^\d+$/.test(property)) return proxies[Number(property)];
          const index = records.findIndex((value) => value.name === property || value.type === property);
          if (index >= 0) return proxies[index];
        }
        if (methods.includes(property)) {
          if (!methodCache.has(property)) {
            const nativeFunction = Reflect.get(inner, property, inner);
            methodCache.set(property, callable(nativeFunction, (thisArg, args) => {
              if (!validReceiver(thisArg)) throw new TypeError("Illegal invocation");
              if (property === "item") return proxies[Number(args[0])] || null;
              if (property === "namedItem") {
                const value = String(args[0] || "");
                const index = records.findIndex((entry) => entry.name === value || entry.type === value);
                return index >= 0 ? proxies[index] : null;
              }
              if (property === "refresh") return undefined;
              if (property === Symbol.iterator) return proxies.values();
              return Reflect.apply(nativeFunction, nativeArray, args);
            }, typeof property === "symbol" ? "values" : String(property)));
          }
          return methodCache.get(property);
        }
        return Reflect.get(inner, property, receiver);
      },
      has(inner, property) {
        if (property === "length" || methods.includes(property)) return true;
        if (typeof property === "string" && (/^\d+$/.test(property) || records.some((value) => value.name === property || value.type === property))) return true;
        return Reflect.has(inner, property);
      },
      ownKeys(inner) {
        const keys = Reflect.ownKeys(inner).filter((key) => {
          if (typeof key !== "string") return true;
          const descriptor = descriptorFor(inner, key);
          return descriptor && descriptor.configurable === false;
        });
        const additions = [];
        for (let index = 0; index < records.length; index += 1) additions.push(String(index));
        for (const record of records) {
          if (record.name) additions.push(record.name);
          if (record.type) additions.push(record.type);
        }
        return [...new Set([...keys, ...additions])];
      },
      getOwnPropertyDescriptor(inner, property) {
        const nativeDescriptor = descriptorFor(inner, property);
        if (nativeDescriptor && (typeof property !== "string" || nativeDescriptor.configurable === false)) return nativeDescriptor;
        if (typeof property === "string") {
          if (/^\d+$/.test(property) && proxies[Number(property)]) return virtualDescriptor(proxies[Number(property)], true);
          const index = records.findIndex((value) => value.name === property || value.type === property);
          if (index >= 0) return virtualDescriptor(proxies[index], false);
        }
        return undefined;
      },
      set(inner, property, value, receiver) {
        if (property === "length" || typeof property === "string" && (/^\d+$/.test(property) || records.some((entry) => entry.name === property || entry.type === property))) return false;
        return Reflect.set(inner, property, value, receiver);
      },
    });
    if (records === effectivePluginRecords) {
      pluginArrayStates.set(proxy, { records, proxies });
    } else {
      mimeArrayStates.set(proxy, { records, proxies });
    }
    return proxy;
  }

  const pluginArrayProxy = arrayProxy(nativePlugins, effectivePluginRecords, pluginProxies, typeof PluginArray === "function" ? PluginArray : null, ["item", "namedItem", "refresh", Symbol.iterator]);
  const mimeArrayProxy = arrayProxy(nativeMimeTypes, orderedMimeRecords, mimeProxies, typeof MimeTypeArray === "function" ? MimeTypeArray : null, ["item", "namedItem", Symbol.iterator]);

  function patchPrototypeMethod(prototype, property, stateMap, kind) {
    if (!prototype) return;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, property);
    if (!descriptor || typeof descriptor.value !== "function" || descriptor.configurable === false) return;
    const original = descriptor.value;
    const wrapper = callable(original, (receiver, args) => {
      const state = stateMap.get(receiver);
      if (!state) return Reflect.apply(original, receiver, args);
      if (property === "item") return state.proxies[Number(args[0])] || null;
      if (property === "namedItem") {
        const value = String(args[0] || "");
        const index = state.records.findIndex((entry) => entry.name === value || entry.type === value);
        return index >= 0 ? state.proxies[index] : null;
      }
      if (property === "refresh") return undefined;
      if (property === Symbol.iterator) return state.proxies.values();
      return Reflect.apply(original, receiver, args);
    }, typeof property === "symbol" ? "values" : String(property));
    try {
      Object.defineProperty(prototype, property, { ...descriptor, value: wrapper });
    } catch (_error) { /* a hardened prototype may reject optional wrappers */ }
  }

  function patchPluginMethod(prototype, property) {
    if (!prototype) return;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, property);
    if (!descriptor || typeof descriptor.value !== "function" || descriptor.configurable === false) return;
    const original = descriptor.value;
    const wrapper = callable(original, (receiver, args) => {
      const state = pluginStates.get(receiver);
      if (!state) return Reflect.apply(original, receiver, args);
      if (property === "item") return state.record.mimeTypes[Number(args[0])] ? mimeForType(state.record.mimeTypes[Number(args[0])].type) : null;
      if (property === "namedItem") return mimeForType(String(args[0] || ""));
      return Reflect.apply(original, receiver, args);
    }, String(property));
    try {
      Object.defineProperty(prototype, property, { ...descriptor, value: wrapper });
    } catch (_error) { /* optional */ }
  }

  function installGetter(property, value) {
    const found = findDescriptor(navigator, property);
    if (!found || !found.value || typeof found.value.get !== "function" || found.value.configurable === false) return false;
    const original = found.value;
    const getter = callable(original.get, (receiver) => {
      if (receiver !== navigator && !(receiver instanceof Navigator)) throw new TypeError("Illegal invocation");
      return value;
    }, original.get.name || `get ${property}`);
    return Reflect.defineProperty(found.owner, property, {
      get: getter,
      set: original.set,
      enumerable: original.enumerable,
      configurable: original.configurable,
    });
  }

  const pluginsDescriptor = findDescriptor(navigator, "plugins");
  const mimeTypesDescriptor = findDescriptor(navigator, "mimeTypes");
  if (!pluginsDescriptor || !mimeTypesDescriptor ||
      !pluginsDescriptor.value || !mimeTypesDescriptor.value ||
      typeof pluginsDescriptor.value.get !== "function" ||
      typeof mimeTypesDescriptor.value.get !== "function" ||
      pluginsDescriptor.value.configurable === false ||
      mimeTypesDescriptor.value.configurable === false) return;
  if (!installGetter("plugins", pluginArrayProxy)) return;
  if (!installGetter("mimeTypes", mimeArrayProxy)) return;

  patchPrototypeMethod(pluginsPrototype, "item", pluginArrayStates, "plugins");
  patchPrototypeMethod(pluginsPrototype, "namedItem", pluginArrayStates, "plugins");
  patchPrototypeMethod(pluginsPrototype, "refresh", pluginArrayStates, "plugins");
  patchPrototypeMethod(pluginsPrototype, Symbol.iterator, pluginArrayStates, "plugins");
  patchPrototypeMethod(mimeTypesPrototype, "item", mimeArrayStates, "mimeTypes");
  patchPrototypeMethod(mimeTypesPrototype, "namedItem", mimeArrayStates, "mimeTypes");
  patchPrototypeMethod(mimeTypesPrototype, Symbol.iterator, mimeArrayStates, "mimeTypes");
  patchPluginMethod(typeof Plugin !== "undefined" ? Plugin.prototype : null, "item");
  patchPluginMethod(typeof Plugin !== "undefined" ? Plugin.prototype : null, "namedItem");

  try {
    Object.defineProperty(navigatorPrototype, marker, {
      value: true,
      writable: false,
      enumerable: false,
      configurable: false,
    });
  } catch (_error) { /* marker is an idempotence optimization only */ }
})();
