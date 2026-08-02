/*
 * Chrome desktop compatibility surface.
 *
 * Chromium exposes a small, legacy window.chrome object even when no
 * extension is installed.  This module recreates that surface when the
 * runtime does not provide it, while preserving a native object whenever one
 * already exists.  It intentionally does not implement extension transport;
 * runtime methods are safe no-ops with the same callable shape as Chrome.
 */
(function chromeStealthModule() {
  "use strict";

  if (typeof window === "undefined") return;

  const marker = Symbol.for("cemeru.stealth.chrome.v1");
  const stealth = globalThis.__stealth && typeof globalThis.__stealth === "object"
    ? globalThis.__stealth : null;
  const profile = stealth && stealth.chromeProfile &&
    typeof stealth.chromeProfile === "object" ? stealth.chromeProfile : {};
  const hasProfile = Object.keys(profile).length > 0;

  function ownDescriptor(object, property) {
    try { return Object.getOwnPropertyDescriptor(object, property) || null; }
    catch (_error) { return null; }
  }

  function own(object, property) {
    return Object.prototype.hasOwnProperty.call(object, property);
  }

  function objectValue(value) {
    return value && typeof value === "object" ? value : null;
  }

  function finite(value, fallback) {
    return typeof value === "number" && Number.isFinite(value) ? value : fallback;
  }

  function boolean(value, fallback) {
    return typeof value === "boolean" ? value : fallback;
  }

  function string(value, fallback) {
    return typeof value === "string" ? value : fallback;
  }

  function sourceOf(value, fallback) {
    if (typeof value === "function") {
      try { return Reflect.apply(functionState.original, value, []); }
      catch (_error) { /* use fallback */ }
    }
    return fallback;
  }

  // Share the intrinsic wrapper installed by Navigator/Window/Screen. This
  // keeps every module's Proxy callable native-looking without replacing the
  // original Function#toString behavior for unrelated functions.
  const toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
  const validState = (state) => state && state.sources &&
    typeof state.sources.set === "function" && typeof state.original === "function" &&
    typeof state.replacement === "function";
  const shared = validState(stealth && stealth.navigatorFunctionState)
    ? stealth.navigatorFunctionState
    : (validState(stealth && stealth.windowFunctionState)
      ? stealth.windowFunctionState
      : (validState(stealth && stealth.screenFunctionState)
        ? stealth.screenFunctionState : null));
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
        Object.defineProperty(stealth, "chromeFunctionState", {
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
    functionState.sources.set(
      functionState.replacement,
      sourceOf(functionState.original, "function toString() { [native code] }"),
    );
  }

  function callable(nativeFunction, implementation, fallbackName, fallbackSource) {
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
          value: fallbackName, writable: false, enumerable: false, configurable: true,
        });
      } catch (_error) { /* optional metadata */ }
    }
    functionState.sources.set(
      result,
      sourceOf(nativeFunction, fallbackSource || `function ${fallbackName}() { [native code] }`),
    );
    return result;
  }

  function defineData(object, property, value, descriptor = {}) {
    const current = ownDescriptor(object, property);
    const next = {
      value,
      writable: descriptor.writable !== false,
      enumerable: descriptor.enumerable !== false,
      configurable: descriptor.configurable !== false,
    };
    try {
      Object.defineProperty(object, property, next);
      return true;
    } catch (_error) {
      try {
        if (!current || current.writable) object[property] = value;
      } catch (_ignored) { /* native non-writable properties stay untouched */ }
      return false;
    }
  }

  function defineAccessor(object, property, getter, original) {
    try {
      Object.defineProperty(object, property, {
        get: getter,
        set: original && original.set,
        enumerable: original ? original.enumerable : true,
        configurable: original ? original.configurable : true,
      });
      return true;
    } catch (_error) { return false; }
  }

  function cloneObject(value) {
    if (!value || (typeof value !== "object" && typeof value !== "function")) {
      return Object.create(Object.prototype);
    }
    const result = Object.create(Reflect.getPrototypeOf(value) || Object.prototype);
    for (const property of Reflect.ownKeys(value)) {
      if (property === marker) continue;
      const descriptor = ownDescriptor(value, property);
      if (!descriptor) continue;
      try { Object.defineProperty(result, property, descriptor); } catch (_error) { /* best effort */ }
    }
    return result;
  }

  function profileSection(name) {
    return objectValue(profile[name]);
  }

  function present(section, fallback) {
    return section && typeof section.present === "boolean" ? section.present : fallback;
  }

  function removeProperty(object, property) {
    const descriptor = ownDescriptor(object, property);
    if (descriptor && descriptor.configurable) {
      try { delete object[property]; } catch (_error) { /* native shape wins */ }
    }
  }

  const nativeChrome = window.chrome &&
    (typeof window.chrome === "object" || typeof window.chrome === "function")
    ? window.chrome : null;
  if (nativeChrome && nativeChrome[marker]) return;
  if (!nativeChrome && profile.present === false) return;

  const chrome = nativeChrome && hasProfile ? cloneObject(nativeChrome)
    : (nativeChrome || Object.create(Object.prototype));
  if (nativeChrome && !hasProfile) {
    // A real Chrome object is already the least surprising implementation.
    try {
      Object.defineProperty(nativeChrome, marker, {
        value: Object.freeze({ version: "1.0.0", native: true }),
        writable: false, enumerable: false, configurable: false,
      });
    } catch (_error) { /* frozen native object */ }
    return;
  }

  const nativeLoadTimes = nativeChrome && typeof nativeChrome.loadTimes === "function"
    ? nativeChrome.loadTimes : null;
  const nativeCsi = nativeChrome && typeof nativeChrome.csi === "function"
    ? nativeChrome.csi : null;
  const nativeApp = nativeChrome && objectValue(nativeChrome.app);
  const nativeRuntime = nativeChrome && objectValue(nativeChrome.runtime);
  const nativeWebstore = nativeChrome && objectValue(nativeChrome.webstore);

  const loadProfile = profileSection("loadTimes");
  const csiProfile = profileSection("csi");
  const appProfile = profileSection("app");
  const runtimeProfile = profileSection("runtime");
  const webstoreProfile = profileSection("webstore");

  function sectionValue(section) {
    return objectValue(section && section.value) || section;
  }

  const nativeLoadValue = (() => {
    try { return nativeLoadTimes ? nativeLoadTimes.call(nativeChrome) : null; }
    catch (_error) { return null; }
  })();
  const nativeCsiValue = (() => {
    try { return nativeCsi ? nativeCsi.call(nativeChrome) : null; }
    catch (_error) { return null; }
  })();
  const loadValueProfile = sectionValue(loadProfile);
  const csiValueProfile = sectionValue(csiProfile);
  const nowMs = Date.now();
  const epochSeconds = nowMs / 1000;
  const timeOrigin = finite(
    typeof performance !== "undefined" && performance.timeOrigin,
    nowMs,
  );

  function loadTimesValue() {
    const source = loadValueProfile || nativeLoadValue || {};
    const requestTime = finite(source.requestTime, epochSeconds);
    const startLoadTime = finite(source.startLoadTime, requestTime);
    const value = {
      requestTime,
      startLoadTime,
      commitLoadTime: finite(source.commitLoadTime, 0),
      finishDocumentLoadTime: finite(source.finishDocumentLoadTime, requestTime),
      finishLoadTime: finite(source.finishLoadTime, requestTime),
      firstPaintTime: finite(source.firstPaintTime, 0),
      firstPaintAfterLoadTime: finite(source.firstPaintAfterLoadTime, 0),
      navigationType: string(source.navigationType, "Other"),
      wasFetchedViaSpdy: boolean(source.wasFetchedViaSpdy, false),
      wasNpnNegotiated: boolean(source.wasNpnNegotiated, false),
      npnNegotiatedProtocol: string(source.npnNegotiatedProtocol, ""),
      wasAlternateProtocolAvailable: boolean(source.wasAlternateProtocolAvailable, false),
      connectionInfo: string(source.connectionInfo, "unknown"),
    };
    for (const key of Object.keys(source)) if (!own(value, key)) value[key] = source[key];
    return value;
  }

  function csiValue() {
    const source = csiValueProfile || nativeCsiValue || {};
    const value = {
      startE: finite(source.startE, Math.round(timeOrigin)),
      onloadT: finite(source.onloadT, Math.round(timeOrigin)),
      pageT: finite(source.pageT, typeof performance !== "undefined" ? performance.now() : 0),
      tran: finite(source.tran, 15),
    };
    for (const key of Object.keys(source)) if (!own(value, key)) value[key] = source[key];
    return value;
  }

  const hasNativeLoad = typeof nativeLoadTimes === "function";
  const hasNativeCsi = typeof nativeCsi === "function";
  const loadEnabled = present(loadProfile, hasNativeLoad || !nativeChrome);
  const csiEnabled = present(csiProfile, hasNativeCsi || !nativeChrome);
  const appEnabled = present(appProfile, !!nativeApp || !nativeChrome);
  if (loadEnabled) {
    defineData(chrome, "loadTimes", callable(
      nativeLoadTimes,
      function loadTimes() { return loadTimesValue(); },
      "loadTimes",
      "function () { [native code] }",
    ));
  } else removeProperty(chrome, "loadTimes");
  if (csiEnabled) {
    defineData(chrome, "csi", callable(
      nativeCsi,
      function csi() { return csiValue(); },
      "csi",
      "function () { [native code] }",
    ));
  } else removeProperty(chrome, "csi");

  const defaultInstallState = {
    DISABLED: "disabled", INSTALLED: "installed", NOT_INSTALLED: "not_installed",
  };
  const defaultRunningState = {
    CANNOT_RUN: "cannot_run", READY_TO_RUN: "ready_to_run", RUNNING: "running",
  };
  function enumValue(section, key, fallback) {
    const value = section && objectValue(section[key]);
    return value || fallback;
  }

  function createApp() {
    const source = cloneObject(nativeApp);
    const isInstalled = boolean(appProfile && appProfile.isInstalled, false);
    const installState = enumValue(appProfile, "InstallState", defaultInstallState);
    const runningState = enumValue(appProfile, "RunningState", defaultRunningState);
    defineData(source, "isInstalled", isInstalled);
    defineData(source, "getDetails", callable(
      nativeApp && nativeApp.getDetails,
      function getDetails() { return appProfile && own(appProfile, "details") ? appProfile.details : null; },
      "getDetails",
    ));
    defineData(source, "getIsInstalled", callable(
      nativeApp && nativeApp.getIsInstalled,
      function getIsInstalled() { return isInstalled; },
      "getIsInstalled",
    ));
    defineData(source, "installState", callable(
      nativeApp && nativeApp.installState,
      function installState() { return string(appProfile && appProfile.installState, "not_installed"); },
      "installState",
    ));
    defineData(source, "runningState", callable(
      nativeApp && nativeApp.runningState,
      function runningState() { return string(appProfile && appProfile.runningState, "cannot_run"); },
      "runningState",
    ));
    defineData(source, "InstallState", installState);
    defineData(source, "RunningState", runningState);
    return source;
  }
  if (appEnabled) defineData(chrome, "app", createApp());
  else removeProperty(chrome, "app");

  function eventObject() {
    const event = Object.create(Object.prototype);
    const noop = () => undefined;
    defineData(event, "addListener", callable(null, noop, "addListener"));
    defineData(event, "removeListener", callable(null, noop, "removeListener"));
    defineData(event, "hasListener", callable(null, () => false, "hasListener"));
    return event;
  }

  function createPort(args) {
    const port = Object.create(Object.prototype);
    const name = args && args.length && args[0] && typeof args[0] === "object"
      ? string(args[0].name, "") : string(args && args[0], "");
    defineData(port, "name", name);
    defineData(port, "sender", null);
    defineData(port, "onDisconnect", eventObject());
    defineData(port, "onMessage", eventObject());
    defineData(port, "postMessage", callable(null, () => undefined, "postMessage"));
    defineData(port, "disconnect", callable(null, () => undefined, "disconnect"));
    return port;
  }

  const defaultEnums = {
    ContextType: { APP: "APP", BACKGROUND: "BACKGROUND", EXTENSION: "EXTENSION", OFFSCREEN_DOCUMENT: "OFFSCREEN_DOCUMENT", POPUP: "POPUP", SIDE_PANEL: "SIDE_PANEL", TAB: "TAB" },
    OnInstalledReason: { CHROME_UPDATE: "chrome_update", INSTALL: "install", SHARED_MODULE_UPDATE: "shared_module_update", UPDATE: "update" },
    OnRestartRequiredReason: { APP_UPDATE: "app_update", OS_UPDATE: "os_update", PERIODIC: "periodic" },
    PlatformArch: { ARM: "arm", ARM64: "arm64", MIPS: "mips", MIPS64: "mips64", X86_32: "x86-32", X86_64: "x86-64" },
    PlatformOs: { ANDROID: "android", CROS: "cros", LINUX: "linux", MAC: "mac", OPENBSD: "openbsd", WIN: "win" },
    RequestUpdateCheckStatus: { NO_UPDATE: "no_update", THROTTLED: "throttled", UPDATE_AVAILABLE: "update_available" },
  };

  function createRuntime() {
    const runtime = cloneObject(nativeRuntime);
    const id = runtimeProfile && typeof runtimeProfile.id === "string"
      ? runtimeProfile.id : (nativeRuntime && typeof nativeRuntime.id === "string" ? nativeRuntime.id : null);
    defineData(runtime, "id", id);
    defineData(runtime, "connect", callable(
      nativeRuntime && nativeRuntime.connect,
      function connect() { return createPort(arguments); },
      "connect",
    ));
    defineData(runtime, "sendMessage", callable(
      nativeRuntime && nativeRuntime.sendMessage,
      function sendMessage() {
        const args = Array.from(arguments);
        const callback = args.find((value) => typeof value === "function");
        if (callback) {
          try { callback(); } catch (_error) { /* extension callbacks are best effort */ }
        }
        return undefined;
      },
      "sendMessage",
    ));
    defineData(runtime, "getManifest", callable(
      nativeRuntime && nativeRuntime.getManifest,
      function getManifest() {
        const manifest = runtimeProfile && objectValue(runtimeProfile.manifest);
        return manifest ? cloneObject(manifest) : {};
      },
      "getManifest",
    ));

    const lastErrorDescriptor = nativeRuntime && ownDescriptor(nativeRuntime, "lastError");
    const lastErrorGetter = lastErrorDescriptor && lastErrorDescriptor.get;
    defineAccessor(
      runtime,
      "lastError",
      callable(
        lastErrorGetter,
        function getLastError() {
          return runtimeProfile && own(runtimeProfile, "lastError") ? runtimeProfile.lastError : undefined;
        },
        "get lastError",
        "function get lastError() { [native code] }",
      ),
      { set: undefined, enumerable: true, configurable: true },
    );

    const enumProfiles = runtimeProfile && objectValue(runtimeProfile.enums)
      ? runtimeProfile.enums : {};
    for (const [key, fallback] of Object.entries(defaultEnums)) {
      defineData(runtime, key, enumValue(enumProfiles, key, fallback));
    }
    return runtime;
  }

  // Bundled/headless Chromium has no native chrome.runtime.  Expose the
  // compatibility surface by default in that environment; an explicit
  // profile can still model a normal page without an extension by setting
  // ``runtime.present`` to false (as the real-browser baseline does).
  const runtimeEnabled = present(
    runtimeProfile,
    !!nativeRuntime || (!nativeChrome && !hasProfile),
  );
  if (runtimeEnabled) defineData(chrome, "runtime", createRuntime());
  else removeProperty(chrome, "runtime");

  const webstoreEnabled = present(webstoreProfile, !!nativeWebstore);
  if (webstoreEnabled) {
    const webstore = cloneObject(nativeWebstore);
    defineData(webstore, "install", callable(
      nativeWebstore && nativeWebstore.install,
      () => undefined,
      "install",
    ));
    defineData(chrome, "webstore", webstore);
  } else removeProperty(chrome, "webstore");

  try {
    Object.defineProperty(chrome, marker, {
      value: Object.freeze({ version: "1.0.0", profile: hasProfile }),
      writable: false, enumerable: false, configurable: false,
    });
  } catch (_error) { /* object may be hardened */ }

  const windowChromeDescriptor = ownDescriptor(window, "chrome");
  if (!windowChromeDescriptor) {
    try {
      Object.defineProperty(window, "chrome", {
        value: chrome, writable: true, enumerable: true, configurable: false,
      });
    } catch (_error) {
      try { window.chrome = chrome; } catch (_ignored) { /* CSP/hardened realm */ }
    }
  } else if (windowChromeDescriptor.writable) {
    try { window.chrome = chrome; } catch (_error) { /* preserve native object */ }
  }
}());
