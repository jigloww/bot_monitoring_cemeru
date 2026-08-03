/*
 * Profile-aware Speech Synthesis compatibility layer.
 *
 * Native SpeechSynthesis, SpeechSynthesisUtterance, and SpeechSynthesisEvent
 * objects are retained whenever the browser provides them.  A profile only
 * replaces the observable voice list and state methods; speak() never starts
 * an audio engine.  Synthetic voices inherit from the native
 * SpeechSynthesisVoice.prototype, preserving instanceof and object shape.
 */
(function speechStealthModule() {
  "use strict";

  if (typeof window === "undefined" || typeof speechSynthesis === "undefined") return;

  const synthesis = speechSynthesis;
  const synthesisPrototype = typeof SpeechSynthesis !== "undefined"
    ? SpeechSynthesis.prototype : Object.getPrototypeOf(synthesis);
  const voicePrototype = typeof SpeechSynthesisVoice !== "undefined"
    ? SpeechSynthesisVoice.prototype : null;
  if (!synthesisPrototype) return;

  const marker = Symbol.for("cemeru.stealth.speech.v1");
  if (synthesisPrototype[marker] || (voicePrototype && voicePrototype[marker])) return;

  const stealth = globalThis.__stealth && typeof globalThis.__stealth === "object"
    ? globalThis.__stealth : null;
  const profile = stealth && stealth.speechProfile &&
    typeof stealth.speechProfile === "object" ? stealth.speechProfile : {};
  const profileVoices = Array.isArray(profile.voices)
    ? profile.voices.filter((voice) => voice && typeof voice === "object") : [];
  const hasProfile = Object.keys(profile).length > 0;

  const own = (object, property) =>
    Object.prototype.hasOwnProperty.call(object, property);

  function descriptor(object, property) {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Object.getOwnPropertyDescriptor(owner, property);
      if (value) return { owner, value };
    }
    return null;
  }

  function nativeValue(property) {
    try { return Reflect.get(synthesis, property); }
    catch (_error) { return undefined; }
  }

  /* Reuse the native-source wrapper installed by the completed modules. */
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
              ? stealth.fontsFunctionState : null)))));
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
        Object.defineProperty(stealth, "speechFunctionState", {
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
    } catch (_error) { /* hardened realms may reject optional masking */ }
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
    if (value === synthesis) return true;
    try {
      return typeof SpeechSynthesis !== "undefined" && value instanceof SpeechSynthesis;
    } catch (_error) { return false; }
  }

  const voiceRecords = new WeakMap();
  const voices = profileVoices.map((entry) => {
    const voice = Object.create(voicePrototype || Object.prototype);
    voiceRecords.set(voice, {
      voiceURI: typeof entry.voiceURI === "string" ? entry.voiceURI :
        (typeof entry.uri === "string" ? entry.uri : (typeof entry.name === "string" ? entry.name : "")),
      name: typeof entry.name === "string" ? entry.name : "",
      lang: typeof entry.lang === "string" ? entry.lang : "en-US",
      localService: typeof entry.localService === "boolean" ? entry.localService :
        (typeof entry.local === "boolean" ? entry.local : false),
      default: typeof entry.default === "boolean" ? entry.default : false,
    });
    return voice;
  });

  function setGetter(proto, property, implementation, fallbackName) {
    const found = descriptor(proto, property);
    if (!found || !found.value || found.value.configurable === false ||
        typeof found.value.get !== "function") return;
    const getter = callable(
      found.value.get,
      implementation,
      found.value.get.name || `get ${String(property)}`,
      fallbackName || `function get ${String(property)}() { [native code] }`,
    );
    if (typeof getter !== "function") return;
    Reflect.defineProperty(found.owner, property, {
      get: getter,
      set: found.value.set,
      enumerable: found.value.enumerable,
      configurable: found.value.configurable,
    });
  }

  function setMethod(proto, property, implementation, fallbackName) {
    const found = descriptor(proto, property);
    if (!found || !found.value || found.value.configurable === false ||
        typeof found.value.value !== "function") return;
    const method = callable(
      found.value.value,
      implementation,
      found.value.value.name || String(property),
      fallbackName || `function ${String(property)}() { [native code] }`,
    );
    if (typeof method !== "function") return;
    Reflect.defineProperty(found.owner, property, {
      value: method,
      writable: found.value.writable,
      enumerable: found.value.enumerable,
      configurable: found.value.configurable,
    });
  }

  function setVoiceGetter(property) {
    if (!voicePrototype) return;
    const found = descriptor(voicePrototype, property);
    if (!found || !found.value || found.value.configurable === false ||
        typeof found.value.get !== "function") return;
    const nativeGetter = found.value.get;
    const getter = callable(
      nativeGetter,
      function getVoiceProperty() {
        const record = voiceRecords.get(this);
        if (record) return record[property];
        return Reflect.apply(nativeGetter, this, []);
      },
      nativeGetter.name || `get ${property}`,
      `function get ${property}() { [native code] }`,
    );
    Reflect.defineProperty(found.owner, property, {
      get: getter,
      set: found.value.set,
      enumerable: found.value.enumerable,
      configurable: found.value.configurable,
    });
  }

  if (hasProfile) {
    const initial = {
      speaking: typeof profile.speaking === "boolean" ? profile.speaking : Boolean(nativeValue("speaking")),
      pending: typeof profile.pending === "boolean" ? profile.pending : Boolean(nativeValue("pending")),
      paused: typeof profile.paused === "boolean" ? profile.paused : Boolean(nativeValue("paused")),
      onvoiceschanged: null,
    };
    const stateRecords = new WeakMap([[synthesis, initial]]);
    const getState = (receiver) => stateRecords.get(receiver) || initial;
    const nativeGetVoices = descriptor(synthesisPrototype, "getVoices");

    if (profileVoices.length > 0 && voicePrototype) {
      for (const property of ["voiceURI", "name", "lang", "localService", "default"]) {
        setVoiceGetter(property);
      }
    }

    setMethod(synthesisPrototype, "getVoices", function getVoices() {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      if (own(profile, "voices")) return voices.slice();
      if (nativeGetVoices && typeof nativeGetVoices.value.value === "function") {
        return Reflect.apply(nativeGetVoices.value.value, this, []);
      }
      return [];
    });
    for (const property of ["speaking", "pending", "paused"]) {
      setGetter(synthesisPrototype, property, function getSpeechState() {
        if (!validReceiver(this)) throw new TypeError("Illegal invocation");
        return Boolean(getState(this)[property]);
      });
    }

    setMethod(synthesisPrototype, "cancel", function cancel() {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      const state = getState(this);
      state.speaking = false;
      state.pending = false;
      state.paused = false;
      return undefined;
    });
    setMethod(synthesisPrototype, "pause", function pause() {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      getState(this).paused = true;
      return undefined;
    });
    setMethod(synthesisPrototype, "resume", function resume() {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      getState(this).paused = false;
      return undefined;
    });
    setMethod(synthesisPrototype, "speak", function speak(utterance) {
      if (!validReceiver(this)) throw new TypeError("Illegal invocation");
      if (typeof SpeechSynthesisUtterance !== "undefined" &&
          !(utterance instanceof SpeechSynthesisUtterance)) {
        throw new TypeError("The argument is not a SpeechSynthesisUtterance");
      }
      // Deliberately do not synthesize audio or dispatch asynchronous events.
      return undefined;
    });

    const voicesChanged = descriptor(synthesisPrototype, "onvoiceschanged");
    if (voicesChanged && voicesChanged.value && typeof voicesChanged.value.get === "function" &&
        voicesChanged.value.configurable !== false) {
      const nativeGetter = voicesChanged.value.get;
      const nativeSetter = voicesChanged.value.set;
      const getter = callable(nativeGetter, function getVoicesChanged() {
        if (!validReceiver(this)) throw new TypeError("Illegal invocation");
        return getState(this).onvoiceschanged;
      }, nativeGetter.name || "get onvoiceschanged", "function get onvoiceschanged() { [native code] }");
      const setter = typeof nativeSetter === "function" ? callable(nativeSetter, function setVoicesChanged(value) {
        if (!validReceiver(this)) throw new TypeError("Illegal invocation");
        getState(this).onvoiceschanged = value == null || typeof value === "function" ? value : null;
        return undefined;
      }, nativeSetter.name || "set onvoiceschanged", "function set onvoiceschanged() { [native code] }") : nativeSetter;
      Reflect.defineProperty(voicesChanged.owner, "onvoiceschanged", {
        get: getter,
        set: setter,
        enumerable: voicesChanged.value.enumerable,
        configurable: voicesChanged.value.configurable,
      });
    }
  }

  try {
    Object.defineProperty(synthesisPrototype, marker, {
      value: Object.freeze({ version: "1.0.0", profile: hasProfile }),
      writable: false,
      enumerable: false,
      configurable: false,
    });
    if (voicePrototype) {
      Object.defineProperty(voicePrototype, marker, {
        value: true,
        writable: false,
        enumerable: false,
        configurable: false,
      });
    }
  } catch (_error) { /* hardened realms may refuse optional markers */ }
}());
