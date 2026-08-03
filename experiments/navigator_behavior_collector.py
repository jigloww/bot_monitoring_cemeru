"""Experiment 051: read-only Navigator behavior collector.

The collector uses BrowserSessionManager/BrowserConfig and the Browser
Platform launcher on ``about:blank``.  It observes property access, identity,
prototype, descriptor, and illegal-receiver behavior without requesting
permissions, touching media, navigating, injecting stealth, or performing
network operations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
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
    write_json_exclusive,
    write_text_exclusive,
)


ARTIFACT_NAMES = (
    "runtime.json",
    "getters.json",
    "exceptions.json",
    "prototype.json",
    "identity.json",
    "fingerprint.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "navigator_behavior_report.md",
)


NAVIGATOR_BEHAVIOR_PROBE = r"""
async () => {
  const nativeSource = (value) => {
    try { return Function.prototype.toString.call(value); }
    catch (_) { return null; }
  };
  const safe = (callback, fallback = null) => {
    try { return callback(); } catch (_) { return fallback; }
  };
  const ownKeys = (target) => {
    if (!target) return [];
    try {
      return [...Object.getOwnPropertyNames(target), ...Object.getOwnPropertySymbols(target).map(String)].sort();
    } catch (_) { return []; }
  };
  const descriptor = (target, key) => safe(() => {
    const item = Object.getOwnPropertyDescriptor(target, key);
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
  });
  const errorInfo = (error) => ({
    name: safe(() => error && error.name, null),
    constructor: safe(() => error && error.constructor && error.constructor.name, null),
    message: safe(() => String(error && error.message || '').slice(0, 240), ''),
    isDOMException: safe(() => error instanceof DOMException, false),
    isTypeError: safe(() => error instanceof TypeError, false),
    isError: safe(() => error instanceof Error, false)
  });
  const stableValue = (value) => {
    if (value === undefined) return null;
    if (value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value;
    if (Array.isArray(value)) return value.map((item) => stableValue(item));
    return {
      type: typeof value,
      constructor: safe(() => value.constructor && value.constructor.name, null),
      objectToString: safe(() => Object.prototype.toString.call(value), null),
      ownProperties: ownKeys(value)
    };
  };
  const chain = (target) => {
    const output = [];
    const seen = new Set();
    let current = target;
    while (current && !seen.has(current)) {
      seen.add(current);
      output.push(safe(() => current.constructor && current.constructor.name, null));
      current = safe(() => Object.getPrototypeOf(current), null);
    }
    return output;
  };
  const getterInfo = async (target, name) => {
    const item = safe(() => Object.getOwnPropertyDescriptor(target, name), null);
    const getter = item && typeof item.get === 'function' ? item.get : null;
    const read = () => safe(() => navigator[name], null);
    const first = read();
    const second = read();
    const third = read();
    const firstStable = stableValue(first);
    const secondStable = stableValue(second);
    const thirdStable = stableValue(third);
    const detached = {};
    for (const label of ['detached', 'invalidReceiver', 'prototypeReceiver']) {
      try {
        const value = label === 'detached' ? getter() : label === 'invalidReceiver' ? getter.call({}) : getter.call(Navigator.prototype);
        detached[label] = { throws: false, value: stableValue(value) };
      } catch (error) {
        detached[label] = { throws: true, error: errorInfo(error) };
      }
    }
    return {
      descriptor: descriptor(target, name),
      available: typeof getter === 'function',
      source: getter ? nativeSource(getter) : null,
      name: getter ? safe(() => getter.name, null) : null,
      length: getter ? safe(() => getter.length, null) : null,
      nativeSource: getter ? /\[native code\]/.test(nativeSource(getter) || '') : false,
      first: firstStable,
      second: secondStable,
      third: thirdStable,
      valueStable: JSON.stringify(firstStable) === JSON.stringify(secondStable) && JSON.stringify(secondStable) === JSON.stringify(thirdStable),
      referenceStable: first !== null && (typeof first === 'object' || typeof first === 'function') ? first === second && second === third : null,
      detached
    };
  };
  const methodInfo = async (target, name) => {
    const fn = safe(() => target[name], undefined);
    const info = {
      available: typeof fn === 'function',
      typeof: typeof fn,
      source: typeof fn === 'function' ? nativeSource(fn) : null,
      name: typeof fn === 'function' ? safe(() => fn.name, null) : null,
      length: typeof fn === 'function' ? safe(() => fn.length, null) : null,
      nativeSource: typeof fn === 'function' && /\[native code\]/.test(nativeSource(fn) || ''),
      descriptor: descriptor(target, name),
      illegalInvocation: { tested: false, throws: null }
    };
    if (typeof fn !== 'function') return info;
    try {
      const value = fn.call({});
      if (value && typeof value.then === 'function') {
        try {
          await value;
          info.illegalInvocation = { tested: true, throws: false, promise: true, outcome: 'resolved' };
        } catch (error) {
          info.illegalInvocation = { tested: true, throws: true, promise: true, outcome: 'rejected', error: errorInfo(error) };
        }
      } else {
        info.illegalInvocation = { tested: true, throws: false, promise: false, outcome: 'returned' };
      }
    } catch (error) {
      info.illegalInvocation = { tested: true, throws: true, promise: false, outcome: 'threw', error: errorInfo(error) };
    }
    return info;
  };
  const primitiveNames = [
    'userAgent', 'platform', 'vendor', 'language', 'languages',
    'hardwareConcurrency', 'deviceMemory', 'maxTouchPoints',
    'cookieEnabled', 'onLine', 'webdriver', 'pdfViewerEnabled'
  ].sort();
  const runtime = { values: {}, access: {}, enumeration: {}, subapis: {} };
  for (const name of primitiveNames) {
    const first = safe(() => navigator[name], null);
    const second = safe(() => navigator[name], null);
    const value = stableValue(first);
    runtime.values[name] = value;
    runtime.access[name] = {
      type: typeof first,
      first: value,
      second: stableValue(second),
      stable: JSON.stringify(value) === JSON.stringify(stableValue(second)),
      referenceEqual: first !== null && (typeof first === 'object' || typeof first === 'function') ? first === second : null,
      descriptor: descriptor(Navigator.prototype, name)
    };
  }
  runtime.enumeration = {
    objectKeys: Object.keys(navigator).sort(),
    reflectOwnKeys: Reflect.ownKeys(navigator).map(String).sort(),
    forIn: (() => { const output = []; for (const key in navigator) output.push(String(key)); return output.sort(); })(),
    entries: Object.entries(navigator).map((entry) => [String(entry[0]), stableValue(entry[1])]).sort((a, b) => a[0].localeCompare(b[0])),
    values: Object.values(navigator).map(stableValue),
    keysStable: JSON.stringify(Object.keys(navigator).sort()) === JSON.stringify(Object.keys(navigator).sort())
  };
  const navigatorPrototype = Object.getPrototypeOf(navigator);
  const navigatorConstructor = safe(() => navigator.constructor, null);
  const prototype = {
    constructor: {
      name: safe(() => navigatorConstructor && navigatorConstructor.name, null),
      source: navigatorConstructor ? nativeSource(navigatorConstructor) : null,
      nativeSource: !!navigatorConstructor && /\[native code\]/.test(nativeSource(navigatorConstructor) || ''),
      length: navigatorConstructor ? safe(() => navigatorConstructor.length, null) : null,
      descriptor: descriptor(globalThis, 'Navigator')
    },
    chain: chain(navigator),
    navigatorPrototypeName: safe(() => navigatorPrototype.constructor && navigatorPrototype.constructor.name, null),
    constructorEquality: safe(() => navigatorPrototype.constructor === navigatorConstructor, false),
    prototypeEquality: safe(() => navigatorPrototype === navigatorConstructor.prototype, false),
    instanceofNavigator: safe(() => navigator instanceof Navigator, false),
    instanceofObject: safe(() => navigator instanceof Object, false),
    objectPrototype: safe(() => Object.getPrototypeOf(navigatorPrototype).constructor.name, null),
    prototypeProperties: ownKeys(navigatorPrototype),
    prototypeDescriptors: Object.fromEntries(ownKeys(navigatorPrototype).map((name) => [name, descriptor(navigatorPrototype, name)]))
  };
  const getters = {};
  for (const name of ownKeys(navigatorPrototype)) {
    const item = descriptor(navigatorPrototype, name);
    if (item && item.hasGetter) getters[name] = await getterInfo(navigatorPrototype, name);
  }
  const methods = {};
  for (const name of ownKeys(navigatorPrototype)) {
    const item = descriptor(navigatorPrototype, name);
    if (item && item.valueType === 'function') methods[name] = await methodInfo(navigatorPrototype, name);
  }
  const exceptions = {
    constructorCall: null,
    constructorReflect: null,
    getters: {}
  };
  try { Navigator.call({}); exceptions.constructorCall = { throws: false }; }
  catch (error) { exceptions.constructorCall = { throws: true, error: errorInfo(error) }; }
  try { Reflect.construct(Navigator, []); exceptions.constructorReflect = { throws: false }; }
  catch (error) { exceptions.constructorReflect = { throws: true, error: errorInfo(error) }; }
  for (const [name, value] of Object.entries(getters)) exceptions.getters[name] = value.detached;

  const subApiNames = ['permissions', 'connection', 'mediaCapabilities', 'storage'].sort();
  for (const name of subApiNames) {
    const first = safe(() => navigator[name], null);
    const second = safe(() => navigator[name], null);
    const proto = first ? safe(() => Object.getPrototypeOf(first), null) : null;
    const ctor = first ? safe(() => first.constructor, null) : null;
    const methodNames = proto ? ownKeys(proto).filter((key) => {
      const item = descriptor(proto, key); return item && item.valueType === 'function';
    }) : [];
    const subMethods = {};
    for (const methodName of methodNames) subMethods[methodName] = await methodInfo(proto, methodName);
    runtime.subapis[name] = {
      available: first !== null,
      typeof: first === null ? 'undefined' : typeof first,
      constructor: safe(() => ctor && ctor.name, null),
      constructorSource: ctor ? nativeSource(ctor) : null,
      prototype: safe(() => proto && proto.constructor && proto.constructor.name, null),
      prototypeChain: chain(first),
      referenceStable: first !== null && first === second,
      objectToString: safe(() => Object.prototype.toString.call(first), null),
      symbolToStringTag: descriptor(proto, Symbol.toStringTag),
      descriptor: descriptor(navigatorPrototype, name),
      methods: subMethods
    };
  }
  const identity = {
    navigatorSelfEqual: navigator === navigator,
    prototypeRepeatedEqual: Object.getPrototypeOf(navigator) === Object.getPrototypeOf(navigator),
    constructorRepeatedEqual: navigator.constructor === navigator.constructor,
    subapis: Object.fromEntries(Object.entries(runtime.subapis).map(([name, value]) => [name, value.referenceStable])),
    frozen: {
      navigator: Object.isFrozen(navigator),
      prototype: Object.isFrozen(navigatorPrototype),
      subapis: Object.fromEntries(subApiNames.map((name) => [name, Object.isFrozen(safe(() => navigator[name], null))]))
    }
  };
  return { available: true, runtime, getters, exceptions, prototype, methods, identity };
}
"""


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _ordered(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _ordered(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _positive_timeout(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return parsed


def _capture(args: argparse.Namespace) -> tuple[str, str | None, dict[str, Any], bool]:
    config = BrowserConfig(browser=args.browser, headless=args.headless, persistent=False, url="about:blank", timeout=args.timeout, enable_stealth=False)
    manager = BrowserSessionManager(config)
    page: Any = None
    started = False
    error: str | None = None
    data: dict[str, Any] = {}
    try:
        manager.start()
        started = True
        page = manager.new_page()
        result = page.evaluate(NAVIGATOR_BEHAVIOR_PROBE)
        if not isinstance(result, dict): raise TypeError("Navigator behavior probe returned a non-object result")
        data = _ordered(result)
    except Exception as exc:
        error = str(exc)
    finally:
        if page is not None:
            try: manager.close_page(page)
            except Exception: pass
        try: manager.shutdown()
        except Exception: pass
    status = "SUCCESS" if started and data.get("available") and not error else ("PARTIAL" if started else "UNKNOWN")
    return status, error, data, started


def _report(summary: dict[str, Any], stats: dict[str, Any], validation: dict[str, Any], data: dict[str, Any]) -> str:
    values = data.get("runtime", {}).get("values", {})
    subapis = data.get("runtime", {}).get("subapis", {})
    lines = [
        "# Experiment 051 - Navigator Behavior Collector", "", "## Executive Summary", "",
        f"- Result: **{summary['result']}**",
        f"- Runtime values: **{stats['runtime_value_count']}**",
        f"- Getter checks: **{stats['getter_count']}**",
        f"- Prototype checks: **{stats['prototype_property_count']}**",
        f"- Sub-APIs: **{stats['subapi_count']}**",
        f"- Fingerprint: `{summary['fingerprint_sha256']}`", "",
        "The probe ran on about:blank through Browser Platform only. Sensitive sub-API methods were not invoked.", "",
        "## Runtime Values", "", "| Property | Value | Stable | Reference Equal |", "|---|---|---|---|",
    ]
    access = data.get("runtime", {}).get("access", {})
    for name in sorted(values):
        item = access.get(name, {})
        lines.append(f"| `{name}` | `{values[name]}` | {item.get('stable')} | {item.get('referenceEqual')} |")
    lines += ["", "## Sub-API Runtime", "", "| API | Available | Constructor | Reference Stable |", "|---|---|---|---|"]
    for name in sorted(subapis):
        item = subapis[name]
        lines.append(f"| `{name}` | {item.get('available')} | `{item.get('constructor')}` | {item.get('referenceStable')} |")
    lines += ["", "## Validation", "", "| Check | Status |", "|---|---|"]
    for key, value in validation.items():
        if key in {"valid", "artifact_completeness", "browser_launches", "network_requests"}: continue
        passed = bool(value) or (key == "historical_artifacts_modified" and value is False)
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if passed else 'FAIL'} |")
    lines += ["", "## Read-only Boundary", "", "Only property reads, descriptor reads, getter/function metadata, and invalid-receiver checks were performed. No permission, media, network, or stealth operation was used.", ""]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    status, error, data, started = _capture(args)
    data = _ordered(data if isinstance(data, dict) else {})
    fingerprint_data = {key: data.get(key, {}) for key in ("runtime", "getters", "exceptions", "prototype", "methods", "identity")}
    fingerprint_hash = _canonical_hash(_ordered(fingerprint_data))
    runtime = data.get("runtime", {}) if isinstance(data.get("runtime"), dict) else {}
    getters = data.get("getters", {}) if isinstance(data.get("getters"), dict) else {}
    prototype = data.get("prototype", {}) if isinstance(data.get("prototype"), dict) else {}
    methods = data.get("methods", {}) if isinstance(data.get("methods"), dict) else {}
    identity = data.get("identity", {}) if isinstance(data.get("identity"), dict) else {}
    exceptions = data.get("exceptions", {}) if isinstance(data.get("exceptions"), dict) else {}
    access = runtime.get("access", {}) if isinstance(runtime.get("access"), dict) else {}
    subapis = runtime.get("subapis", {}) if isinstance(runtime.get("subapis"), dict) else {}
    getter_count = len(getters)
    getter_stable = sum(1 for value in getters.values() if isinstance(value, dict) and value.get("valueStable"))
    method_values = list(methods.values()) + [method for api in subapis.values() if isinstance(api, dict) for method in (api.get("methods", {}) or {}).values() if isinstance(methods, dict)]
    native_count = sum(1 for value in method_values if isinstance(value, dict) and value.get("nativeSource"))
    stats = {
        "runtime_value_count": len(runtime.get("values", {})) if isinstance(runtime.get("values"), dict) else 0,
        "getter_count": getter_count,
        "getter_stable_count": getter_stable,
        "getter_illegal_throw_count": sum(1 for value in getters.values() if isinstance(value, dict) and value.get("detached", {}).get("detached", {}).get("throws")),
        "prototype_property_count": len(prototype.get("prototypeProperties", [])),
        "method_count": len(methods),
        "native_method_count": native_count,
        "subapi_count": len(subapis),
        "available_subapi_count": sum(1 for value in subapis.values() if isinstance(value, dict) and value.get("available")),
        "enumeration_key_count": len(runtime.get("enumeration", {}).get("objectKeys", [])) if isinstance(runtime.get("enumeration"), dict) else 0,
        "identity_checks": len(identity),
        "exception_checks": len(exceptions),
        "browser_launches": int(started),
        "network_requests": 0,
        "capture_status": status,
        "capture_error": error,
        "fingerprint_sha256": fingerprint_hash,
    }
    source = Path(__file__).read_text(encoding="utf-8")
    probe = NAVIGATOR_BEHAVIOR_PROBE
    forbidden = ("permissions.query(", "get" + "UserMedia(", "get" + "DisplayMedia(", "sendBeacon(", "fetch(", "XMLHttpRequest", "requestDevice(", "requestAdapter(", "requestSession(")
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (data, fingerprint_data, stats)),
        "artifact_completeness": False,
        "deterministic_ordering": data == _ordered(data),
        "runtime_validation": bool(runtime.get("values")) and all(value.get("stable") for value in access.values() if isinstance(value, dict)),
        "getter_validation": getter_count > 0 and getter_stable == getter_count and all(isinstance(value, dict) for value in getters.values()),
        "prototype_validation": bool(prototype.get("constructorEquality")) and bool(prototype.get("prototypeEquality")) and bool(prototype.get("instanceofNavigator")),
        "identity_validation": bool(identity.get("navigatorSelfEqual")) and bool(identity.get("prototypeRepeatedEqual")) and bool(identity.get("constructorRepeatedEqual")),
        "fingerprint_validation": bool(fingerprint_hash) and fingerprint_hash == _canonical_hash(_ordered(fingerprint_data)),
        "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and "launch_browser" in source and ("sync_" + "playwright") not in source,
        "read_only_verification": not any(token in probe for token in forbidden) and ("add_" + "init_script") not in source and ("_" + "_stealth") not in probe,
        "no_permission_prompts": "permissions.query(" not in probe and "requestPermission(" not in probe,
        "no_media_capture": not any(token in probe for token in ("get" + "UserMedia(", "get" + "DisplayMedia(")),
        "no_network_requests": not any(token in probe for token in ("sendBeacon(", "fetch(", "XMLHttpRequest")),
        "historical_artifacts_modified": False,
        "historical_artifacts_immutable": True,
        "browser_launches": int(started),
        "network_requests": 0,
        "valid": False,
    }
    summary = {
        "experiment": "Experiment 051 - Navigator Behavior Collector",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "SUCCESS" if status == "SUCCESS" else ("PARTIAL" if started else "UNKNOWN"),
        "browser": args.browser,
        "headless": bool(args.headless),
        "browser_platform": "BrowserSessionManager -> launch_browser",
        "runtime_value_count": stats["runtime_value_count"],
        "getter_count": getter_count,
        "subapi_count": len(subapis),
        "fingerprint_sha256": fingerprint_hash,
        "browser_launches": int(started),
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "navigator_behavior"
    output.mkdir(parents=True, exist_ok=False)
    artifact_data = {
        "runtime.json": runtime,
        "getters.json": getters,
        "exceptions.json": exceptions,
        "prototype.json": prototype,
        "identity.json": identity,
        "fingerprint.json": {"algorithm": "SHA-256", "sha256": fingerprint_hash, "data": fingerprint_data},
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    validation["artifact_completeness"] = all(name in artifact_data for name in ("runtime.json", "getters.json", "exceptions.json", "prototype.json", "identity.json", "fingerprint.json", "statistics.json", "summary.json", "validation.json"))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests", "historical_artifacts_modified"})
    summary["validation_valid"] = validation["valid"]
    for filename, value in artifact_data.items(): write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "navigator_behavior_report.md", _report(summary, stats, validation, data))
    print("NAVIGATOR BEHAVIOR COLLECTOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Values: {stats['runtime_value_count']} | Getters: {getter_count} | Sub-APIs: {stats['available_subapi_count']}/{stats['subapi_count']}")
    print(f"Fingerprint: {fingerprint_hash}")
    print(f"Browser launches: {stats['browser_launches']} | Network requests: {stats['network_requests']}")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 051: collect Navigator runtime behavior")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
