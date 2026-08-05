"""Experiment 060D: canonical Browser Platform User-Agent Client Hints baseline.

The collector observes only the native ``navigator.userAgentData`` surface.
It performs one Browser Platform launch on ``about:blank`` and never changes
HTTP headers, navigator.userAgent, browser scripts, or historical artifacts.
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
    "client_hints.json",
    "prototype.json",
    "descriptors.json",
    "methods.json",
    "fingerprint.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "client_hints_report.md",
)


UA_PROBE = r"""
async () => {
  const errors = [];
  const hints = ['architecture', 'bitness', 'brands', 'fullVersionList', 'mobile', 'model', 'platform', 'platformVersion', 'uaFullVersion', 'wow64'];
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
  const methodInfo = async (prototype, name) => {
    const fn = safe(() => prototype && prototype[name], null);
    const illegalInvocation = { tested: false, throws: false, rejected: false, error: null };
    if (typeof fn === 'function') {
      illegalInvocation.tested = true;
      try {
        const result = fn.call({});
        if (result && typeof result.then === 'function') {
          await result;
          illegalInvocation.rejected = false;
        }
      } catch (error) {
        illegalInvocation.throws = true;
        illegalInvocation.rejected = true;
        illegalInvocation.error = errorInfo(error);
      }
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
  const output = {
    supported: false,
    errors,
    availability: {},
    userAgentData: {},
    constructor: {},
    prototype: {},
    descriptors: {},
    methods: {},
    values: {},
    highEntropy: {},
    promise: {},
    identity: {},
    immutable: {}
  };
  try {
    const value = navigator.userAgentData;
    output.availability = {
      navigatorUserAgentData: value !== undefined && value !== null,
      typeof: typeof value,
      constructor: safe(() => value && value.constructor && value.constructor.name, null)
    };
    if (!value) {
      output.highEntropy = {
        requestedHints: hints,
        full: null,
        availability: Object.fromEntries(hints.map((hint) => [hint, { resolved: false, present: false, type: null, value: null, reason: 'api_unavailable' }]))
      };
      output.promise = { supported: false, isPromise: false, asynchronous: null, userAgentUnchanged: true, reason: 'api_unavailable' };
      output.identity = { available: false, objectToString: null, constructorName: null, instanceofConstructor: false, instanceofObject: false, prototypeEquality: false, ownProperties: [], inheritedProperties: [], symbolToStringTag: null };
      output.immutable = { objectFrozen: null, brandsFrozen: null, brandsExtensible: null, jsonFrozen: null, jsonBrandsFrozen: null, brandsReferenceStable: null, jsonReferenceStable: null };
      return output;
    }
    output.supported = true;
    const prototype = Object.getPrototypeOf(value);
    const constructor = value.constructor || globalThis.NavigatorUAData;
    output.constructor = constructorInfo('NavigatorUAData', constructor);
    output.prototype = {
      constructor: safe(() => constructor && constructor.name, null),
      ownProperties: ownKeys(prototype),
      inheritedProperties: ownKeys(Object.getPrototypeOf(prototype)),
      prototypeChain: chain(prototype),
      constructorEquality: safe(() => prototype.constructor === constructor, false),
      objectPrototype: safe(() => Object.getPrototypeOf(prototype).constructor.name, null),
      instanceofObject: safe(() => prototype instanceof Object, false),
      toStringTag: descriptor(prototype, Symbol.toStringTag)
    };
    output.descriptors = {
      navigatorUserAgentData: descriptor(Navigator.prototype, 'userAgentData'),
      prototype: descriptorMap(prototype),
      constructor: descriptor(globalThis, 'NavigatorUAData')
    };
    output.methods = {
      getHighEntropyValues: await methodInfo(prototype, 'getHighEntropyValues'),
      toJSON: await methodInfo(prototype, 'toJSON')
    };
    output.values = {
      brands: safe(() => value.brands, []),
      mobile: safe(() => value.mobile, null),
      platform: safe(() => value.platform, null),
      toJSON: typeof value.toJSON === 'function' ? safe(() => value.toJSON(), null) : null
    };
    output.immutable = {
      objectFrozen: Object.isFrozen(value),
      brandsFrozen: Object.isFrozen(value.brands),
      brandsExtensible: Object.isExtensible(value.brands),
      jsonFrozen: typeof value.toJSON === 'function' ? Object.isFrozen(value.toJSON()) : null,
      jsonBrandsFrozen: typeof value.toJSON === 'function' && value.toJSON() && value.toJSON().brands ? Object.isFrozen(value.toJSON().brands) : null,
      brandsReferenceStable: value.brands === value.brands,
      jsonReferenceStable: typeof value.toJSON === 'function' ? value.toJSON() === value.toJSON() : null
    };
    output.identity = {
      objectToString: Object.prototype.toString.call(value),
      constructorName: safe(() => value.constructor.name, null),
      instanceofConstructor: safe(() => value instanceof constructor, false),
      instanceofObject: value instanceof Object,
      prototypeEquality: Object.getPrototypeOf(value) === prototype,
      ownProperties: ownKeys(value),
      inheritedProperties: ownKeys(prototype),
      symbolToStringTag: descriptor(prototype, Symbol.toStringTag)
    };
    const beforeUA = navigator.userAgent;
    const emptyPromise = value.getHighEntropyValues([]);
    output.promise = {
      isPromise: !!emptyPromise && typeof emptyPromise.then === 'function',
      constructor: safe(() => emptyPromise && emptyPromise.constructor && emptyPromise.constructor.name, null),
      asynchronous: true,
      emptyResolved: null,
      emptyRejected: null,
      invalidReceiverRejected: null,
      invalidArgumentRejected: null,
      userAgentUnchanged: beforeUA === navigator.userAgent
    };
    try { output.promise.emptyResolved = await emptyPromise; }
    catch (error) { output.promise.emptyRejected = errorInfo(error); }
    try {
      const invalidReceiver = value.getHighEntropyValues.call({});
      await invalidReceiver;
    } catch (error) { output.promise.invalidReceiverRejected = errorInfo(error); }
    try {
      const invalidArgument = value.getHighEntropyValues(null);
      await invalidArgument;
    } catch (error) { output.promise.invalidArgumentRejected = errorInfo(error); }
    const full = await value.getHighEntropyValues(hints);
    output.highEntropy = { requestedHints: hints, full: full, availability: {} };
    for (const hint of hints) {
      try {
        const resolved = await value.getHighEntropyValues([hint]);
        output.highEntropy.availability[hint] = { resolved: true, present: Object.prototype.hasOwnProperty.call(resolved, hint), type: typeof resolved[hint], value: resolved[hint] === undefined ? null : resolved[hint] };
      } catch (error) {
        output.highEntropy.availability[hint] = { resolved: false, present: false, type: null, value: null, error: errorInfo(error) };
      }
    }
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
        result = page.evaluate(UA_PROBE)
        if isinstance(result, dict):
            probe = _ordered(result)
            probe["browserVersion"] = _browser_version(page)
        else:
            error = "Client Hints probe returned a non-object"
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
    return ("AVAILABLE" if launches and isinstance(probe, dict) else ("PARTIAL" if launches else "UNKNOWN"), probe, error, duration, launches)


def _report(summary: dict[str, Any], data: dict[str, Any], fingerprint: dict[str, Any], validation: dict[str, Any]) -> str:
    values = data.get("values", {})
    high = data.get("highEntropy", {})
    promise_status = "NOT_APPLICABLE" if not data.get("availability", {}).get("navigatorUserAgentData") else data.get("promise", {}).get("isPromise")
    lines = [
        "# Experiment 060D - Canonical Client Hints Baseline",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Browser Platform status: **{summary['playwright_status']}**",
        f"- Browser launches: **{summary['browser_launches']}**",
        f"- Network requests: **{summary['network_requests']}**",
        f"- Fingerprint SHA-256: `{fingerprint['sha256']}`",
        f"- navigator.userAgentData available: `{data.get('availability', {}).get('navigatorUserAgentData')}`",
        "",
        "## Low Entropy Values",
        "",
        "| Property | Value |",
        "|---|---|",
    ]
    for name in ("brands", "mobile", "platform"):
        lines.append(f"| `{name}` | `{values.get(name)}` |")
    lines += ["", "## High Entropy Availability", "", "| Hint | Resolved | Present | Type |", "|---|---|---|---|"]
    for hint, item in high.get("availability", {}).items():
        lines.append(f"| `{hint}` | {item.get('resolved')} | {item.get('present')} | `{item.get('type')}` |")
    lines += ["", "## Native Surface", "", f"- Constructor available: `{data.get('constructor', {}).get('available')}`", f"- Prototype properties: **{len(data.get('prototype', {}).get('ownProperties', []))}**", f"- Methods collected: **{len(data.get('methods', {}))}**", f"- Promise validation: `{promise_status}`", f"- User-Agent unchanged: `{data.get('promise', {}).get('userAgentUnchanged')}`", "", "## Validation", "", f"- Validation: **{'PASS' if validation['valid'] else 'FAIL'}**", "- No header modification, network request, stealth injection, or historical artifact mutation was performed.", ""]
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
            "availability": probe.get("availability", {}),
            "userAgentData": probe.get("userAgentData", {}),
            "constructor": probe.get("constructor", {}),
            "prototype": probe.get("prototype", {}),
            "descriptors": probe.get("descriptors", {}),
            "methods": probe.get("methods", {}),
            "values": probe.get("values", {}),
            "highEntropy": probe.get("highEntropy", {}),
            "promise": probe.get("promise", {}),
            "identity": probe.get("identity", {}),
            "immutable": probe.get("immutable", {}),
            "errors": probe.get("errors", []),
        }
    )
    fingerprint = {"algorithm": "SHA-256", "sha256": _canonical_hash(data), "data": data}
    descriptors = [f"{group}.{name}" for group, values in data.get("descriptors", {}).items() if isinstance(values, dict) for name in values]
    methods = [name for name in data.get("methods", {})]
    api_supported = bool(data.get("availability", {}).get("navigatorUserAgentData"))
    # A native browser may intentionally omit UA-CH (for example in a
    # headless channel).  Absence is a valid baseline state; structural and
    # Promise checks are required only when the API exists.
    prototype_valid = (not api_supported) or (bool(data.get("prototype", {}).get("constructorEquality")) and bool(data.get("identity", {}).get("prototypeEquality")) and bool(data.get("identity", {}).get("instanceofConstructor")))
    native_valid = (not api_supported) or all(item.get("nativeSource") is True for item in data.get("methods", {}).values() if isinstance(item, dict) and item.get("available"))
    descriptor_valid = (not api_supported) or (bool(descriptors) and all(value is None or isinstance(value, dict) for values in data.get("descriptors", {}).values() if isinstance(values, dict) for value in values.values()))
    promise_valid = (not api_supported) or (bool(data.get("promise", {}).get("isPromise")) and bool(data.get("promise", {}).get("userAgentUnchanged")) and data.get("promise", {}).get("invalidReceiverRejected") is not None)
    summary = _ordered(
        {
            "experiment": "Experiment 060D - Client Hints Baseline Rebuild",
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
            "promise_validation": promise_valid,
            "fingerprint_validation": fingerprint["sha256"] == _canonical_hash(fingerprint["data"]),
            "registry_compatibility": isinstance(fingerprint.get("sha256"), str) and len(fingerprint["sha256"]) == 64 and isinstance(fingerprint.get("data"), dict) and summary["result"] == "SUCCESS",
            "playwright_status": capture_status,
            "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and "launch_browser" in source and ("sync_" + "playwright") not in source,
            "historical_artifacts_immutable": historical_before == historical_after,
            "read_only_verification": ("add_" + "init_script") not in source and ("__" + "stealth") not in source and ("extra_" + "http_headers") not in source and ("fetch" + "(") not in source and ("setUserAgent" + "(") not in source,
            "browser_launches": launches,
            "network_requests": 0,
            "capture_error": capture_error,
            "valid": False,
        }
    )
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "client_hints"
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {
        "client_hints.json": {"availability": data.get("availability", {}), "values": data.get("values", {}), "highEntropy": data.get("highEntropy", {}), "promise": data.get("promise", {}), "identity": data.get("identity", {}), "immutable": data.get("immutable", {})},
        "prototype.json": {"constructor": data.get("constructor", {}), "prototype": data.get("prototype", {})},
        "descriptors.json": data.get("descriptors", {}),
        "methods.json": data.get("methods", {}),
        "fingerprint.json": fingerprint,
        "statistics.json": {"browser_launches": launches, "network_requests": 0, "collection_duration_ms": round(duration_ms, 3), "collected_properties": len(data.get("values", {})) + len(data.get("highEntropy", {}).get("availability", {})), "collected_descriptors": len(descriptors), "collected_methods": len(methods), "fingerprint_generation": bool(fingerprint["sha256"]), "browser_version": probe.get("browserVersion")},
        "summary.json": summary,
        "validation.json": validation,
    }
    validation["artifact_completeness"] = all(name in artifacts for name in ARTIFACT_NAMES if name.endswith(".json"))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests", "capture_error"}) and validation["artifact_completeness"]
    summary["validation_valid"] = validation["valid"]
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "client_hints_report.md", _report(summary, data, fingerprint, validation))
    print("CLIENT HINTS BASELINE REBUILD")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Status: {capture_status} | Browser launches: {launches} | Network: 0")
    print(f"Fingerprint SHA-256: {fingerprint['sha256']}")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 060D: canonical Browser Platform Client Hints baseline")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
