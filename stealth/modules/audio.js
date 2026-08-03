/*
 * Profile-aware Web Audio fingerprint compatibility layer.
 *
 * Constructors, graph topology, parameter ranges, and audible behavior stay
 * native.  Only analyser arrays and offline-rendered sample buffers are
 * adapted, and only while an explicit __stealth.audioProfile is present.
 * Every adjustment is deterministic and derived from that profile.
 */
(function audioStealthModule() {
  "use strict";

  const root = typeof globalThis !== "undefined" ? globalThis : window;
  const stealth = root && root.__stealth && typeof root.__stealth === "object"
    ? root.__stealth : null;
  const profile = stealth && stealth.audioProfile &&
    typeof stealth.audioProfile === "object" ? stealth.audioProfile : null;
  if (!profile || Object.keys(profile).length === 0) return;

  const Base = typeof root.BaseAudioContext !== "undefined" ? root.BaseAudioContext : null;
  const Audio = typeof root.AudioContext !== "undefined" ? root.AudioContext : null;
  const Offline = typeof root.OfflineAudioContext !== "undefined" ? root.OfflineAudioContext : null;
  const BufferCtor = typeof root.AudioBuffer !== "undefined" ? root.AudioBuffer : null;
  const Analyser = typeof root.AnalyserNode !== "undefined" ? root.AnalyserNode : null;
  const Oscillator = typeof root.OscillatorNode !== "undefined" ? root.OscillatorNode : null;
  const Compressor = typeof root.DynamicsCompressorNode !== "undefined" ? root.DynamicsCompressorNode : null;
  const Gain = typeof root.GainNode !== "undefined" ? root.GainNode : null;
  const Biquad = typeof root.BiquadFilterNode !== "undefined" ? root.BiquadFilterNode : null;
  if (!Base && !Audio && !Offline) return;

  const moduleMarker = Symbol.for("cemeru.stealth.audio.v1");
  const methodMarker = Symbol.for("cemeru.stealth.audio.methods.v1");
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

  function descriptor(object, property) {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Object.getOwnPropertyDescriptor(owner, property);
      if (value) return { owner, value };
    }
    return null;
  }

  const toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
  const isState = (state) => state && state.sources &&
    typeof state.sources.set === "function" && typeof state.original === "function" &&
    typeof state.replacement === "function";
  const shared = [
    "navigatorFunctionState", "windowFunctionState", "screenFunctionState",
    "chromeFunctionState", "permissionsFunctionState", "fontsFunctionState",
    "speechFunctionState", "performanceFunctionState", "webglFunctionState",
    "canvasFunctionState",
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
        Object.defineProperty(stealth, "audioFunctionState", {
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
    const wrapped = new Proxy(nativeFunction, {
      apply(_target, receiver, args) { return Reflect.apply(implementation, receiver, args); },
    });
    if (functionState) functionState.sources.set(wrapped, nativeSource(nativeFunction, `function ${name}() { [native code] }`));
    return wrapped;
  }

  function hashSeed(value) {
    const text = String(value === undefined ? "audio" : value);
    let hash = 2166136261 >>> 0;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index); hash = Math.imul(hash, 16777619) >>> 0;
    }
    return hash >>> 0;
  }
  const seed = hashSeed(own(profile, "renderHash") ? profile.renderHash :
    (own(profile, "sampleRate") ? profile.sampleRate : "audio"));
  const fftNoise = typeof profile.fftNoise === "number" && Number.isFinite(profile.fftNoise)
    ? Math.abs(profile.fftNoise) : 0;

  function noise(index, channel) {
    let value = (seed ^ Math.imul(index + 1, 1103515245) ^ Math.imul(channel + 1, 12345)) >>> 0;
    value ^= value << 13; value >>>= 0; value ^= value >>> 17; value >>>= 0; value ^= value << 5; value >>>= 0;
    return ((value & 0xffff) / 65535) * 2 - 1;
  }

  function isAnalyser(value) {
    if (!Analyser) return false;
    try { return value instanceof Analyser; } catch (_error) { return false; }
  }
  function isOffline(value) {
    if (!Offline) return false;
    try { return value instanceof Offline; } catch (_error) { return false; }
  }
  function isAudioBuffer(value) {
    if (!BufferCtor) return false;
    try { return value instanceof BufferCtor; } catch (_error) { return false; }
  }

  function adjustArray(array, kind) {
    if (!fftNoise || !array || typeof array.length !== "number") return;
    const length = array.length;
    for (let index = 0; index < length; index += 1) {
      const delta = noise(index, kind) * fftNoise;
      if (kind === 1 || kind === 3) {
        array[index] = Math.max(0, Math.min(255, Math.round(Number(array[index]) + delta * 255)));
      } else {
        array[index] = Number(array[index]) + delta;
      }
    }
  }

  function adjustBuffer(buffer, context) {
    if (!isAudioBuffer(buffer) || (!fftNoise && !own(profile, "renderHash")) || !context || typeof context.createBuffer !== "function") return buffer;
    try {
      const clone = Reflect.apply(context.createBuffer, context, [buffer.numberOfChannels, buffer.length, buffer.sampleRate]);
      for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
        const source = buffer.getChannelData(channel);
        const target = clone.getChannelData(channel);
        target.set(source);
        if (fftNoise || own(profile, "renderHash")) {
          for (let index = 0; index < target.length; index += 1) {
            target[index] = Number(target[index]) + noise(index, channel) * (fftNoise || 0.000001);
          }
        }
      }
      return clone;
    } catch (_error) { return buffer; }
  }

  function installMethod(proto, property, implementationFactory) {
    if (!proto) return;
    const found = descriptor(proto, property);
    if (!found || !found.value || typeof found.value.value !== "function" || found.value.configurable === false) return;
    let state = found.owner[methodMarker];
    if (state && state[property]) return;
    const nativeFunction = found.value.value;
    const implementation = implementationFactory(nativeFunction);
    const wrapped = callable(nativeFunction, implementation, nativeFunction.name || property);
    if (typeof wrapped !== "function") return;
    try {
      Object.defineProperty(found.owner, property, { value: wrapped, writable: found.value.writable, enumerable: found.value.enumerable, configurable: found.value.configurable });
      if (!state) {
        state = {};
        Object.defineProperty(found.owner, methodMarker, { value: state, writable: false, enumerable: false, configurable: false });
      }
      state[property] = true;
    } catch (_error) { /* hardened native prototype */ }
  }

  function installContext(proto) {
    if (!proto || proto[moduleMarker]) return;
    try { Object.defineProperty(proto, moduleMarker, { value: true, writable: false, enumerable: false, configurable: false }); }
    catch (_error) { return; }
    ["createAnalyser", "createOscillator", "createDynamicsCompressor", "createGain", "createBuffer", "createBufferSource", "createBiquadFilter"].forEach((property) => {
      installMethod(proto, property, (native) => function audioFactory() {
        return Reflect.apply(native, this, arguments);
      });
    });
    installMethod(proto, "decodeAudioData", (native) => function decodeAudioData() {
      const result = Reflect.apply(native, this, arguments);
      if (!result || typeof result.then !== "function") return result;
      return result.then((buffer) => isAudioBuffer(buffer) ? adjustBuffer(buffer, this) : buffer);
    });
  }

  function installAnalyser(proto) {
    if (!proto || proto[moduleMarker]) return;
    try { Object.defineProperty(proto, moduleMarker, { value: true, writable: false, enumerable: false, configurable: false }); }
    catch (_error) { return; }
    ["getFloatFrequencyData", "getByteFrequencyData", "getFloatTimeDomainData", "getByteTimeDomainData"].forEach((property, index) => {
      installMethod(proto, property, (native) => function analyserData(array) {
        const result = Reflect.apply(native, this, arguments);
        if (isAnalyser(this) && array && typeof array.length === "number") adjustArray(array, index);
        return result;
      });
    });
  }

  function installOffline(proto) {
    if (!proto || proto[moduleMarker]) return;
    try { Object.defineProperty(proto, moduleMarker, { value: true, writable: false, enumerable: false, configurable: false }); }
    catch (_error) { return; }
    installMethod(proto, "startRendering", (native) => function startRendering() {
      const result = Reflect.apply(native, this, arguments);
      if (!result || typeof result.then !== "function") return result;
      return result.then((buffer) => isOffline(this) ? adjustBuffer(buffer, this) : buffer);
    });
  }

  if (Base && Base.prototype) installContext(Base.prototype);
  else if (Audio && Audio.prototype) installContext(Audio.prototype);
  if (Analyser && Analyser.prototype) installAnalyser(Analyser.prototype);
  if (Offline && Offline.prototype) installOffline(Offline.prototype);
})();
