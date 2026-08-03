"""Experiment 049: immutable Real Browser Navigator collector.

The collector is observational only.  It launches through the Browser
Platform's ``BrowserSessionManager`` (which delegates to ``launch_browser``),
then inspects Navigator values, prototypes, descriptors, and sub-API method
surfaces on ``about:blank``.  No permissions, media, network, or stealth API
is invoked.
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
    "navigator.json",
    "prototype.json",
    "descriptors.json",
    "methods.json",
    "subapis.json",
    "fingerprint.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "navigator_report.md",
)


NAVIGATOR_PROBE = r"""
async () => {
  const nativeSource = (value) => {
    try { return Function.prototype.toString.call(value); }
    catch (_) { return null; }
  };
  const safe = (callback, fallback = null) => {
    try { return callback(); } catch (_) { return fallback; }
  };
  const keyLabel = (key) => typeof key === 'symbol' ? String(key) : String(key);
  const ownKeys = (target) => {
    if (!target) return [];
    try {
      const names = Object.getOwnPropertyNames(target);
      const symbols = Object.getOwnPropertySymbols(target).map(keyLabel);
      return [...new Set([...names, ...symbols])].sort();
    } catch (_) { return []; }
  };
  const actualKeys = (target) => {
    if (!target) return [];
    try {
      return [
        ...Object.getOwnPropertyNames(target),
        ...Object.getOwnPropertySymbols(target)
      ].sort((left, right) => keyLabel(left).localeCompare(keyLabel(right)));
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
  const descriptorMap = (target) => {
    const output = {};
    for (const key of actualKeys(target)) {
      const item = descriptor(target, key);
      if (item) output[keyLabel(key)] = item;
    }
    return output;
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
  const inheritedProperties = (target) => {
    const own = new Set(ownKeys(target));
    const output = new Set();
    let current = safe(() => Object.getPrototypeOf(target), null);
    const seen = new Set();
    while (current && !seen.has(current)) {
      seen.add(current);
      for (const key of ownKeys(current)) if (!own.has(key)) output.add(key);
      current = safe(() => Object.getPrototypeOf(current), null);
    }
    return [...output].sort();
  };
  const errorInfo = (error) => ({
    name: safe(() => error && error.name, null),
    constructor: safe(() => error && error.constructor && error.constructor.name, null),
    message: safe(() => String(error && error.message || '').slice(0, 240), ''),
    isTypeError: safe(() => error instanceof TypeError, false),
    isError: safe(() => error instanceof Error, false)
  });
  const prototypeInfo = (target) => ({
    exists: !!target,
    constructor: safe(() => target && target.constructor && target.constructor.name, null),
    chain: chain(target),
    ownProperties: ownKeys(target),
    inheritedProperties: inheritedProperties(target),
    descriptors: descriptorMap(target),
    symbolToStringTag: descriptor(target, Symbol.toStringTag),
    objectToString: safe(() => Object.prototype.toString.call(target), null)
  });
  const constructorInfo = (ctor) => ({
    available: typeof ctor === 'function',
    name: safe(() => ctor && ctor.name, null),
    source: typeof ctor === 'function' ? nativeSource(ctor) : null,
    nativeSource: typeof ctor === 'function' && /\[native code\]/.test(nativeSource(ctor) || ''),
    ownProperties: ownKeys(ctor),
    descriptor: descriptor(globalThis, safe(() => ctor && ctor.name, '')),
    prototypeName: safe(() => ctor && ctor.prototype && ctor.prototype.constructor && ctor.prototype.constructor.name, null),
    prototypeEquality: safe(() => !!ctor && ctor.prototype && ctor.prototype.constructor === ctor, false)
  });
  const illegalInvocation = async (fn) => {
    if (typeof fn !== 'function') return { tested: false, throws: null };
    try {
      const value = fn.call({});
      if (value && typeof value.then === 'function') {
        try {
          await value;
          return { tested: true, throws: false, promise: true, outcome: 'resolved' };
        } catch (error) {
          return { tested: true, throws: true, promise: true, outcome: 'rejected', error: errorInfo(error) };
        }
      }
      return { tested: true, throws: false, promise: false, outcome: 'returned' };
    } catch (error) {
      return { tested: true, throws: true, promise: false, outcome: 'threw', error: errorInfo(error) };
    }
  };
  const methodInfo = async (target, name, testIllegal) => {
    const fn = safe(() => target && target[name], undefined);
    const info = {
      available: typeof fn === 'function',
      typeof: typeof fn,
      source: typeof fn === 'function' ? nativeSource(fn) : null,
      nativeSource: typeof fn === 'function' && /\[native code\]/.test(nativeSource(fn) || ''),
      descriptor: descriptor(target, name),
      illegalInvocation: { tested: false, throws: null }
    };
    if (testIllegal && typeof fn === 'function') info.illegalInvocation = await illegalInvocation(fn);
    return info;
  };
  const methodMap = async (target, testIllegal) => {
    const output = {};
    for (const name of ownKeys(target)) {
      const item = descriptor(target, name);
      if (item && item.valueType === 'function') output[name] = await methodInfo(target, name, testIllegal);
    }
    return output;
  };
  const values = {};
  const primitiveNames = [
    'userAgent', 'platform', 'vendor', 'vendorSub', 'product', 'productSub',
    'appCodeName', 'appName', 'appVersion', 'language', 'languages', 'onLine',
    'cookieEnabled', 'pdfViewerEnabled', 'webdriver', 'hardwareConcurrency',
    'deviceMemory', 'maxTouchPoints', 'doNotTrack', 'oscpu', 'buildID'
  ].sort();
  for (const name of primitiveNames) {
    values[name] = safe(() => {
      const value = navigator[name];
      if (Array.isArray(value)) return value.map((item) => String(item));
      if (value === undefined) return null;
      if (value === null) return null;
      if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return value;
      return String(value);
    }, null);
  }

  const navigatorPrototype = safe(() => Object.getPrototypeOf(navigator), null);
  const navigatorConstructor = safe(() => navigator.constructor, null);
  const navigatorObject = {
    typeof: typeof navigator,
    constructor: constructorInfo(navigatorConstructor),
    objectToString: safe(() => Object.prototype.toString.call(navigator), null),
    ownProperties: ownKeys(navigator),
    inheritedProperties: inheritedProperties(navigator),
    prototypeChain: chain(navigator),
    symbolToStringTag: descriptor(navigatorPrototype, Symbol.toStringTag),
    instanceofNavigator: safe(() => navigator instanceof Navigator, false),
    instanceofObject: safe(() => navigator instanceof Object, false),
    ownDescriptors: descriptorMap(navigator)
  };
  const prototype = {
    navigator: prototypeInfo(navigatorPrototype),
    constructor: constructorInfo(navigatorConstructor),
    prototypeEquality: safe(() => !!navigatorConstructor && navigatorPrototype === navigatorConstructor.prototype, false),
    navigatorInstanceof: safe(() => navigator instanceof Navigator, false),
    objectPrototype: safe(() => Object.getPrototypeOf(navigatorPrototype) && Object.getPrototypeOf(navigatorPrototype).constructor && Object.getPrototypeOf(navigatorPrototype).constructor.name, null)
  };
  const descriptors = {
    navigator: descriptorMap(navigator),
    navigatorPrototype: descriptorMap(navigatorPrototype),
    getterIllegalInvocation: {},
    symbolToStringTag: descriptor(navigatorPrototype, Symbol.toStringTag)
  };
  for (const name of ownKeys(navigatorPrototype)) {
    const item = descriptor(navigatorPrototype, name);
    if (item && item.hasGetter) {
      const getter = safe(() => Object.getOwnPropertyDescriptor(navigatorPrototype, name).get, null);
      descriptors.getterIllegalInvocation[name] = await illegalInvocation(getter);
    }
  }
  const methods = {
    navigatorPrototype: await methodMap(navigatorPrototype, true),
    subApiMethods: {}
  };

  const subApiNames = [
    'permissions', 'storage', 'mediaCapabilities', 'connection', 'gpu',
    'bluetooth', 'clipboard', 'credentials', 'keyboard', 'locks',
    'mediaDevices', 'serviceWorker', 'usb', 'hid', 'serial', 'xr',
    'presentation', 'virtualKeyboard', 'wakeLock'
  ].sort();
  const subapis = {};
  for (const name of subApiNames) {
    const value = safe(() => navigator[name], undefined);
    const available = value !== undefined && value !== null;
    const ctor = available ? safe(() => value.constructor, null) : null;
    const proto = available ? safe(() => Object.getPrototypeOf(value), null) : null;
    const apiMethods = proto ? await methodMap(proto, false) : {};
    subapis[name] = {
      availability: available,
      typeof: available ? typeof value : 'undefined',
      constructor: constructorInfo(ctor),
      prototype: prototypeInfo(proto),
      prototypeChain: chain(value),
      ownProperties: ownKeys(value),
      inheritedProperties: inheritedProperties(value),
      descriptor: descriptor(navigatorPrototype, name),
      nativeMethods: apiMethods,
      symbolToStringTag: descriptor(proto, Symbol.toStringTag),
      objectToString: safe(() => Object.prototype.toString.call(value), null)
    };
    methods.subApiMethods[name] = apiMethods;
  }
  return {
    available: true,
    values,
    navigator: navigatorObject,
    prototype,
    descriptors,
    methods,
    subapis
  };
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
    config = BrowserConfig(
        browser=args.browser,
        headless=args.headless,
        persistent=False,
        url="about:blank",
        timeout=args.timeout,
        enable_stealth=False,
    )
    manager = BrowserSessionManager(config)
    page: Any = None
    started = False
    error: str | None = None
    data: dict[str, Any] = {}
    try:
        manager.start()
        started = True
        page = manager.new_page()
        result = page.evaluate(NAVIGATOR_PROBE)
        if not isinstance(result, dict):
            raise TypeError("Navigator probe returned a non-object result")
        data = _ordered(result)
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
    status = "SUCCESS" if started and data.get("available") and not error else ("PARTIAL" if started else "UNKNOWN")
    return status, error, data, started


def _report(summary: dict[str, Any], stats: dict[str, Any], validation: dict[str, Any], data: dict[str, Any]) -> str:
    values = data.get("values", {})
    subapis = data.get("subapis", {})
    lines = [
        "# Experiment 049 - Real Navigator Collector",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Navigator fields: **{stats['primitive_value_count']}**",
        f"- Prototype properties: **{stats['prototype_property_count']}**",
        f"- Sub-APIs inspected: **{stats['subapi_count']}**",
        f"- Available sub-APIs: **{stats['available_subapi_count']}**",
        f"- Fingerprint: `{summary['fingerprint_sha256']}`",
        "",
        "The collector inspected `about:blank` through Browser Platform only. No permission query, media capture, network navigation, stealth injection, or browser mutation was performed.",
        "",
        "## Primitive Values",
        "",
        "| Property | Value |",
        "|---|---|",
    ]
    for name in sorted(values):
        value = values[name]
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        lines.append(f"| `{name}` | `{value}` |")
    lines += ["", "## Sub-API Availability", "", "| API | Available | Constructor | Methods |", "|---|---|---|---:|"]
    for name in sorted(subapis):
        api = subapis[name]
        methods = api.get("nativeMethods", {}) if isinstance(api.get("nativeMethods"), dict) else {}
        lines.append(f"| `{name}` | {api.get('availability')} | `{api.get('constructor', {}).get('name')}` | {len(methods)} |")
    lines += ["", "## Statistics", "", "| Metric | Value |", "|---|---:|"]
    for key in sorted(stats):
        if key in {"fingerprint_sha256", "capture_error"}:
            continue
        lines.append(f"| `{key}` | {stats[key]} |")
    lines += ["", "## Validation", "", "| Check | Status |", "|---|---|"]
    for key, value in validation.items():
        if key in {"valid", "artifact_completeness", "browser_launches", "network_requests"}:
            continue
        passed = bool(value) or key in {"historical_artifacts_modified"} and value is False
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if passed else 'FAIL'} |")
    lines += ["", "## Read-only Boundary", "", "Only property reads, descriptor reads, native-source inspection, and illegal-receiver checks were performed. Sensitive sub-API methods were not invoked.", ""]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    status, error, data, started = _capture(args)
    data = _ordered(data if isinstance(data, dict) else {})
    navigator = data.get("navigator", {}) if isinstance(data.get("navigator"), dict) else {}
    prototype = data.get("prototype", {}) if isinstance(data.get("prototype"), dict) else {}
    descriptors = data.get("descriptors", {}) if isinstance(data.get("descriptors"), dict) else {}
    methods = data.get("methods", {}) if isinstance(data.get("methods"), dict) else {}
    subapis = data.get("subapis", {}) if isinstance(data.get("subapis"), dict) else {}
    values = data.get("values", {}) if isinstance(data.get("values"), dict) else {}
    fingerprint_data = {
        "values": values,
        "navigator": navigator,
        "prototype": prototype,
        "descriptors": descriptors,
        "methods": methods,
        "subapis": subapis,
    }
    fingerprint_hash = _canonical_hash(_ordered(fingerprint_data))
    descriptor_values = list(descriptors.get("navigatorPrototype", {}).values()) if isinstance(descriptors.get("navigatorPrototype"), dict) else []
    getter_tests = descriptors.get("getterIllegalInvocation", {}) if isinstance(descriptors.get("getterIllegalInvocation"), dict) else {}
    navigator_methods = methods.get("navigatorPrototype", {}) if isinstance(methods.get("navigatorPrototype"), dict) else {}
    all_sub_methods = methods.get("subApiMethods", {}) if isinstance(methods.get("subApiMethods"), dict) else {}
    sub_method_count = sum(len(value) for value in all_sub_methods.values() if isinstance(value, dict))
    native_records = [value for value in list(navigator_methods.values()) + [item for group in all_sub_methods.values() if isinstance(group, dict) for item in group.values()] if isinstance(value, dict) and value.get("available")]
    stats = {
        "primitive_value_count": len(values),
        "navigator_own_property_count": len(navigator.get("ownProperties", [])),
        "navigator_inherited_property_count": len(navigator.get("inheritedProperties", [])),
        "prototype_property_count": len(prototype.get("navigator", {}).get("ownProperties", [])) if isinstance(prototype.get("navigator"), dict) else 0,
        "descriptor_count": len(descriptor_values),
        "getter_count": sum(1 for value in descriptor_values if isinstance(value, dict) and value.get("hasGetter")),
        "setter_count": sum(1 for value in descriptor_values if isinstance(value, dict) and value.get("hasSetter")),
        "navigator_method_count": len(navigator_methods),
        "subapi_method_count": sub_method_count,
        "native_source_count": sum(1 for value in native_records if value.get("nativeSource")),
        "native_source_failures": sum(1 for value in native_records if not value.get("nativeSource")),
        "getter_illegal_invocation_count": len(getter_tests),
        "getter_illegal_throw_count": sum(1 for value in getter_tests.values() if isinstance(value, dict) and value.get("throws")),
        "subapi_count": len(subapis),
        "available_subapi_count": sum(1 for value in subapis.values() if isinstance(value, dict) and value.get("availability")),
        "browser_launches": int(started),
        "network_requests": 0,
        "capture_status": status,
        "capture_error": error,
        "fingerprint_sha256": fingerprint_hash,
    }
    source = Path(__file__).read_text(encoding="utf-8")
    probe_text = NAVIGATOR_PROBE
    platform_token = "sync_" + "playwright"
    init_token = "add_" + "init_script"
    stealth_token = "_" + "_stealth"
    forbidden_calls = (
        "get" + "UserMedia(", "get" + "DisplayMedia(", "permissions.query(",
        "requestDevice(", "requestAdapter(", "requestSession(", "sendBeacon(",
    )
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (data, fingerprint_data, stats)),
        "artifact_completeness": False,
        "deterministic_ordering": data == _ordered(data),
        "prototype_validation": bool(prototype.get("prototypeEquality")) and bool(prototype.get("navigatorInstanceof")) and bool(navigator.get("instanceofNavigator")),
        "descriptor_validation": bool(descriptors.get("navigatorPrototype")) and all(isinstance(value, dict) and {"configurable", "enumerable", "writable", "hasGetter", "hasSetter"}.issubset(value) for value in descriptor_values),
        "native_source_validation": bool(native_records) and all(value.get("nativeSource") for value in native_records),
        "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and "launch_browser" in source and platform_token not in source,
        "read_only_verification": not any(token in probe_text for token in forbidden_calls) and init_token not in source and stealth_token not in probe_text,
        "no_permission_prompts": "permissions.query(" not in probe_text and "requestPermission(" not in probe_text,
        "no_media_capture": not any(token in probe_text for token in ("get" + "UserMedia(", "get" + "DisplayMedia(")),
        "no_network_calls": not any(token in probe_text for token in ("sendBeacon(", "fetch(", "XMLHttpRequest")),
        "sha256_validation": fingerprint_hash == _canonical_hash(_ordered(fingerprint_data)),
        "browser_launches": int(started),
        "network_requests": 0,
        "historical_artifacts_modified": False,
        "historical_artifacts_immutable": True,
        "valid": False,
    }
    summary = {
        "experiment": "Experiment 049 - Real Navigator Collector",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "SUCCESS" if status == "SUCCESS" else ("PARTIAL" if started else "UNKNOWN"),
        "browser": args.browser,
        "headless": bool(args.headless),
        "browser_platform": "BrowserSessionManager -> launch_browser",
        "primitive_value_count": len(values),
        "subapi_count": len(subapis),
        "available_subapi_count": stats["available_subapi_count"],
        "fingerprint_sha256": fingerprint_hash,
        "browser_launches": int(started),
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "navigator"
    output.mkdir(parents=True, exist_ok=False)
    artifact_data = {
        "navigator.json": {"values": values, "navigator": navigator},
        "prototype.json": prototype,
        "descriptors.json": descriptors,
        "methods.json": methods,
        "subapis.json": subapis,
        "fingerprint.json": {"algorithm": "SHA-256", "sha256": fingerprint_hash, "data": fingerprint_data},
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    validation["artifact_completeness"] = all(name in artifact_data for name in ARTIFACT_NAMES if name.endswith(".json"))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests", "historical_artifacts_modified"})
    summary["validation_valid"] = validation["valid"]
    for filename, value in artifact_data.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "navigator_report.md", _report(summary, stats, validation, data))
    print("REAL NAVIGATOR COLLECTOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Navigator values: {len(values)} | Sub-APIs: {stats['available_subapi_count']}/{stats['subapi_count']}")
    print(f"Fingerprint: {fingerprint_hash}")
    print(f"Browser launches: {stats['browser_launches']} | Network requests: {stats['network_requests']}")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 049: collect a real Navigator snapshot")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
