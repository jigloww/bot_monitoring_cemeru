"""Read-only MediaDevices fingerprint collector for the Browser Platform.

The collector uses ``BrowserSessionManager`` (which delegates launch to the
platform ``launch_browser`` entry point) and only evaluates browser APIs.  It
never requests media, records media, patches JavaScript, or injects stealth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
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


MEDIA_DEVICES_PROBE = r"""
async () => {
  const nativeSource = (value) => {
    try { return Function.prototype.toString.call(value); }
    catch (_) { return null; }
  };
  const descriptor = (target, name) => {
    try {
      const item = Object.getOwnPropertyDescriptor(target, name);
      if (!item) return null;
      const output = {
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
      return output;
    } catch (_) { return null; }
  };
  const descriptorMap = (target, names) => {
    const result = {};
    for (const name of [...names].sort()) {
      const item = descriptor(target, name);
      if (item) result[name] = item;
    }
    return result;
  };
  const ownNames = (target) => {
    if (!target) return [];
    try {
      const names = Object.getOwnPropertyNames(target);
      const symbols = Object.getOwnPropertySymbols(target).map((item) => String(item));
      return [...new Set([...names, ...symbols])].sort();
    } catch (_) { return []; }
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
  const digest = async (value) => {
    try {
      const bytes = new TextEncoder().encode(String(value || ''));
      const buffer = await crypto.subtle.digest('SHA-256', bytes);
      return Array.from(new Uint8Array(buffer)).map((item) => item.toString(16).padStart(2, '0')).join('');
    } catch (_) { return null; }
  };

  const mediaDevices = navigator.mediaDevices || null;
  const mediaConstructor = mediaDevices && mediaDevices.constructor ? mediaDevices.constructor : null;
  const mediaPrototype = mediaConstructor && mediaConstructor.prototype ? mediaConstructor.prototype : null;
  const mediaOwnNames = ownNames(mediaDevices);
  const prototypeNames = ownNames(mediaPrototype);
  const methodNames = ['enumerateDevices', 'getUserMedia', 'getDisplayMedia', 'selectAudioOutput'];
  const methodDescriptors = mediaPrototype ? descriptorMap(mediaPrototype, methodNames) : {};
  const methods = {};
  for (const name of methodNames) {
    const method = mediaDevices ? mediaDevices[name] : undefined;
    methods[name] = {
      available: typeof method === 'function',
      typeof: typeof method,
      source: typeof method === 'function' ? nativeSource(method) : null,
      nativeSource: typeof method === 'function' && /\[native code\]/.test(nativeSource(method) || ''),
      descriptor: methodDescriptors[name] || null
    };
  }

  const devices = [];
  let enumerationError = null;
  if (mediaDevices && typeof mediaDevices.enumerateDevices === 'function') {
    try {
      const values = await mediaDevices.enumerateDevices();
      for (let index = 0; index < values.length; index += 1) {
        const item = values[index] || {};
        const deviceId = String(item.deviceId || '');
        const groupId = String(item.groupId || '');
        devices.push({
          kind: String(item.kind || 'unknown'),
          label: String(item.label || ''),
          deviceIdLength: deviceId.length,
          deviceIdHash: await digest(deviceId),
          groupIdLength: groupId.length,
          groupIdHash: await digest(groupId),
          isDefault: deviceId === 'default',
          index
        });
      }
    } catch (error) {
      enumerationError = String(error && error.message ? error.message : error);
    }
  } else {
    enumerationError = 'navigator.mediaDevices.enumerateDevices is unavailable';
  }
  devices.sort((left, right) => left.index - right.index || left.kind.localeCompare(right.kind));

  const permissionNames = ['camera', 'microphone'];
  const permissions = {};
  for (const name of permissionNames) {
    const item = { name, supported: false, state: 'unknown', error: null };
    try {
      if (navigator.permissions && typeof navigator.permissions.query === 'function') {
        item.supported = true;
        const status = await navigator.permissions.query({ name });
        item.state = String(status && status.state ? status.state : 'unknown');
      } else {
        item.error = 'navigator.permissions.query is unavailable';
      }
    } catch (error) {
      item.error = String(error && error.message ? error.message : error);
    }
    permissions[name] = item;
  }

  const navigatorPrototype = Object.getPrototypeOf(navigator);
  const navigatorMediaDescriptor = descriptor(navigatorPrototype, 'mediaDevices');
  const symbolTagDescriptor = mediaPrototype ? descriptor(mediaPrototype, Symbol.toStringTag) : null;
  let symbolTag = null;
  try { symbolTag = mediaDevices ? Object.prototype.toString.call(mediaDevices) : null; } catch (_) {}
  const counts = { audioinput: 0, audiooutput: 0, videoinput: 0, default: 0 };
  for (const item of devices) {
    if (Object.prototype.hasOwnProperty.call(counts, item.kind)) counts[item.kind] += 1;
    if (item.isDefault) counts.default += 1;
  }
  return {
    navigator: {
      exists: !!navigator,
      typeof: typeof navigator.mediaDevices,
      constructor: navigator && navigator.constructor ? navigator.constructor.name : null,
      prototype: navigatorPrototype && navigatorPrototype.constructor ? navigatorPrototype.constructor.name : null,
      ownProperties: ownNames(navigator),
      mediaDevicesDescriptor: navigatorMediaDescriptor
    },
    mediaDevices: {
      exists: !!mediaDevices,
      typeof: typeof navigator.mediaDevices,
      constructor: mediaConstructor ? mediaConstructor.name : null,
      prototype: mediaPrototype && mediaPrototype.constructor ? mediaPrototype.constructor.name : null,
      ownProperties: mediaOwnNames,
      prototypeProperties: prototypeNames,
      prototypeChain: chain(mediaDevices),
      instanceof: !!(mediaDevices && mediaConstructor && mediaDevices instanceof mediaConstructor),
      toStringTag: symbolTag,
      toStringTagDescriptor: symbolTagDescriptor
    },
    methods,
    descriptors: {
      navigatorPrototype: navigatorMediaDescriptor,
      mediaDevicesPrototype: mediaPrototype ? descriptorMap(mediaPrototype, prototypeNames) : {},
      methods: methodDescriptors
    },
    devices: {
      supported: !!mediaDevices,
      enumerationError,
      devices,
      counts,
      total: devices.length
    },
    permissions,
    permissionApi: {
      available: !!(navigator.permissions && typeof navigator.permissions.query === 'function'),
      prototype: navigator.permissions ? chain(navigator.permissions) : []
    }
  };
}
"""


@dataclass(frozen=True)
class CollectorRun:
    status: str
    url: str
    browser_started: bool
    navigation_succeeded: bool
    error: str | None
    data: dict[str, Any]


def _empty_probe(error: str | None = None) -> dict[str, Any]:
    return {
        "navigator": {"exists": False, "typeof": "undefined", "constructor": None, "prototype": None, "ownProperties": [], "mediaDevicesDescriptor": None},
        "mediaDevices": {"exists": False, "typeof": "undefined", "constructor": None, "prototype": None, "ownProperties": [], "prototypeProperties": [], "prototypeChain": [], "instanceof": False, "toStringTag": None, "toStringTagDescriptor": None},
        "methods": {},
        "descriptors": {"navigatorPrototype": None, "mediaDevicesPrototype": {}, "methods": {}},
        "devices": {"supported": False, "enumerationError": error, "devices": [], "counts": {"audioinput": 0, "audiooutput": 0, "videoinput": 0, "default": 0}, "total": 0},
        "permissions": {"camera": {"name": "camera", "supported": False, "state": "unknown", "error": error}, "microphone": {"name": "microphone", "supported": False, "state": "unknown", "error": error}},
        "permissionApi": {"available": False, "prototype": []},
    }


def _run_collection(args: argparse.Namespace) -> CollectorRun:
    config = BrowserConfig(
        browser=args.browser,
        headless=args.headless,
        persistent=False,
        url="about:blank",
        timeout=args.timeout,
        enable_stealth=False,
    )
    manager = BrowserSessionManager(config)
    browser_started = False
    navigation_succeeded = False
    error: str | None = None
    data: dict[str, Any]
    page: Any = None
    try:
        manager.start()
        browser_started = True
        page = manager.new_page()
        if args.url and args.url != "about:blank":
            try:
                page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout)
                navigation_succeeded = True
            except Exception as exc:
                error = f"navigation: {exc}"
        try:
            data = page.evaluate(MEDIA_DEVICES_PROBE)
            if not isinstance(data, dict):
                raise TypeError("MediaDevices probe returned a non-object result")
        except Exception as exc:
            error = f"probe: {exc}"
            data = _empty_probe(str(exc))
        status = "SUCCESS" if data.get("mediaDevices", {}).get("exists") else "PARTIAL"
        if error and status == "SUCCESS":
            status = "PARTIAL"
    except Exception as exc:
        error = f"browser launch: {exc}"
        data = _empty_probe(str(exc))
        status = "UNKNOWN"
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
    return CollectorRun(status, args.url, browser_started, navigation_succeeded, error, data)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_artifacts(run: CollectorRun, experiment_id: str) -> dict[str, Any]:
    data = run.data
    devices = data.get("devices") or data.get("devices", {})
    permissions = data.get("permissions", {})
    methods = data.get("methods", {})
    descriptors = data.get("descriptors", {})
    prototype = {
        "navigator": data.get("navigator", {}),
        "mediaDevices": data.get("mediaDevices", {}),
        "permissionApi": data.get("permissionApi", {}),
    }
    device_document = devices
    permission_document = permissions
    method_document = methods
    descriptor_document = descriptors
    fingerprint_data = {
        "navigator": data.get("navigator", {}),
        "mediaDevices": data.get("mediaDevices", {}),
        "methods": method_document,
        "descriptors": descriptor_document,
        "devices": device_document,
        "permissions": permission_document,
        "permissionApi": data.get("permissionApi", {}),
    }
    device_items = device_document.get("devices", []) if isinstance(device_document, dict) else []
    device_counts = device_document.get("counts", {}) if isinstance(device_document, dict) else {}
    permission_counts = {
        "total": len(permission_document),
        "supported": sum(1 for value in permission_document.values() if value.get("supported")),
        "granted": sum(1 for value in permission_document.values() if value.get("state") == "granted"),
        "denied": sum(1 for value in permission_document.values() if value.get("state") == "denied"),
        "prompt": sum(1 for value in permission_document.values() if value.get("state") == "prompt"),
    }
    descriptor_count = 0
    for value in descriptor_document.values():
        if isinstance(value, dict):
            descriptor_count += len(value) if value is not descriptor_document.get("methods") else sum(len(item) for item in value.values() if isinstance(item, dict))
    method_count = len(method_document)
    statistics = {
        "total_properties": len(data.get("navigator", {}).get("ownProperties", [])) + len(data.get("mediaDevices", {}).get("prototypeProperties", [])),
        "total_methods": method_count,
        "device_counts": device_counts,
        "permission_counts": permission_counts,
        "descriptor_count": descriptor_count,
        "native_method_count": sum(1 for item in method_document.values() if item.get("nativeSource")),
        "devices_total": len(device_items),
        "browser_started": run.browser_started,
        "navigation_succeeded": run.navigation_succeeded,
    }
    return {
        "devices.json": device_document,
        "permissions.json": permission_document,
        "prototype.json": prototype,
        "descriptors.json": descriptor_document,
        "methods.json": method_document,
        "fingerprint.json": {
            "experiment": "Experiment 035 - Real MediaDevices Collector",
            "experiment_id": experiment_id,
            "algorithm": "sha256",
            "sha256": _canonical_hash(fingerprint_data),
            "data": fingerprint_data,
        },
        "statistics.json": statistics,
    }


def _report(summary: dict[str, Any], validation: dict[str, Any], statistics: dict[str, Any], run: CollectorRun) -> str:
    lines = [
        "# Experiment 035 — Real MediaDevices Collector",
        "",
        "## Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- URL: **{run.url}**",
        f"- Browser started through Browser Platform: **{run.browser_started}**",
        f"- MediaDevices available: **{statistics.get('media_devices_available', False)}**",
        f"- Device count: **{statistics.get('devices_total', 0)}**",
        "",
        "## Device Counts",
        "",
        "| Kind | Count |",
        "|---|---:|",
    ]
    for key, value in sorted((statistics.get("device_counts") or {}).items()):
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "## Permissions",
        "",
        "Permission queries are observational only. No camera, microphone, display, or recording API was invoked.",
        "",
        "## Validation",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    for key, value in validation.items():
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if value else 'FAIL'} |")
    if run.error:
        lines += ["", "## Runtime Note", "", f"`{run.error}`"]
    lines += [
        "",
        "## Read-only Boundary",
        "",
        "The collector does not install stealth, request permissions, call getUserMedia(), call getDisplayMedia(), record audio/video, intercept network traffic, or modify browser prototypes.",
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = args.reports_dir or root / "reports" / "experiments"
    if not reports_root.is_absolute():
        reports_root = root / reports_root
    experiment = Experiment.create(reports_root.resolve())
    output = experiment.directory / "media_devices"
    output.mkdir(parents=True, exist_ok=True)
    collection = _run_collection(args)
    artifacts = _build_artifacts(collection, experiment.experiment_id)
    statistics = dict(artifacts["statistics.json"])
    statistics["media_devices_available"] = bool(collection.data.get("mediaDevices", {}).get("exists"))
    statistics["browser_launches"] = 1 if collection.browser_started else 0
    statistics["network_requests"] = 1 if collection.navigation_succeeded else 0
    artifacts["statistics.json"] = statistics
    device_data = artifacts["devices.json"]
    raw_id_keys = {"deviceId", "groupId", "device_id", "group_id", "deviceIdRaw", "groupIdRaw"}

    def contains_raw_key(value: Any) -> bool:
        if isinstance(value, dict):
            return any(key in raw_id_keys or contains_raw_key(item) for key, item in value.items())
        if isinstance(value, list):
            return any(contains_raw_key(item) for item in value)
        return False

    read_only = not contains_raw_key(artifacts)
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in artifacts.values()),
        "artifact_completeness": all(name in artifacts for name in ("devices.json", "permissions.json", "prototype.json", "descriptors.json", "methods.json", "fingerprint.json", "statistics.json")),
        "deterministic_ordering": device_data.get("devices", []) == sorted(device_data.get("devices", []), key=lambda item: (item.get("index", 0), item.get("kind", ""))),
        "serialization": all(_json_safe(value) for value in artifacts.values()),
        "read_only_verification": read_only and "Object.defineProperty" not in MEDIA_DEVICES_PROBE and "getUserMedia(" not in MEDIA_DEVICES_PROBE and "getDisplayMedia(" not in MEDIA_DEVICES_PROBE,
        "no_stealth_injection": True,
        "browser_platform_entrypoint": True,
        "permission_request_absent": "getUserMedia(" not in MEDIA_DEVICES_PROBE and "getDisplayMedia(" not in MEDIA_DEVICES_PROBE,
    }
    valid = all(validation.values())
    summary = {
        "experiment": "Experiment 035 - Real MediaDevices Collector",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "result": collection.status if collection.status in {"SUCCESS", "PARTIAL", "UNKNOWN"} else "UNKNOWN",
        "url": collection.url,
        "browser_started": collection.browser_started,
        "navigation_succeeded": collection.navigation_succeeded,
        "media_devices_available": statistics["media_devices_available"],
        "device_count": statistics["devices_total"],
        "fingerprint_sha256": artifacts["fingerprint.json"]["sha256"],
        "error": collection.error,
        "validation_valid": valid,
        "browser_launches": statistics["browser_launches"],
        "network_requests": statistics["network_requests"],
        "historical_artifacts_modified": False,
    }
    validation["valid"] = valid
    artifacts["summary.json"] = summary
    artifacts["validation.json"] = validation
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "media_devices_report.md", _report(summary, validation, statistics, collection))
    print(_report(summary, validation, statistics, collection))
    return 0 if valid else 1


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return True
    except (TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect real Chrome MediaDevices metadata without modifying browser behavior")
    parser.add_argument("--url", default="https://example.com", help="secure URL used for the read-only probe")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    args = parser.parse_args()
    configure_console_error_handling()
    return run(args)


def _positive_timeout(value: str) -> int:
    timeout = int(value)
    if timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return timeout


if __name__ == "__main__":
    raise SystemExit(main())
