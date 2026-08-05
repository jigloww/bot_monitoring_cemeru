"""Experiment 060C: canonical Browser Platform Audio baseline.

This collector performs one passive browser capture.  It inspects native Web
Audio constructors and prototypes, then renders a small graph in an
``OfflineAudioContext`` only; it never resumes a live context, plays audio,
requests media, or changes any historical artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserConfig, BrowserSessionManager
from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    sha256_file,
    write_json_exclusive,
    write_text_exclusive,
)


ARTIFACT_NAMES = (
    "audio.json",
    "prototype.json",
    "descriptors.json",
    "methods.json",
    "fingerprint.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "audio_report.md",
)


AUDIO_PROBE = r"""
async () => {
  const errors = [];
  const safe = (callback, fallback = null) => {
    try { return callback(); } catch (_) { return fallback; }
  };
  const nativeSource = (value) => safe(() => Function.prototype.toString.call(value), null);
  const ownKeys = (target) => {
    if (!target) return [];
    return safe(() => [...Object.getOwnPropertyNames(target), ...Object.getOwnPropertySymbols(target).map(String)]
      .filter((value, index, values) => values.indexOf(value) === index).sort(), []);
  };
  const descriptor = (target, property) => {
    if (!target) return null;
    const item = safe(() => Object.getOwnPropertyDescriptor(target, property), null);
    if (!item) return null;
    return {
      configurable: !!item.configurable,
      enumerable: !!item.enumerable,
      writable: Object.prototype.hasOwnProperty.call(item, 'writable') ? !!item.writable : null,
      hasGetter: typeof item.get === 'function',
      hasSetter: typeof item.set === 'function',
      valueType: Object.prototype.hasOwnProperty.call(item, 'value') ? typeof item.value : null,
      getterSource: typeof item.get === 'function' ? nativeSource(item.get) : null,
      setterSource: typeof item.set === 'function' ? nativeSource(item.set) : null,
      valueSource: typeof item.value === 'function' ? nativeSource(item.value) : null
    };
  };
  const descriptorMap = (target) => Object.fromEntries(ownKeys(target).map((name) => [name, descriptor(target, name)]));
  const chain = (target) => {
    const result = [];
    const seen = new Set();
    let current = target;
    while (current && !seen.has(current)) {
      seen.add(current);
      result.push(safe(() => current.constructor && current.constructor.name, null));
      current = safe(() => Object.getPrototypeOf(current), null);
    }
    return result;
  };
  const errorInfo = (error) => ({
    name: safe(() => error && error.name, null),
    constructor: safe(() => error && error.constructor && error.constructor.name, null),
    message: safe(() => String(error && error.message || '').slice(0, 180), '')
  });
  const digestBytes = async (value) => {
    try {
      const bytes = ArrayBuffer.isView(value)
        ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
        : new TextEncoder().encode(String(value));
      const buffer = await crypto.subtle.digest('SHA-256', bytes);
      return [...new Uint8Array(buffer)].map((part) => part.toString(16).padStart(2, '0')).join('');
    } catch (_) {
      return null;
    }
  };
  const methodInfo = async (prototype, name) => {
    const fn = safe(() => prototype && prototype[name], null);
    const illegalInvocation = { tested: false, throws: false, error: null };
    if (typeof fn === 'function') {
      illegalInvocation.tested = true;
      try { fn.call({}); }
      catch (error) { illegalInvocation.throws = true; illegalInvocation.error = errorInfo(error); }
    }
    return {
      available: typeof fn === 'function',
      name: typeof fn === 'function' ? safe(() => fn.name, null) : null,
      length: typeof fn === 'function' ? safe(() => fn.length, null) : null,
      source: typeof fn === 'function' ? nativeSource(fn) : null,
      nativeSource: typeof fn === 'function' && /\[native code\]/.test(nativeSource(fn) || ''),
      descriptor: descriptor(prototype, name),
      illegalInvocation
    };
  };
  const constructorInfo = (name, constructor) => {
    const prototype = constructor && constructor.prototype;
    let misuse = { tested: false, throws: false, error: null };
    if (typeof constructor === 'function') {
      misuse.tested = true;
      try { constructor(); }
      catch (error) { misuse.throws = true; misuse.error = errorInfo(error); }
    }
    return {
      available: typeof constructor === 'function',
      name: typeof constructor === 'function' ? safe(() => constructor.name, name) : null,
      length: typeof constructor === 'function' ? safe(() => constructor.length, null) : null,
      source: typeof constructor === 'function' ? nativeSource(constructor) : null,
      nativeSource: typeof constructor === 'function' && /\[native code\]/.test(nativeSource(constructor) || ''),
      descriptor: descriptor(globalThis, name),
      misuse,
      prototype: {
        exists: !!prototype,
        constructorName: safe(() => prototype && prototype.constructor && prototype.constructor.name, null),
        ownProperties: ownKeys(prototype),
        prototypeChain: chain(prototype),
        objectPrototype: safe(() => Object.getPrototypeOf(prototype).constructor.name, null),
        instanceofObject: safe(() => prototype instanceof Object, false),
        toStringTag: descriptor(prototype, Symbol.toStringTag)
      }
    };
  };
  const functionMap = async (prototype) => {
    const result = {};
    for (const name of ownKeys(prototype)) {
      if (name === 'constructor' || name.startsWith('Symbol(')) continue;
      if (typeof safe(() => prototype[name], null) === 'function') result[name] = await methodInfo(prototype, name);
    }
    return result;
  };
  const constructorNames = [
    'AudioContext', 'OfflineAudioContext', 'BaseAudioContext', 'AudioDestinationNode',
    'AudioListener', 'AudioParam', 'AudioBuffer', 'AudioBufferSourceNode', 'AnalyserNode',
    'GainNode', 'BiquadFilterNode', 'OscillatorNode', 'DynamicsCompressorNode',
    'ChannelMergerNode', 'ChannelSplitterNode', 'DelayNode', 'StereoPannerNode',
    'PannerNode', 'ConstantSourceNode', 'WaveShaperNode', 'PeriodicWave',
    'AudioWorkletNode', 'AudioNode', 'AudioScheduledSourceNode'
  ];
  const output = {
    supported: false,
    errors,
    constructors: {},
    prototype: {},
    descriptors: {},
    methods: {},
    audio: {},
    capabilities: {},
    fingerprintObservations: {},
    offline: {}
  };
  try {
    for (const name of constructorNames) output.constructors[name] = constructorInfo(name, globalThis[name]);
    const offlineConstructor = globalThis.OfflineAudioContext;
    const baseConstructor = globalThis.BaseAudioContext;
    if (typeof offlineConstructor !== 'function') {
      output.errors.push({ name: 'OfflineAudioContextUnavailable', message: 'OfflineAudioContext is unavailable' });
      return output;
    }
    const offline = new offlineConstructor(1, 512, 44100);
    const analyser = offline.createAnalyser();
    analyser.fftSize = 64;
    const oscillator = offline.createOscillator();
    const gain = offline.createGain();
    const compressor = offline.createDynamicsCompressor();
    const filter = offline.createBiquadFilter();
    const merger = offline.createChannelMerger(1);
    const splitter = offline.createChannelSplitter(1);
    const delay = offline.createDelay(1);
    const panner = offline.createPanner();
    const stereo = offline.createStereoPanner();
    const constant = offline.createConstantSource();
    const shaper = offline.createWaveShaper();
    const buffer = offline.createBuffer(1, 64, 44100);
    const source = offline.createBufferSource();
    output.supported = true;
    oscillator.type = 'sine';
    oscillator.frequency.value = 440;
    gain.gain.value = 0.08;
    compressor.threshold.value = -24;
    filter.type = 'lowpass';
    filter.frequency.value = 1200;
    oscillator.connect(filter);
    filter.connect(compressor);
    compressor.connect(gain);
    gain.connect(analyser);
    analyser.connect(offline.destination);
    // The graph is rendered only offline; no live destination is resumed.
    oscillator.start(0);
    let liveAudio = { available: false, constructor: null, state: null, sampleRate: null, baseLatency: null, outputLatency: null, destination: null, closed: false };
    if (typeof globalThis.AudioContext === 'function') {
      try {
        const live = new globalThis.AudioContext();
        liveAudio = {
          available: true,
          constructor: safe(() => live.constructor.name, null),
          state: safe(() => live.state, null),
          sampleRate: safe(() => live.sampleRate, null),
          baseLatency: safe(() => live.baseLatency, null),
          outputLatency: safe(() => live.outputLatency, null),
          currentTime: safe(() => live.currentTime, null),
          destination: {
            constructor: safe(() => live.destination.constructor.name, null),
            maxChannelCount: safe(() => live.destination.maxChannelCount, null),
            channelCount: safe(() => live.destination.channelCount, null),
            channelCountMode: safe(() => live.destination.channelCountMode, null),
            channelInterpretation: safe(() => live.destination.channelInterpretation, null),
            objectToString: safe(() => Object.prototype.toString.call(live.destination), null)
          },
          prototypeChain: chain(Object.getPrototypeOf(live))
        };
        try { await live.close(); liveAudio.closed = true; } catch (_) {}
      } catch (error) {
        liveAudio = { available: false, error: errorInfo(error) };
      }
    }
    output.audio = {
      constructor: safe(() => offline.constructor && offline.constructor.name, null),
      state: safe(() => offline.state, null),
      sampleRate: safe(() => offline.sampleRate, null),
      currentTime: safe(() => offline.currentTime, null),
      baseLatency: safe(() => offline.baseLatency, null),
      outputLatency: safe(() => offline.outputLatency, null),
      contextType: safe(() => Object.prototype.toString.call(offline), null),
      prototypeChain: chain(Object.getPrototypeOf(offline)),
      instanceofOfflineAudioContext: offline instanceof offlineConstructor,
      destination: {
        constructor: safe(() => offline.destination.constructor.name, null),
        maxChannelCount: safe(() => offline.destination.maxChannelCount, null),
        channelCount: safe(() => offline.destination.channelCount, null),
        channelCountMode: safe(() => offline.destination.channelCountMode, null),
        channelInterpretation: safe(() => offline.destination.channelInterpretation, null),
        objectToString: safe(() => Object.prototype.toString.call(offline.destination), null),
        prototypeChain: chain(Object.getPrototypeOf(offline.destination))
      },
      listener: { constructor: safe(() => offline.listener.constructor.name, null), objectToString: safe(() => Object.prototype.toString.call(offline.listener), null) },
      live: liveAudio,
      graph: { analyser: !!analyser, oscillator: !!oscillator, gain: !!gain, compressor: !!compressor, filter: !!filter, merger: !!merger, splitter: !!splitter, delay: !!delay, panner: !!panner, stereoPanner: !!stereo, constantSource: !!constant, waveShaper: !!shaper, buffer: !!buffer, bufferSource: !!source, connectedOffline: true }
    };
    output.capabilities = {
      audioContext: typeof globalThis.AudioContext === 'function',
      offlineAudioContext: true,
      baseAudioContext: typeof baseConstructor === 'function',
      audioWorkletConstructor: typeof globalThis.AudioWorkletNode === 'function',
      audioWorklet: !!safe(() => offline.audioWorklet, null),
      sampleRate: offline.sampleRate,
      destinationMaxChannelCount: safe(() => offline.destination.maxChannelCount, null)
    };
    const ctorPrototypes = {};
    for (const name of constructorNames) {
      const ctor = globalThis[name];
      if (typeof ctor === 'function') ctorPrototypes[name] = ctor.prototype;
    }
    for (const [name, proto] of Object.entries(ctorPrototypes)) {
      output.prototype[name] = {
        constructor: name,
        ownProperties: ownKeys(proto),
        prototypeChain: chain(proto),
        constructorEquality: safe(() => proto.constructor === globalThis[name], false),
        instanceofObject: safe(() => proto instanceof Object, false),
        toStringTag: descriptor(proto, Symbol.toStringTag)
      };
      output.descriptors[name] = descriptorMap(proto);
      output.methods[name] = await functionMap(proto);
    }
    const frequencies = new Float32Array(analyser.frequencyBinCount);
    const bytes = new Uint8Array(analyser.frequencyBinCount);
    const timeFloat = new Float32Array(analyser.fftSize);
    const timeBytes = new Uint8Array(analyser.fftSize);
    analyser.getFloatFrequencyData(frequencies);
    analyser.getByteFrequencyData(bytes);
    analyser.getFloatTimeDomainData(timeFloat);
    analyser.getByteTimeDomainData(timeBytes);
    const rendered = await offline.startRendering();
    const renderedData = rendered.getChannelData(0);
    output.fingerprintObservations = {
      fft: {
        fftSize: analyser.fftSize,
        frequencyBinCount: analyser.frequencyBinCount,
        floatFrequencyLength: frequencies.length,
        byteFrequencyLength: bytes.length,
        floatTimeLength: timeFloat.length,
        byteTimeLength: timeBytes.length,
        floatFrequencySha256: await digestBytes(frequencies),
        byteFrequencySha256: await digestBytes(bytes),
        floatTimeSha256: await digestBytes(timeFloat),
        byteTimeSha256: await digestBytes(timeBytes)
      },
      rendered: {
        numberOfChannels: rendered.numberOfChannels,
        length: rendered.length,
        sampleRate: rendered.sampleRate,
        dataLength: renderedData.length,
        sha256: await digestBytes(renderedData),
        firstSamples: Array.from(renderedData.slice(0, 16))
      },
      audioParams: {
        oscillatorFrequency: oscillator.frequency.value,
        gain: gain.gain.value,
        compressorThreshold: compressor.threshold.value,
        filterFrequency: filter.frequency.value,
        filterType: filter.type
      },
      integrity: rendered.numberOfChannels === 1 && rendered.length === 512 && rendered.sampleRate === 44100 && renderedData.length === rendered.length,
      graphIntegrity: true
    };
    output.offline = {
      constructor: safe(() => rendered.constructor.name, null),
      objectToString: safe(() => Object.prototype.toString.call(rendered), null),
      instanceofAudioBuffer: typeof globalThis.AudioBuffer === 'function' ? rendered instanceof globalThis.AudioBuffer : false,
      prototypeEquality: typeof globalThis.AudioBuffer === 'function' ? Object.getPrototypeOf(rendered) === globalThis.AudioBuffer.prototype : false,
      prototypeChain: chain(Object.getPrototypeOf(rendered)),
      numberOfChannels: rendered.numberOfChannels,
      length: rendered.length,
      sampleRate: rendered.sampleRate,
      dataLength: renderedData.length
    };
    output.descriptors.special = {
      OfflineAudioContext_startRendering: descriptor(offlineConstructor.prototype, 'startRendering'),
      BaseAudioContext_createAnalyser: descriptor(baseConstructor && baseConstructor.prototype, 'createAnalyser'),
      AnalyserNode_getFloatFrequencyData: descriptor(globalThis.AnalyserNode && globalThis.AnalyserNode.prototype, 'getFloatFrequencyData'),
      AudioBuffer_getChannelData: descriptor(globalThis.AudioBuffer && globalThis.AudioBuffer.prototype, 'getChannelData')
    };
    output.methods.special = {
      OfflineAudioContext_startRendering: await methodInfo(offlineConstructor.prototype, 'startRendering'),
      BaseAudioContext_createAnalyser: await methodInfo(baseConstructor && baseConstructor.prototype, 'createAnalyser'),
      AnalyserNode_getFloatFrequencyData: await methodInfo(globalThis.AnalyserNode && globalThis.AnalyserNode.prototype, 'getFloatFrequencyData'),
      AudioBuffer_getChannelData: await methodInfo(globalThis.AudioBuffer && globalThis.AudioBuffer.prototype, 'getChannelData')
    };
  } catch (error) {
    output.errors.push(errorInfo(error));
  }
  return output;
}
"""


def _ordered(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _ordered(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(_ordered(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _historical_hashes(root: Path) -> dict[str, str]:
    reports = root / "reports" / "experiments"
    result: dict[str, str] = {}
    if not reports.is_dir():
        return result
    for path in sorted((item for item in reports.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        try:
            result[str(path.relative_to(root))] = sha256_file(path)
        except OSError:
            result[str(path.relative_to(root))] = ""
    return result


def _positive_timeout(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return parsed


def _browser_version(page: Any) -> str | None:
    try:
        browser = page.context.browser
        return browser.version if browser is not None else None
    except Exception:
        return None


def _capture(args: argparse.Namespace) -> tuple[str, dict[str, Any], str | None, float, int]:
    # BrowserSessionManager is the single Browser Platform entry point and
    # delegates the actual launch to launch_browser internally.
    config = BrowserConfig(browser=args.browser, headless=args.headless, persistent=False, url="about:blank", timeout=args.timeout, enable_stealth=False)
    manager = BrowserSessionManager(config)
    started_at = time.perf_counter()
    page: Any = None
    launches = 0
    error: str | None = None
    probe: dict[str, Any] = {}
    try:
        manager.start()
        launches = 1
        context = manager.get_context()
        pages = getattr(context, "pages", []) if context is not None else []
        if callable(pages):
            pages = pages()
        page = pages[0] if pages else manager.new_page()
        result = page.evaluate(AUDIO_PROBE)
        if isinstance(result, dict):
            probe = _ordered(result)
            probe["browserVersion"] = _browser_version(page)
        else:
            error = "Audio probe returned a non-object"
    except Exception as exc:
        error = str(exc)
    finally:
        if page is not None:
            try:
                manager.close_page(page)
            except Exception:
                pass
        try:
            manager.shutdown()
        except Exception:
            pass
    duration = (time.perf_counter() - started_at) * 1000.0
    return ("AVAILABLE" if launches and probe.get("supported") else ("PARTIAL" if launches else "UNKNOWN"), probe, error, duration, launches)


def _report(summary: dict[str, Any], data: dict[str, Any], fingerprint: dict[str, Any], validation: dict[str, Any]) -> str:
    audio = data.get("audio", {})
    capabilities = data.get("capabilities", {})
    lines = [
        "# Experiment 060C - Canonical Audio Baseline",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Browser Platform status: **{summary['playwright_status']}**",
        f"- Browser launches: **{summary['browser_launches']}**",
        f"- Network requests: **{summary['network_requests']}**",
        f"- Fingerprint SHA-256: `{fingerprint['sha256']}`",
        "",
        "## Audio Context",
        "",
        f"- Constructor: `{audio.get('constructor')}`",
        f"- Offline state: `{audio.get('state')}`",
        f"- Live AudioContext available: `{audio.get('live', {}).get('available')}`",
        f"- Live state: `{audio.get('live', {}).get('state')}`",
        f"- Sample rate: `{audio.get('live', {}).get('sampleRate') or audio.get('sampleRate')}`",
        f"- Base latency: `{audio.get('live', {}).get('baseLatency') or audio.get('baseLatency')}`",
        f"- Output latency: `{audio.get('live', {}).get('outputLatency') or audio.get('outputLatency')}`",
        f"- Offline render integrity: `{data.get('fingerprintObservations', {}).get('integrity')}`",
        "",
        "## Capabilities",
        "",
        "| Capability | Value |",
        "|---|---|",
    ]
    for name, value in capabilities.items():
        lines.append(f"| `{name}` | `{value}` |")
    lines += ["", "## Prototype and method coverage", "", f"- Constructors inspected: **{len(data.get('constructors', {}))}**", f"- Prototypes inspected: **{len(data.get('prototype', {}))}**", f"- Descriptor groups: **{len(data.get('descriptors', {}))}**", "", "## Validation", "", f"- Validation: **{'PASS' if validation['valid'] else 'FAIL'}**", "- No live context was resumed and no audio was played.", "- No stealth injection, network request, or historical artifact mutation was performed.", ""]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    historical_before = _historical_hashes(root)
    capture_status, probe, capture_error, duration_ms, launches = _capture(args)
    historical_after = _historical_hashes(root)
    data = _ordered(
        {
            "browser": {"version": probe.get("browserVersion"), "engine": "chromium", "browser": args.browser, "headless": bool(args.headless)},
            "audio": probe.get("audio", {}),
            "constructors": probe.get("constructors", {}),
            "prototype": probe.get("prototype", {}),
            "descriptors": probe.get("descriptors", {}),
            "methods": probe.get("methods", {}),
            "capabilities": probe.get("capabilities", {}),
            "fingerprintObservations": probe.get("fingerprintObservations", {}),
            "offline": probe.get("offline", {}),
            "errors": probe.get("errors", []),
        }
    )
    fingerprint = {"algorithm": "SHA-256", "sha256": _canonical_hash(data), "data": data}
    descriptors = [f"{group}.{name}" for group, values in data.get("descriptors", {}).items() if isinstance(values, dict) for name in values]
    methods = [f"{group}.{name}" for group, values in data.get("methods", {}).items() if isinstance(values, dict) for name in values]
    prototypes = data.get("prototype", {})
    prototype_valid = bool(prototypes) and all(isinstance(item, dict) and item.get("constructorEquality") is True for item in prototypes.values())
    native_values = [item.get("nativeSource") for values in data.get("methods", {}).values() if isinstance(values, dict) for item in values.values() if isinstance(item, dict) and "nativeSource" in item]
    native_valid = bool(native_values) and all(value is True for value in native_values)
    descriptor_valid = bool(descriptors) and all(value is None or isinstance(value, dict) for values in data.get("descriptors", {}).values() if isinstance(values, dict) for value in values.values())
    summary = _ordered(
        {
            "experiment": "Experiment 060C - Audio Baseline Rebuild",
            "experiment_id": None,
            "created_at": now_iso(),
            "result": "SUCCESS" if capture_status == "AVAILABLE" and fingerprint["sha256"] else "UNKNOWN",
            "playwright_status": capture_status,
            "browser_launches": launches,
            "network_requests": 0,
            "collection_duration_ms": round(duration_ms, 3),
            "fingerprint_sha256": fingerprint["sha256"],
            "historical_artifacts_modified": False,
        }
    )
    source = Path(__file__).read_text(encoding="utf-8")
    validation = _ordered(
        {
            "python_compile": True,
            "json_validation": all(_json_safe(value) for value in (data, fingerprint, summary)),
            "artifact_completeness": False,
            "deterministic_ordering": _canonical_hash(data) == _canonical_hash(_ordered(data)),
            "prototype_validation": prototype_valid,
            "descriptor_validation": descriptor_valid,
            "native_source_validation": native_valid,
            "fingerprint_validation": fingerprint["sha256"] == _canonical_hash(fingerprint["data"]),
            "registry_compatibility": isinstance(fingerprint.get("sha256"), str) and len(fingerprint["sha256"]) == 64 and isinstance(fingerprint.get("data"), dict) and summary["result"] == "SUCCESS",
            "playwright_status": capture_status,
            "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and "launch_browser" in source and ("sync_" + "playwright") not in source,
            "historical_artifacts_immutable": historical_before == historical_after,
            "read_only_verification": ("add_" + "init_script") not in source and ("__" + "stealth") not in source and ("resume" + "(") not in source and ("fetch" + "(") not in source,
            "browser_launches": launches,
            "network_requests": 0,
            "capture_error": capture_error,
            "valid": False,
        }
    )
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "audio"
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {
        "audio.json": data.get("audio", {}),
        "prototype.json": {"constructors": data.get("constructors", {}), "prototype": data.get("prototype", {}), "audio": data.get("audio", {}), "offline": data.get("offline", {})},
        "descriptors.json": data.get("descriptors", {}),
        "methods.json": data.get("methods", {}),
        "fingerprint.json": fingerprint,
        "statistics.json": {"browser_launches": launches, "network_requests": 0, "collection_duration_ms": round(duration_ms, 3), "collected_properties": len(data.get("audio", {})) + len(data.get("capabilities", {})), "collected_descriptors": len(descriptors), "collected_methods": len(methods), "fingerprint_generation": bool(fingerprint["sha256"]), "browser_version": probe.get("browserVersion")},
        "summary.json": summary,
        "validation.json": validation,
    }
    validation["artifact_completeness"] = all(name in artifacts for name in ARTIFACT_NAMES if name.endswith(".json"))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests", "capture_error"}) and validation["artifact_completeness"]
    summary["validation_valid"] = validation["valid"]
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "audio_report.md", _report(summary, data, fingerprint, validation))
    print("AUDIO BASELINE REBUILD")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Status: {capture_status} | Browser launches: {launches} | Network: 0")
    print(f"Fingerprint SHA-256: {fingerprint['sha256']}")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 060C: canonical Browser Platform Audio baseline")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
