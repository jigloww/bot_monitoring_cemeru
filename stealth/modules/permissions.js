/*
 * Profile-aware Permissions API compatibility layer.
 *
 * The module keeps navigator.permissions on Navigator.prototype and query on
 * Permissions.prototype. Custom PermissionStatus values are created with the
 * browser's PermissionStatus.prototype, so instanceof and the native object
 * shape remain intact. No permission is actually granted or revoked.
 */
(function permissionsStealthModule() {
  "use strict";

  if (typeof navigator === "undefined" || typeof Navigator === "undefined") return;
  if (typeof Permissions === "undefined" || typeof PermissionStatus === "undefined") return;

  const marker = Symbol.for("cemeru.stealth.permissions.v1");
  const navigatorPrototype = Navigator.prototype;
  const permissionsPrototype = Permissions.prototype;
  const statusPrototype = PermissionStatus.prototype;
  if (navigatorPrototype[marker] || permissionsPrototype[marker]) return;

  const stealth = globalThis.__stealth && typeof globalThis.__stealth === "object"
    ? globalThis.__stealth : null;
  const profile = stealth && stealth.permissionsProfile &&
    typeof stealth.permissionsProfile === "object"
    ? stealth.permissionsProfile : {};

  const supported = [
    "notifications", "camera", "microphone", "clipboard-read", "clipboard-write",
    "geolocation", "persistent-storage", "midi", "background-sync", "accelerometer",
    "gyroscope", "magnetometer", "payment-handler",
  ];
  const canonicalNames = {
    notifications: "notifications",
    camera: "video_capture",
    microphone: "audio_capture",
    "clipboard-read": "clipboard_read",
    "clipboard-write": "clipboard_write",
    geolocation: "geolocation",
    "persistent-storage": "persistent_storage",
    midi: "midi",
    "background-sync": "background_sync",
    accelerometer: "accelerometer",
    gyroscope: "gyroscope",
    magnetometer: "magnetometer",
    "payment-handler": "payment_handler",
  };

  function descriptor(object, property) {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Object.getOwnPropertyDescriptor(owner, property);
      if (value) return { owner, value };
    }
    return null;
  }

  function own(object, property) {
    return Object.prototype.hasOwnProperty.call(object, property);
  }

  function objectValue(value) {
    return value && typeof value === "object" ? value : null;
  }

  function validState(value) {
    return value === "granted" || value === "denied" || value === "prompt";
  }

  // Reuse the intrinsic wrapper installed by the completed modules. This
  // avoids changing Function#toString output for functions outside this API.
  const toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
  const isState = (state) => state && state.sources &&
    typeof state.sources.set === "function" && typeof state.original === "function" &&
    typeof state.replacement === "function";
  const shared = isState(stealth && stealth.navigatorFunctionState)
    ? stealth.navigatorFunctionState
    : (isState(stealth && stealth.windowFunctionState)
      ? stealth.windowFunctionState
      : (isState(stealth && stealth.screenFunctionState)
        ? stealth.screenFunctionState
        : (isState(stealth && stealth.chromeFunctionState)
          ? stealth.chromeFunctionState : null)));
  const functionState = shared || (() => {
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
        Object.defineProperty(stealth, "permissionsFunctionState", {
          value: state, writable: false, enumerable: false, configurable: false,
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
  if (!functionState.sources.has(functionState.replacement)) {
    functionState.sources.set(functionState.replacement, "function toString() { [native code] }");
  }

  function nativeSource(value, fallback) {
    if (typeof value === "function") {
      try { return Reflect.apply(functionState.original, value, []); }
      catch (_error) { /* fallback below */ }
    }
    return fallback;
  }

  function callable(nativeFunction, implementation, name, fallbackSource) {
    const fallback = Object.getOwnPropertyDescriptor(Object.prototype, "__proto__").get;
    const target = typeof nativeFunction === "function" ? nativeFunction : fallback;
    const result = new Proxy(target, {
      apply(_target, thisArg, args) {
        return Reflect.apply(implementation, thisArg, args);
      },
    });
    if (typeof nativeFunction !== "function") {
      try {
        Object.defineProperty(result, "name", {
          value: name, writable: false, enumerable: false, configurable: true,
        });
      } catch (_error) { /* optional metadata */ }
    }
    functionState.sources.set(
      result,
      nativeSource(nativeFunction, fallbackSource || `function ${name}() { [native code] }`),
    );
    return result;
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

  const permissionsDescriptor = descriptor(navigator, "permissions");
  const nativePermissionsGetter = permissionsDescriptor && permissionsDescriptor.value.get;
  let nativePermissions = null;
  try {
    nativePermissions = nativePermissionsGetter
      ? Reflect.apply(nativePermissionsGetter, navigator, []) : navigator.permissions;
  } catch (_error) { nativePermissions = null; }
  const permissionsObject = nativePermissions || Object.create(Permissions.prototype);
  const queryDescriptor = descriptor(permissionsObject, "query");
  const nativeQuery = queryDescriptor && queryDescriptor.value.value;
  const statusRecords = new WeakMap();

  function profileEntry(requested) {
    const states = objectValue(profile.states);
    const aliases = [requested, canonicalNames[requested]];
    for (const key of aliases) {
      const value = (states && own(states, key)) ? states[key] : (own(profile, key) ? profile[key] : undefined);
      if (value === undefined) continue;
      if (typeof value === "string" && validState(value)) return { state: value };
      if (value && typeof value === "object" && validState(value.state)) {
        return {
          state: value.state,
          name: typeof value.name === "string" ? value.name : undefined,
          onchange: typeof value.onchange === "function" ? value.onchange : null,
        };
      }
    }
    if (typeof profile.default === "string" && validState(profile.default)) {
      return { state: profile.default };
    }
    return null;
  }

  function createStatus(requested, entry) {
    const status = Object.create(statusPrototype);
    statusRecords.set(status, {
      state: entry.state,
      name: entry.name || canonicalNames[requested],
      onchange: entry.onchange || null,
    });
    return status;
  }

  function installStatusProperty(property, implementation, original) {
    if (!original || typeof original.get !== "function") return false;
    if (original.configurable === false) return false;
    const getter = callable(
      original.get,
      implementation,
      original.get.name || `get ${property}`,
      `function get ${property}() { [native code] }`,
    );
    let setter = original.set;
    if (typeof original.set === "function") {
      setter = callable(
        original.set,
        function setPermissionStatus(value) {
          const record = statusRecords.get(this);
          if (record) {
            record.onchange = value == null || typeof value === "function" ? value : null;
            return undefined;
          }
          return Reflect.apply(original.set, this, [value]);
        },
        original.set.name || `set ${property}`,
        `function set ${property}() { [native code] }`,
      );
    }
    return Reflect.defineProperty(statusPrototype, property, {
      get: getter,
      set: setter,
      enumerable: original.enumerable,
      configurable: original.configurable,
    });
  }

  const statusState = descriptor(statusPrototype, "state");
  const statusName = descriptor(statusPrototype, "name");
  const statusOnchange = descriptor(statusPrototype, "onchange");
  installStatusProperty("state", function getState() {
    const record = statusRecords.get(this);
    if (record) return record.state;
    try { return Reflect.apply(statusState.value.get, this, []); }
    catch (_error) { return "prompt"; }
  }, statusState && statusState.value);
  installStatusProperty("name", function getName() {
    const record = statusRecords.get(this);
    if (record) return record.name;
    try { return Reflect.apply(statusName.value.get, this, []); }
    catch (_error) { return undefined; }
  }, statusName && statusName.value);
  installStatusProperty("onchange", function getOnchange() {
    const record = statusRecords.get(this);
    if (record) return record.onchange;
    try { return Reflect.apply(statusOnchange.value.get, this, []); }
    catch (_error) { return null; }
  }, statusOnchange && statusOnchange.value);

  function queryImplementation(descriptorValue) {
    if (this !== permissionsObject && !(this instanceof Permissions)) {
      throw new TypeError("Illegal invocation");
    }
    const requested = descriptorValue && typeof descriptorValue === "object"
      ? descriptorValue.name : undefined;
    if (typeof requested !== "string" || !supported.includes(requested)) {
      return Promise.reject(new TypeError(
        "Failed to execute 'query' on 'Permissions': The provided value is not a valid PermissionName.",
      ));
    }
    const entry = profileEntry(requested);
    if (entry) return Promise.resolve(createStatus(requested, entry));
    if (typeof nativeQuery === "function") {
      try { return Reflect.apply(nativeQuery, this, [descriptorValue]); }
      catch (error) { return Promise.reject(error); }
    }
    return Promise.resolve(createStatus(requested, { state: "prompt" }));
  }

  if (queryDescriptor && queryDescriptor.value.configurable !== false &&
      typeof queryDescriptor.value.value === "function") {
    const query = callable(
      nativeQuery,
      queryImplementation,
      nativeQuery.name || "query",
      "function query() { [native code] }",
    );
    Reflect.defineProperty(queryDescriptor.owner, "query", {
      value: query,
      writable: queryDescriptor.value.writable,
      enumerable: queryDescriptor.value.enumerable,
      configurable: queryDescriptor.value.configurable,
    });
  }

  if (permissionsDescriptor && permissionsDescriptor.value.configurable !== false &&
      typeof permissionsDescriptor.value.get === "function") {
    const getter = callable(
      nativePermissionsGetter,
      function getPermissions() { return permissionsObject; },
      nativePermissionsGetter.name || "get permissions",
      "function get permissions() { [native code] }",
    );
    Reflect.defineProperty(permissionsDescriptor.owner, "permissions", {
      get: getter,
      set: permissionsDescriptor.value.set,
      enumerable: permissionsDescriptor.value.enumerable,
      configurable: permissionsDescriptor.value.configurable,
    });
  }

  Object.defineProperty(navigatorPrototype, marker, {
    value: Object.freeze({ version: "1.0.0", profile: Object.keys(profile).length > 0 }),
    writable: false,
    enumerable: false,
    configurable: false,
  });
}());
