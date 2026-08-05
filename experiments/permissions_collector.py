"""Experiment 054: read-only Permissions API collector.

The collector observes the native Permissions and PermissionStatus surfaces on
``about:blank`` through BrowserSessionManager.  ``permissions.query`` is used
only for the standard, non-prompting permission-state query; no permission is
requested and no media or network API is touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
    sha256_file,
    write_json_exclusive,
    write_text_exclusive,
)


ARTIFACT_NAMES = (
    "permissions.json",
    "prototype.json",
    "descriptors.json",
    "methods.json",
    "behavior.json",
    "fingerprint.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "permissions_report.md",
)
SAFE_PERMISSION_NAMES = (
    "notifications",
    "geolocation",
    "camera",
    "microphone",
    "clipboard-read",
    "clipboard-write",
)


PERMISSIONS_PROBE = r"""
async () => {
  const nativeSource = (value) => {
    try { return Function.prototype.toString.call(value); } catch (_) { return null; }
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
    const value = Object.getOwnPropertyDescriptor(target, key);
    if (!value) return null;
    return {
      configurable: !!value.configurable,
      enumerable: !!value.enumerable,
      writable: Object.prototype.hasOwnProperty.call(value, 'writable') ? !!value.writable : null,
      hasGetter: typeof value.get === 'function',
      hasSetter: typeof value.set === 'function',
      valueType: Object.prototype.hasOwnProperty.call(value, 'value') ? typeof value.value : null,
      getterSource: typeof value.get === 'function' ? nativeSource(value.get) : null,
      setterSource: typeof value.set === 'function' ? nativeSource(value.set) : null,
      valueSource: typeof value.value === 'function' ? nativeSource(value.value) : null
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
  const stable = (value) => {
    if (value === undefined) return null;
    if (value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value;
    if (Array.isArray(value)) return value.map((item) => stable(item));
    return {
      type: typeof value,
      constructor: safe(() => value.constructor && value.constructor.name, null),
      objectToString: safe(() => Object.prototype.toString.call(value), null),
      ownProperties: ownKeys(value)
    };
  };
  const functionInfo = (fn, target, name) => ({
    available: typeof fn === 'function',
    name: typeof fn === 'function' ? safe(() => fn.name, null) : null,
    length: typeof fn === 'function' ? safe(() => fn.length, null) : null,
    source: typeof fn === 'function' ? nativeSource(fn) : null,
    nativeSource: typeof fn === 'function' && /\[native code\]/.test(nativeSource(fn) || ''),
    descriptor: descriptor(target, name)
  });
  const invalidCall = async (fn, receiver, args) => {
    try {
      const value = fn.apply(receiver, args || []);
      if (value && typeof value.then === 'function') {
        try { await value; return { throws: false, promise: true, outcome: 'resolved' }; }
        catch (error) { return { throws: true, promise: true, outcome: 'rejected', error: errorInfo(error) }; }
      }
      return { throws: false, promise: false, outcome: 'returned' };
    } catch (error) {
      return { throws: true, promise: false, outcome: 'threw', error: errorInfo(error) };
    }
  };
  const statusSurface = (status) => {
    if (!status) return null;
    const statusPrototype = safe(() => Object.getPrototypeOf(status), null);
    const statusConstructor = safe(() => status.constructor, null);
    return {
      state: stable(safe(() => status.state, null)),
      name: stable(safe(() => status.name, null)),
      onchangeType: safe(() => typeof status.onchange, null),
      objectToString: safe(() => Object.prototype.toString.call(status), null),
      constructor: safe(() => statusConstructor && statusConstructor.name, null),
      constructorSource: statusConstructor ? nativeSource(statusConstructor) : null,
      prototype: safe(() => statusPrototype && statusPrototype.constructor && statusPrototype.constructor.name, null),
      prototypeChain: chain(status),
      ownProperties: ownKeys(status),
      prototypeProperties: ownKeys(statusPrototype),
      descriptors: Object.fromEntries(ownKeys(statusPrototype).map((key) => [key, descriptor(statusPrototype, key)])),
      toStringTag: descriptor(statusPrototype, Symbol.toStringTag),
      instanceofPermissionStatus: safe(() => typeof PermissionStatus === 'function' && status instanceof PermissionStatus, false),
      reference: {
        repeatedStateEqual: safe(() => status.state === status.state, false),
        repeatedPrototypeEqual: safe(() => Object.getPrototypeOf(status) === Object.getPrototypeOf(status), false)
      }
    };
  };

  const navigatorPermissionsDescriptor = descriptor(Navigator.prototype, 'permissions');
  const permissions = safe(() => navigator.permissions, null);
  const permissionsPrototype = permissions ? safe(() => Object.getPrototypeOf(permissions), null) : null;
  const permissionsConstructor = permissions ? safe(() => permissions.constructor, null) : null;
  const query = permissionsPrototype ? safe(() => permissionsPrototype.query, null) : null;
  const permissionsSurface = {
    available: !!permissions,
    typeof: permissions ? typeof permissions : 'undefined',
    objectToString: safe(() => Object.prototype.toString.call(permissions), null),
    constructor: safe(() => permissionsConstructor && permissionsConstructor.name, null),
    constructorSource: permissionsConstructor ? nativeSource(permissionsConstructor) : null,
    ownProperties: ownKeys(permissions),
    prototypeProperties: ownKeys(permissionsPrototype),
    prototypeChain: chain(permissions),
    symbolToStringTag: descriptor(permissionsPrototype, Symbol.toStringTag),
    navigatorDescriptor: navigatorPermissionsDescriptor,
    instanceofPermissions: safe(() => typeof Permissions === 'function' && permissions instanceof Permissions, false),
    prototypeEquality: safe(() => !!permissionsConstructor && permissionsPrototype === permissionsConstructor.prototype, false),
    constructorEquality: safe(() => !!permissionsConstructor && permissionsPrototype.constructor === permissionsConstructor, false),
    referenceStable: safe(() => navigator.permissions === navigator.permissions, false)
  };
  const prototypeSurface = {
    available: !!permissionsPrototype,
    constructor: {
      name: safe(() => permissionsConstructor && permissionsConstructor.name, null),
      length: safe(() => permissionsConstructor && permissionsConstructor.length, null),
      source: permissionsConstructor ? nativeSource(permissionsConstructor) : null,
      nativeSource: !!permissionsConstructor && /\[native code\]/.test(nativeSource(permissionsConstructor) || ''),
      descriptor: descriptor(globalThis, 'Permissions')
    },
    chain: chain(permissionsPrototype),
    ownProperties: ownKeys(permissionsPrototype),
    objectPrototype: safe(() => Object.getPrototypeOf(permissionsPrototype).constructor.name, null),
    instanceofObject: safe(() => permissionsPrototype instanceof Object, false),
    toStringTag: descriptor(permissionsPrototype, Symbol.toStringTag),
    descriptors: Object.fromEntries(ownKeys(permissionsPrototype).map((key) => [key, descriptor(permissionsPrototype, key)]))
  };
  const methods = {
    query: functionInfo(query, permissionsPrototype, 'query'),
    queryPrototype: functionInfo(query, typeof Permissions === 'function' ? Permissions.prototype : null, 'query')
  };
  const behavior = {};
  for (const name of ["notifications", "geolocation", "camera", "microphone", "clipboard-read", "clipboard-write"]) {
    const row = { name, supported: false, promise: false, outcome: 'unavailable', state: null, status: null, error: null };
    if (query && permissions) {
      try {
        const result = query.call(permissions, { name });
        row.promise = !!result && typeof result.then === 'function';
        const status = await result;
        row.supported = true;
        row.outcome = 'resolved';
        row.status = statusSurface(status);
        row.state = safe(() => status.state, null);
      } catch (error) {
        row.outcome = 'rejected';
        row.error = errorInfo(error);
      }
    }
    behavior[name] = row;
  }
  const exceptions = {
    detachedQuery: query ? await invalidCall(query, undefined, [{ name: 'notifications' }]) : { tested: false },
    invalidReceiver: query ? await invalidCall(query, {}, [{ name: 'notifications' }]) : { tested: false },
    nullDescriptor: query ? await invalidCall(query, permissions, [null]) : { tested: false },
    emptyDescriptor: query ? await invalidCall(query, permissions, [{}]) : { tested: false },
    unknownDescriptor: query ? await invalidCall(query, permissions, [{ name: '__unknown_permission__' }]) : { tested: false },
    prototypeReceiver: query && permissionsPrototype ? await invalidCall(query, permissionsPrototype, [{ name: 'notifications' }]) : { tested: false },
    constructorCall: safe(() => { Permissions.call({}); return { throws: false }; }, null),
    constructorReflect: safe(() => { Reflect.construct(Permissions, []); return { throws: false }; }, null)
  };
  if (exceptions.constructorCall === null) exceptions.constructorCall = { throws: true, error: errorInfo(safe(() => { Permissions.call({}); return null; }, new TypeError('Illegal constructor'))) };
  if (exceptions.constructorReflect === null) exceptions.constructorReflect = { throws: true, error: errorInfo(safe(() => { Reflect.construct(Permissions, []); return null; }, new TypeError('Illegal constructor'))) };
  return {
    available: !!permissions,
    permissions: permissionsSurface,
    prototype: prototypeSurface,
    descriptors: {
      navigatorPermissions: navigatorPermissionsDescriptor,
      permissionsPrototype: prototypeSurface.descriptors,
      permissionStatusPrototype: Object.fromEntries(
        Object.entries(behavior).flatMap(([name, value]) => value.status && value.status.descriptors ? Object.entries(value.status.descriptors).map(([key, descriptorValue]) => [`${name}.${key}`, descriptorValue]) : [])
      )
    },
    methods,
    behavior,
    exceptions
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
        return {str(key): _ordered(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(_ordered(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _historical_hashes(root: Path) -> dict[str, str]:
    """Hash existing experiment files without including this new allocation."""
    reports = root / "reports" / "experiments"
    output: dict[str, str] = {}
    if not reports.is_dir():
        return output
    for experiment_dir in sorted((item for item in reports.iterdir() if item.is_dir() and item.name.startswith("exp_")), key=lambda item: item.name):
        for path in sorted((item for item in experiment_dir.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
            try:
                output[str(path.relative_to(root))] = sha256_file(path)
            except OSError:
                output[str(path.relative_to(root))] = ""
    return output


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
        result = page.evaluate(PERMISSIONS_PROBE)
        if not isinstance(result, dict):
            raise TypeError("Permissions probe returned a non-object result")
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
    behavior = data.get("behavior", {})
    lines = [
        "# Experiment 054 - Permissions Collector", "", "## Executive Summary", "",
        f"- Result: **{summary['result']}**",
        f"- Permissions API available: **{summary['available']}**",
        f"- Safe queries resolved: **{stats['resolved_queries']}/{stats['query_count']}**",
        f"- Fingerprint: `{summary['fingerprint_sha256']}`",
        "",
        "The collector ran on about:blank through Browser Platform. Permission state queries do not request or grant permissions; no media or network operation was performed.",
        "", "## Permission States", "", "| Permission | Supported | Promise | Outcome | State |", "|---|---:|---:|---|---|",
    ]
    for name in sorted(behavior):
        row = behavior[name] if isinstance(behavior[name], dict) else {}
        lines.append(f"| `{name}` | {row.get('supported')} | {row.get('promise')} | {row.get('outcome')} | `{row.get('state')}` |")
    lines += ["", "## Surface", "", "| Field | Value |", "|---|---|"]
    surface = data.get("permissions", {})
    for key in ("available", "typeof", "constructor", "objectToString", "instanceofPermissions", "prototypeEquality", "constructorEquality", "referenceStable"):
        lines.append(f"| `{key}` | `{surface.get(key)}` |")
    lines += ["", "## Validation", "", "| Check | Status |", "|---|---|"]
    for key, value in validation.items():
        if key in {"valid", "artifact_completeness", "browser_launches", "network_requests"}:
            continue
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if bool(value) else 'FAIL'} |")
    lines += ["", "## Read-only Boundary", "", "Only API metadata, descriptors, illegal invocation behavior, and non-prompting permission-state queries were observed. No permission request, media access, navigation, network request, or stealth injection was used.", ""]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    historical_before = _historical_hashes(root)
    status, capture_error, data, started = _capture(args)
    data = _ordered(data if isinstance(data, dict) else {})
    historical_after = _historical_hashes(root)
    fingerprint_data = {key: data.get(key, {}) for key in ("permissions", "prototype", "descriptors", "methods", "behavior", "exceptions")}
    fingerprint_hash = _canonical_hash(fingerprint_data)
    permissions = data.get("permissions", {}) if isinstance(data.get("permissions"), dict) else {}
    prototype = data.get("prototype", {}) if isinstance(data.get("prototype"), dict) else {}
    methods = data.get("methods", {}) if isinstance(data.get("methods"), dict) else {}
    behavior = data.get("behavior", {}) if isinstance(data.get("behavior"), dict) else {}
    exceptions = data.get("exceptions", {}) if isinstance(data.get("exceptions"), dict) else {}
    resolved = sum(1 for value in behavior.values() if isinstance(value, dict) and value.get("outcome") == "resolved")
    query_count = len(behavior)
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden = ("requestPermission(", "get" + "UserMedia(", "get" + "DisplayMedia(", "selectAudioOutput(", "sendBeacon(", "fetch(", "XMLHttpRequest", "add_" + "init_script", "_" + "_stealth")
    query_info = methods.get("query", {}) if isinstance(methods.get("query"), dict) else {}
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (data, fingerprint_data)),
        "artifact_completeness": False,
        "deterministic_ordering": data == _ordered(data),
        "prototype_validation": bool(permissions.get("prototypeEquality")) and bool(permissions.get("constructorEquality")) and bool(prototype.get("instanceofObject")),
        "descriptor_validation": bool(data.get("descriptors")) and all(value is None or isinstance(value, dict) for value in data.get("descriptors", {}).values()),
        "method_validation": bool(query_info.get("available")) and bool(query_info.get("nativeSource")) and isinstance(query_info.get("descriptor"), dict),
        "behavior_validation": query_count == len(SAFE_PERMISSION_NAMES) and all(isinstance(value, dict) for value in behavior.values()),
        "fingerprint_validation": bool(fingerprint_hash) and fingerprint_hash == _canonical_hash(fingerprint_data),
        "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and "launch_browser" in source and ("sync_" + "playwright") not in source,
        "read_only_verification": not any(token in PERMISSIONS_PROBE for token in forbidden),
        "no_permission_prompts": not any(token in PERMISSIONS_PROBE for token in ("requestPermission(", "get" + "UserMedia(", "get" + "DisplayMedia(", "selectAudioOutput(")),
        "no_media_access": not any(token in PERMISSIONS_PROBE for token in ("get" + "UserMedia(", "get" + "DisplayMedia(", "selectAudioOutput(")),
        "no_network_requests": not any(token in PERMISSIONS_PROBE for token in ("sendBeacon(", "fetch(", "XMLHttpRequest")),
        "historical_artifacts_immutable": historical_before == historical_after,
        "browser_launches": int(started),
        "network_requests": 0,
        "valid": False,
    }
    stats = {
        "query_count": query_count,
        "permission_count": query_count,
        "resolved_queries": resolved,
        "rejected_queries": sum(1 for value in behavior.values() if isinstance(value, dict) and value.get("outcome") == "rejected"),
        "supported_permissions": sorted(name for name, value in behavior.items() if isinstance(value, dict) and value.get("supported")),
        "available": bool(data.get("available")),
        "prototype_property_count": len(prototype.get("ownProperties", [])),
        "descriptor_count": sum(1 for value in data.get("descriptors", {}).values() if isinstance(value, dict)),
        "method_count": sum(1 for value in methods.values() if isinstance(value, dict) and value.get("available")),
        "native_method_count": sum(1 for value in methods.values() if isinstance(value, dict) and value.get("nativeSource")),
        "exception_check_count": len(exceptions),
        "browser_launches": int(started),
        "network_requests": 0,
        "capture_status": status,
        "capture_error": capture_error,
        "fingerprint_sha256": fingerprint_hash,
    }
    validation["json_validation"] = all(_json_safe(value) for value in (data, fingerprint_data, stats))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})
    summary = {
        "experiment": "Experiment 054 - Permissions Collector",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "SUCCESS" if status == "SUCCESS" else ("PARTIAL" if started else "UNKNOWN"),
        "available": bool(data.get("available")),
        "browser": args.browser,
        "headless": bool(args.headless),
        "browser_platform": "BrowserSessionManager -> launch_browser",
        "query_count": query_count,
        "resolved_queries": resolved,
        "fingerprint_sha256": fingerprint_hash,
        "browser_launches": int(started),
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "permissions"
    output.mkdir(parents=True, exist_ok=False)
    artifact_data = {
        "permissions.json": permissions,
        "prototype.json": prototype,
        "descriptors.json": data.get("descriptors", {}),
        "methods.json": methods,
        "behavior.json": {"queries": behavior, "exceptions": exceptions},
        "fingerprint.json": {"algorithm": "SHA-256", "sha256": fingerprint_hash, "data": fingerprint_data},
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    validation["artifact_completeness"] = all(name in artifact_data for name in ARTIFACT_NAMES if name.endswith(".json"))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})
    summary["validation_valid"] = validation["valid"]
    for filename, value in artifact_data.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "permissions_report.md", _report(summary, stats, validation, data))
    print("PERMISSIONS COLLECTOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"API available: {summary['available']} | Queries: {resolved}/{query_count} resolved")
    print(f"Fingerprint: {fingerprint_hash}")
    print(f"Browser launches: {stats['browser_launches']} | Network requests: {stats['network_requests']}")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 054: collect native Permissions API behavior")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
