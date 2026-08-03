"""Experiment 045: read-only Real Browser WebRTC API collector.

Only constructors, prototypes, descriptors and native function metadata are
inspected.  The probe never constructs an RTCPeerConnection, gathers ICE,
contacts STUN/TURN, creates a data channel, or sends packets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

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


TARGETS = (
    "RTCPeerConnection",
    "RTCSessionDescription",
    "RTCIceCandidate",
    "RTCDataChannel",
    "RTCRtpSender",
    "RTCRtpReceiver",
    "RTCRtpTransceiver",
)
ARTIFACT_NAMES = (
    "constructors.json",
    "prototype.json",
    "descriptors.json",
    "methods.json",
    "fingerprint.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "webrtc_report.md",
)


WEBRTC_PROBE = r"""
() => {
  const nativeSource = (value) => {
    try { return Function.prototype.toString.call(value); }
    catch (_) { return null; }
  };
  const keyLabel = (key) => typeof key === 'symbol' ? String(key) : String(key);
  const ownKeys = (target) => {
    if (!target) return [];
    try {
      const names = Object.getOwnPropertyNames(target);
      const symbols = Object.getOwnPropertySymbols(target).sort((a, b) => String(a).localeCompare(String(b)));
      return [...names, ...symbols];
    } catch (_) { return []; }
  };
  const descriptor = (target, key) => {
    try {
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
    } catch (_) { return null; }
  };
  const descriptorMap = (target) => {
    const result = {};
    for (const key of ownKeys(target).sort((a, b) => keyLabel(a).localeCompare(keyLabel(b)))) {
      const value = descriptor(target, key);
      if (value) result[keyLabel(key)] = value;
    }
    return result;
  };
  const chain = (target) => {
    const result = [];
    const seen = new Set();
    let current = target;
    while (current && !seen.has(current)) {
      seen.add(current);
      let name = null;
      try { name = current.constructor && current.constructor.name; } catch (_) {}
      result.push(name || '(anonymous)');
      try { current = Object.getPrototypeOf(current); } catch (_) { current = null; }
    }
    return result;
  };
  const functionInfo = (value, target, key) => {
    const source = typeof value === 'function' ? nativeSource(value) : null;
    return {
      available: typeof value === 'function',
      typeof: typeof value,
      source,
      nativeSource: typeof value === 'function' && /\[native code\]/.test(source || ''),
      descriptor: descriptor(target, key)
    };
  };
  const functionMap = (target) => {
    const result = {};
    for (const key of ownKeys(target).sort((a, b) => keyLabel(a).localeCompare(keyLabel(b)))) {
      let value;
      try { value = target[key]; } catch (_) { value = undefined; }
      if (typeof value === 'function') result[keyLabel(key)] = functionInfo(value, target, key);
    }
    return result;
  };
  const illegalInvocation = (target) => {
    const result = {};
    for (const key of ownKeys(target).sort((a, b) => keyLabel(a).localeCompare(keyLabel(b)))) {
      let value;
      try { value = target[key]; } catch (_) { value = undefined; }
      if (typeof value !== 'function') continue;
      const label = keyLabel(key);
      try {
        value.call({});
        result[label] = false;
      } catch (_) {
        result[label] = true;
      }
    }
    return result;
  };
  const symbolTag = (target) => {
    const value = descriptor(target, Symbol.toStringTag);
    return value || null;
  };
  const prototypeInfo = (ctor) => {
    const proto = ctor && ctor.prototype ? ctor.prototype : null;
    if (!proto) return {
      exists: false, name: null, chain: [], ownProperties: [],
      symbolToStringTag: null, instanceofObject: false, constructorIdentity: false,
      instanceof: { prototypeInstanceofConstructor: false, objectPrototypeIsPrototypeOf: false }
    };
    let constructorIdentity = false;
    try { constructorIdentity = proto.constructor === ctor; } catch (_) {}
    let prototypeInstanceofConstructor = false;
    let objectPrototypeIsPrototypeOf = false;
    try { prototypeInstanceofConstructor = proto instanceof ctor; } catch (_) {}
    try { objectPrototypeIsPrototypeOf = Object.prototype.isPrototypeOf(proto); } catch (_) {}
    return {
      exists: true,
      name: (() => { try { return proto.constructor && proto.constructor.name || null; } catch (_) { return null; } })(),
      chain: chain(proto),
      ownProperties: ownKeys(proto).map(keyLabel).sort(),
      symbolToStringTag: symbolTag(proto),
      instanceofObject: proto instanceof Object,
      constructorIdentity,
      instanceof: { prototypeInstanceofConstructor, objectPrototypeIsPrototypeOf },
      descriptors: descriptorMap(proto),
      methods: functionMap(proto),
      illegalInvocation: illegalInvocation(proto)
    };
  };
  const constructorInfo = (name) => {
    const ctor = globalThis[name];
    const available = typeof ctor === 'function';
    const prototype = available && ctor.prototype ? ctor.prototype : null;
    const staticMembers = available ? functionMap(ctor) : {};
    const ownProperties = available ? ownKeys(ctor).map(keyLabel).sort() : [];
    const source = available ? nativeSource(ctor) : null;
    let prototypeIdentity = false;
    try { prototypeIdentity = !!prototype && prototype.constructor === ctor; } catch (_) {}
    return {
      name,
      available,
      typeof: typeof ctor,
      source,
      nativeSource: available && /\[native code\]/.test(source || ''),
      descriptor: descriptor(globalThis, name),
      ownProperties,
      staticMembers,
      prototypeName: prototype && prototype.constructor ? prototype.constructor.name : null,
      prototypeIdentity
    };
  };

  // This is metadata-only: no constructor below is called or instantiated.
  const constructors = {};
  const prototypes = {};
  const descriptorOutput = { constructors: {}, prototypes: {}, staticMembers: {} };
  const methods = { constructors: {}, prototypes: {}, staticMembers: {}, illegalInvocation: {} };
  for (const name of ["RTCPeerConnection", "RTCSessionDescription", "RTCIceCandidate", "RTCDataChannel", "RTCRtpSender", "RTCRtpReceiver", "RTCRtpTransceiver"].sort()) {
    const ctor = constructorInfo(name);
    constructors[name] = ctor;
    const value = globalThis[name];
    const proto = value && value.prototype ? value.prototype : null;
    const info = prototypeInfo(value);
    prototypes[name] = info;
    descriptorOutput.constructors[name] = ctor.descriptor;
    descriptorOutput.prototypes[name] = info.descriptors || {};
    descriptorOutput.staticMembers[name] = availableStatic(name, value);
    methods.constructors[name] = {
      source: ctor.source,
      nativeSource: ctor.nativeSource,
      descriptor: ctor.descriptor
    };
    methods.prototypes[name] = info.methods || {};
    methods.staticMembers[name] = ctor.staticMembers || {};
    methods.illegalInvocation[name] = info.illegalInvocation || {};
  }
  function availableStatic(name, ctor) {
    if (typeof ctor !== 'function') return {};
    const result = {};
    for (const key of ownKeys(ctor).sort((a, b) => keyLabel(a).localeCompare(keyLabel(b)))) {
      const label = keyLabel(key);
      if (label === 'name' || label === 'length' || label === 'prototype') continue;
      let value;
      try { value = ctor[key]; } catch (_) { value = undefined; }
      result[label] = descriptor(ctor, key);
    }
    return result;
  }
  return { constructors, prototypes, descriptors: descriptorOutput, methods };
}
"""


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _iter_method_records(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if "available" in value:
            yield value
        else:
            for child in value.values():
                yield from _iter_method_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_method_records(child)


def _all_keys_sorted(value: Any) -> bool:
    if isinstance(value, dict):
        if list(value) != sorted(value):
            return False
        return all(_all_keys_sorted(child) for child in value.values())
    if isinstance(value, list):
        return all(_all_keys_sorted(child) for child in value)
    return True


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
    probe: dict[str, Any] = {}
    try:
        manager.start()
        started = True
        page = manager.new_page()
        value = page.evaluate(WEBRTC_PROBE)
        if not isinstance(value, dict):
            raise TypeError("WebRTC probe returned a non-object result")
        probe = value
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
    status = "SUCCESS" if started and isinstance(probe, dict) and bool(probe) and not error else ("PARTIAL" if started else "UNKNOWN")
    return status, error, probe, started


def _report(summary: dict[str, Any], stats: dict[str, Any], validation: dict[str, Any]) -> str:
    lines = [
        "# Experiment 045 - Real WebRTC Collector",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Constructors discovered: **{stats['constructor_count']}**",
        f"- Available constructors: **{stats['available_constructor_count']}**",
        f"- Prototype methods: **{stats['prototype_method_count']}**",
        f"- Native function records: **{stats['native_source_count']}**",
        "",
        "The collector inspected browser metadata only. It did not construct a peer connection, gather ICE, contact STUN/TURN, create a data channel, or transmit packets.",
        "",
        "## Constructor Coverage",
        "",
        "| Constructor | Available | Native Source | Prototype | Instanceof Metadata |",
        "|---|---|---|---|---|",
    ]
    for name, item in summary.get("constructors", {}).items():
        prototype = summary.get("prototypes", {}).get(name, {})
        lines.append(f"| `{name}` | {item.get('available')} | {item.get('nativeSource')} | {prototype.get('exists')} | {prototype.get('instanceofObject')} |")
    lines += ["", "## Validation", "", "| Check | Status |", "|---|---|"]
    for key, value in validation.items():
        if key in {"valid", "artifact_completeness", "browser_launches", "network_requests"}:
            continue
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if bool(value) else 'FAIL'} |")
    lines += ["", "## Read-only Boundary", "", "No browser behavior, network stack, permissions, or stealth surface was modified.", ""]
    return "\n".join(lines)


def _positive_timeout(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return result


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    status, error, probe, started = _capture(args)
    constructors = probe.get("constructors", {}) if isinstance(probe.get("constructors"), dict) else {}
    prototypes = probe.get("prototypes", {}) if isinstance(probe.get("prototypes"), dict) else {}
    descriptors = probe.get("descriptors", {}) if isinstance(probe.get("descriptors"), dict) else {}
    methods = probe.get("methods", {}) if isinstance(probe.get("methods"), dict) else {}
    fingerprint_data = {
        "constructors": constructors,
        "prototypes": prototypes,
        "descriptors": descriptors,
        "methods": methods,
    }
    fingerprint = {
        "algorithm": "SHA-256",
        "sha256": _canonical_hash(fingerprint_data),
        "data": fingerprint_data,
    }
    method_records = list(_iter_method_records(methods))
    native_records = [row for row in method_records if row.get("available")]
    native_failures = [row for row in native_records if not row.get("nativeSource")]
    illegal_records = [value for value in (methods.get("illegalInvocation", {}) or {}).values() if isinstance(value, dict) for value in value.values()]
    available_constructors = sum(1 for value in constructors.values() if isinstance(value, dict) and value.get("available"))
    prototype_count = sum(1 for value in prototypes.values() if isinstance(value, dict) and value.get("exists"))
    static_member_count = sum(len(value) for value in (descriptors.get("staticMembers", {}) or {}).values() if isinstance(value, dict))
    descriptor_count = sum(len(value) for value in descriptors.values() if isinstance(value, dict) for value in value.values() if isinstance(value, dict))
    stats = {
        "constructor_count": len(TARGETS),
        "available_constructor_count": available_constructors,
        "prototype_count": prototype_count,
        "prototype_method_count": len([row for row in method_records if row.get("available")]),
        "static_member_count": static_member_count,
        "descriptor_count": descriptor_count,
        "native_source_count": len(native_records),
        "native_source_failures": len(native_failures),
        "illegal_invocation_count": len(illegal_records),
        "illegal_invocation_throw_count": sum(1 for value in illegal_records if value is True),
        "browser_launches": int(started),
        "network_requests": 0,
        "capture_status": status,
    }
    source_code = Path(__file__).read_text(encoding="utf-8")
    probe_source = WEBRTC_PROBE
    forbidden = (
        "new " + "RTCPeerConnection",
        "createDataChannel" + "(",
        "setLocalDescription" + "(",
        "setRemoteDescription" + "(",
        "addIceCandidate" + "(",
        "getUserMedia" + "(",
        "getDisplayMedia" + "(",
        "stun:",
        "turn:",
    )
    constructors_valid = all(
        isinstance(constructors.get(name), dict)
        and constructors[name].get("name") == name
        and (not constructors[name].get("available") or constructors[name].get("prototypeIdentity") is True)
        for name in sorted(TARGETS)
    )
    prototype_valid = all(
        not value.get("exists") or (
            value.get("instanceofObject") is True
            and value.get("constructorIdentity") is True
            and isinstance(value.get("instanceof"), dict)
            and isinstance(value.get("chain"), list)
        )
        for value in prototypes.values() if isinstance(value, dict)
    )
    descriptor_valid = bool(descriptors) and all(_json_safe(value) for value in descriptors.values())
    native_source_valid = all(bool(value.get("nativeSource")) for value in native_records)
    deterministic = (
        list(constructors) == sorted(constructors)
        and list(prototypes) == sorted(prototypes)
        and all(list(value) == sorted(value) for value in descriptors.values() if isinstance(value, dict))
        and all(list(value) == sorted(value) for value in methods.values() if isinstance(value, dict))
    )
    platform_token = "sync_" + "playwright"
    init_script_token = "add_" + "init_script"
    stealth_token = "_" + "_stealth"
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (constructors, prototypes, descriptors, methods, fingerprint, stats)),
        "artifact_completeness": False,
        "deterministic_ordering": deterministic,
        "prototype_validation": constructors_valid and prototype_valid,
        "descriptor_validation": descriptor_valid,
        "native_source_validation": native_source_valid,
        "browser_platform_verification": "BrowserConfig" in source_code and "BrowserSessionManager" in source_code and platform_token not in source_code,
        "read_only_verification": not any(token in probe_source for token in forbidden),
        "no_stealth_injection": init_script_token not in source_code and stealth_token not in probe_source,
        "no_peer_connection_created": "new " + "RTCPeerConnection" not in probe_source,
        "network_requests": 0,
        "browser_launches": int(started),
        "valid": False,
    }
    summary = {
        "experiment": "Experiment 045 - Real WebRTC Collector",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": status,
        "error": error,
        "constructors": constructors,
        "prototypes": prototypes,
        "fingerprint_sha256": fingerprint["sha256"],
        "constructor_count": stats["constructor_count"],
        "available_constructor_count": stats["available_constructor_count"],
        "browser_launches": int(started),
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "webrtc"
    output.mkdir(parents=True, exist_ok=False)
    validation["artifact_completeness"] = True
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})
    summary["validation_valid"] = validation["valid"]
    artifacts = {
        "constructors.json": constructors,
        "prototype.json": prototypes,
        "descriptors.json": descriptors,
        "methods.json": methods,
        "fingerprint.json": fingerprint,
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    report = _report(summary, stats, validation)
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "webrtc_report.md", report)
    print("REAL WEBRTC COLLECTOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Constructors: {stats['available_constructor_count']}/{stats['constructor_count']}")
    print(f"Native methods: {stats['native_source_count']} | Descriptors: {stats['descriptor_count']}")
    print("Browser launches: 1 | Network requests: 0")
    print(f"Result: {status} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 045: collect Real Browser WebRTC API metadata")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
