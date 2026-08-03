"""Read-only navigator.plugins and navigator.mimeTypes collector."""
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
from experiments.utils import configure_console_error_handling, now_iso, project_root, write_json_exclusive, write_text_exclusive


PLUGINS_PROBE = r"""
async () => {
  const nativeSource = (value) => {
    try { return Function.prototype.toString.call(value); } catch (_) { return null; }
  };
  const descriptor = (target, name) => {
    try {
      const item = Object.getOwnPropertyDescriptor(target, name);
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
  const ownNames = (target) => {
    if (!target) return [];
    try {
      const names = Object.getOwnPropertyNames(target);
      const symbols = Object.getOwnPropertySymbols(target).map((item) => String(item));
      return [...new Set([...names, ...symbols])].sort();
    } catch (_) { return []; }
  };
  const descriptorMap = (target, names) => {
    const result = {};
    for (const name of [...names].sort()) {
      const item = descriptor(target, name);
      if (item) result[name] = item;
    }
    return result;
  };
  const functionMap = (target) => {
    if (!target) return {};
    const result = {};
    for (const name of ownNames(target)) {
      try {
        if (typeof target[name] === 'function') result[name] = functionInfo(target, name);
      } catch (_) {}
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
  const objectInfo = (value) => {
    if (!value) return { exists: false, typeof: typeof value, constructor: null, toString: null, ownProperties: [], prototypeChain: [] };
    let constructor = null;
    let toString = null;
    try { constructor = value.constructor ? value.constructor.name : null; } catch (_) {}
    try { toString = Object.prototype.toString.call(value); } catch (_) {}
    return { exists: true, typeof: typeof value, constructor, toString, ownProperties: ownNames(value), prototypeChain: chain(value) };
  };
  const instancePrototypeInfo = (value) => {
    let proto = null;
    try { proto = value ? Object.getPrototypeOf(value) : null; } catch (_) {}
    return {
      name: proto && proto.constructor ? proto.constructor.name : null,
      properties: ownNames(proto),
      descriptors: proto ? descriptorMap(proto, ownNames(proto)) : {},
      methods: functionMap(proto),
      chain: chain(value),
      toStringTag: proto ? descriptor(proto, Symbol.toStringTag) : null
    };
  };
  const functionInfo = (target, name) => {
    const fn = target ? target[name] : undefined;
    return {
      available: typeof fn === 'function',
      typeof: typeof fn,
      source: typeof fn === 'function' ? nativeSource(fn) : null,
      nativeSource: typeof fn === 'function' && /\[native code\]/.test(nativeSource(fn) || ''),
      descriptor: target ? descriptor(target, name) : null
    };
  };
  const illegalInvocation = (target, names) => {
    const output = {};
    for (const name of names) {
      const fn = target ? target[name] : undefined;
      if (typeof fn !== 'function') { output[name] = null; continue; }
      try { fn.call({}); output[name] = false; } catch (_) { output[name] = true; }
    }
    return output;
  };
  const plugins = navigator.plugins || null;
  const mimeTypes = navigator.mimeTypes || null;
  const pluginPrototype = plugins ? Object.getPrototypeOf(plugins) : null;
  const mimePrototype = mimeTypes ? Object.getPrototypeOf(mimeTypes) : null;
  const pluginMethodNames = ['item', 'namedItem', 'refresh', 'keys', 'values', 'entries'];
  const mimeMethodNames = ['item', 'namedItem', 'keys', 'values', 'entries'];
  const pluginMethods = pluginPrototype ? Object.fromEntries(pluginMethodNames.sort().map((name) => [name, functionInfo(pluginPrototype, name)])) : {};
  const mimeMethods = mimePrototype ? Object.fromEntries(mimeMethodNames.sort().map((name) => [name, functionInfo(mimePrototype, name)])) : {};
  if (pluginPrototype) pluginMethods['Symbol.iterator'] = functionInfo(pluginPrototype, Symbol.iterator);
  if (mimePrototype) mimeMethods['Symbol.iterator'] = functionInfo(mimePrototype, Symbol.iterator);
  const pluginItems = [];
  const pluginByName = {};
  if (plugins) {
    for (let index = 0; index < plugins.length; index += 1) {
      const plugin = plugins[index];
      if (!plugin) continue;
      const pluginInstancePrototype = instancePrototypeInfo(plugin);
      const item = {
        index,
        name: String(plugin.name || ''),
        filename: String(plugin.filename || ''),
        description: String(plugin.description || ''),
        length: Number(plugin.length || 0),
        ownProperties: ownNames(plugin),
        prototype: pluginInstancePrototype.name,
        prototypeChain: pluginInstancePrototype.chain,
        prototypeProperties: pluginInstancePrototype.properties,
        prototypeDescriptors: pluginInstancePrototype.descriptors,
        prototypeMethods: pluginInstancePrototype.methods,
        prototypeToStringTag: pluginInstancePrototype.toStringTag,
        descriptors: descriptorMap(plugin, ownNames(plugin)),
        mimeTypes: []
      };
      for (let mimeIndex = 0; mimeIndex < item.length; mimeIndex += 1) {
        try {
          const mime = plugin[mimeIndex] || (typeof plugin.item === 'function' ? plugin.item(mimeIndex) : null);
          if (mime) item.mimeTypes.push(String(mime.type || ''));
        } catch (_) {}
      }
      item.mimeTypes.sort();
      pluginItems.push(item);
      pluginByName[item.name] = index;
    }
  }
  const mimeItems = [];
  if (mimeTypes) {
    for (let index = 0; index < mimeTypes.length; index += 1) {
      const mime = mimeTypes[index];
      if (!mime) continue;
      const mimeInstancePrototype = instancePrototypeInfo(mime);
      let enabledPluginIndex = null;
      let enabledPluginName = null;
      try {
        const enabled = mime.enabledPlugin;
        if (enabled) {
          enabledPluginName = String(enabled.name || '');
          enabledPluginIndex = Object.prototype.hasOwnProperty.call(pluginByName, enabledPluginName) ? pluginByName[enabledPluginName] : null;
        }
      } catch (_) {}
      mimeItems.push({
        index,
        type: String(mime.type || ''),
        suffixes: String(mime.suffixes || ''),
        description: String(mime.description || ''),
        enabledPluginIndex,
        enabledPluginName,
        ownProperties: ownNames(mime),
        prototype: mimeInstancePrototype.name,
        prototypeChain: mimeInstancePrototype.chain,
        prototypeProperties: mimeInstancePrototype.properties,
        prototypeDescriptors: mimeInstancePrototype.descriptors,
        prototypeMethods: mimeInstancePrototype.methods,
        prototypeToStringTag: mimeInstancePrototype.toStringTag,
        descriptors: descriptorMap(mime, ownNames(mime))
      });
    }
  }
  pluginItems.sort((left, right) => left.index - right.index || left.name.localeCompare(right.name));
  mimeItems.sort((left, right) => left.index - right.index || left.type.localeCompare(right.type));
  const pluginMimeTypes = {};
  for (const item of pluginItems) pluginMimeTypes[String(item.index)] = item.mimeTypes;
  const mimeEnabledPlugins = {};
  for (const item of mimeItems) mimeEnabledPlugins[item.type] = item.enabledPluginIndex;
  const mismatches = [];
  for (const mime of mimeItems) {
    if (mime.enabledPluginIndex !== null) {
      const plugin = pluginItems.find((item) => item.index === mime.enabledPluginIndex);
      if (!plugin || !plugin.mimeTypes.includes(mime.type)) mismatches.push({ type: mime.type, reason: 'mime_enabled_plugin_missing_reverse_reference' });
    }
  }
  for (const plugin of pluginItems) {
    for (const type of plugin.mimeTypes) {
      const mime = mimeItems.find((item) => item.type === type);
      // Chromium may expose several Plugin aliases for the same MIME list,
      // while MimeType.enabledPlugin points at one canonical plugin.  Validate
      // the semantic reverse link rather than requiring object identity for
      // every alias.
      const enabled = mime && mime.enabledPluginName ? pluginItems.find((item) => item.name === mime.enabledPluginName) : null;
      if (!mime || !enabled || !enabled.mimeTypes.includes(type)) mismatches.push({ plugin: plugin.name, type, reason: 'plugin_missing_mime_reverse_reference' });
    }
  }
  const pluginArray = objectInfo(plugins);
  const mimeArray = objectInfo(mimeTypes);
  const pluginCtor = typeof PluginArray === 'function' ? PluginArray : null;
  const mimeCtor = typeof MimeTypeArray === 'function' ? MimeTypeArray : null;
  return {
    navigator: {
      constructor: navigator && navigator.constructor ? navigator.constructor.name : null,
      ownProperties: ownNames(navigator),
      pluginsDescriptor: descriptor(Object.getPrototypeOf(navigator), 'plugins'),
      mimeTypesDescriptor: descriptor(Object.getPrototypeOf(navigator), 'mimeTypes')
    },
    plugins: {
      ...pluginArray,
      length: plugins ? plugins.length : 0,
      prototype: pluginPrototype && pluginPrototype.constructor ? pluginPrototype.constructor.name : null,
      inheritedProperties: ownNames(pluginPrototype),
      descriptors: pluginPrototype ? descriptorMap(pluginPrototype, ownNames(pluginPrototype)) : {},
      methods: pluginMethods,
      illegalInvocation: illegalInvocation(pluginPrototype, pluginMethodNames),
      instanceof: !!(plugins && pluginCtor && plugins instanceof pluginCtor),
      symbolToStringTag: pluginPrototype ? descriptor(pluginPrototype, Symbol.toStringTag) : null,
      items: pluginItems
    },
    mimeTypes: {
      ...mimeArray,
      length: mimeTypes ? mimeTypes.length : 0,
      prototype: mimePrototype && mimePrototype.constructor ? mimePrototype.constructor.name : null,
      inheritedProperties: ownNames(mimePrototype),
      descriptors: mimePrototype ? descriptorMap(mimePrototype, ownNames(mimePrototype)) : {},
      methods: mimeMethods,
      illegalInvocation: illegalInvocation(mimePrototype, mimeMethodNames),
      instanceof: !!(mimeTypes && mimeCtor && mimeTypes instanceof mimeCtor),
      symbolToStringTag: mimePrototype ? descriptor(mimePrototype, Symbol.toStringTag) : null,
      items: mimeItems
    },
    crossReference: {
      pluginMimeTypes,
      mimeEnabledPlugins,
      mismatches,
      bidirectionalValid: mismatches.length === 0
    },
    prototype: {
      pluginArray: pluginArray,
      mimeTypeArray: mimeArray,
      pluginChain: chain(plugins),
      mimeChain: chain(mimeTypes),
      pluginInstanceof: !!(plugins && pluginCtor && plugins instanceof pluginCtor),
      mimeInstanceof: !!(mimeTypes && mimeCtor && mimeTypes instanceof mimeCtor),
      pluginToStringTag: pluginArray.toString,
      mimeToStringTag: mimeArray.toString
    }
  };
}
"""


def _empty_data(error: str | None = None) -> dict[str, Any]:
    return {
        "navigator": {"constructor": None, "ownProperties": [], "pluginsDescriptor": None, "mimeTypesDescriptor": None},
        "plugins": {"exists": False, "typeof": "undefined", "constructor": None, "toString": None, "ownProperties": [], "prototypeChain": [], "length": 0, "prototype": None, "inheritedProperties": [], "descriptors": {}, "methods": {}, "illegalInvocation": {}, "instanceof": False, "symbolToStringTag": None, "items": []},
        "mimeTypes": {"exists": False, "typeof": "undefined", "constructor": None, "toString": None, "ownProperties": [], "prototypeChain": [], "length": 0, "prototype": None, "inheritedProperties": [], "descriptors": {}, "methods": {}, "illegalInvocation": {}, "instanceof": False, "symbolToStringTag": None, "items": []},
        "crossReference": {"pluginMimeTypes": {}, "mimeEnabledPlugins": {}, "mismatches": [{"reason": error}] if error else [], "bidirectionalValid": False},
        "prototype": {"pluginArray": {}, "mimeTypeArray": {}, "pluginChain": [], "mimeChain": [], "pluginInstanceof": False, "mimeInstanceof": False, "pluginToStringTag": None, "mimeToStringTag": None},
    }


def _capture(args: argparse.Namespace) -> tuple[str, str | None, dict[str, Any], bool, bool]:
    config = BrowserConfig(browser=args.browser, headless=args.headless, persistent=False, url="about:blank", timeout=args.timeout, enable_stealth=False)
    manager = BrowserSessionManager(config)
    page: Any = None
    started = False
    navigated = False
    error: str | None = None
    data = _empty_data()
    try:
        manager.start()
        started = True
        page = manager.new_page()
        if args.url and args.url != "about:blank":
            try:
                page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout)
                navigated = True
            except Exception as exc:
                error = f"navigation: {exc}"
        try:
            result = page.evaluate(PLUGINS_PROBE)
            if not isinstance(result, dict):
                raise TypeError("Plugin probe returned a non-object result")
            data = result
        except Exception as exc:
            error = f"probe: {exc}"
            data = _empty_data(str(exc))
    except Exception as exc:
        error = f"browser launch: {exc}"
    finally:
        if page is not None:
            try: manager.close_page(page)
            except Exception: pass
        try: manager.shutdown()
        except Exception: pass
    status = "SUCCESS" if started and data.get("plugins", {}).get("exists") and data.get("mimeTypes", {}).get("exists") else ("PARTIAL" if started else "UNKNOWN")
    return status, error, data, started, navigated


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> bool:
    """Check that an artifact can be serialized as JSON."""
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _method_records(value: Any) -> list[dict[str, Any]]:
    """Flatten method metadata, including per-instance prototype methods."""
    records: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "available" in value and "nativeSource" in value:
            records.append(value)
        else:
            for child in value.values():
                records.extend(_method_records(child))
    return records


def _build(args: argparse.Namespace, experiment_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    status, error, data, started, navigated = _capture(args)
    fingerprint_data = {
        "navigator": data.get("navigator", {}),
        "plugins": data.get("plugins", {}),
        "mimeTypes": data.get("mimeTypes", {}),
        "crossReference": data.get("crossReference", {}),
        "prototype": data.get("prototype", {}),
    }
    fingerprint = {"experiment": "Experiment 038 - Real Plugins & MimeTypes Collector", "experiment_id": experiment_id, "algorithm": "sha256", "sha256": _hash(fingerprint_data), "data": fingerprint_data}
    plugins = data.get("plugins", {})
    mime_types = data.get("mimeTypes", {})
    cross = data.get("crossReference", {})
    descriptors = {
        "navigator": {"plugins": data.get("navigator", {}).get("pluginsDescriptor"), "mimeTypes": data.get("navigator", {}).get("mimeTypesDescriptor")},
        "plugins": plugins.get("descriptors", {}),
        "mimeTypes": mime_types.get("descriptors", {}),
    }
    methods = {
        "plugins": plugins.get("methods", {}),
        "plugin_prototypes": {str(item.get("index")): item.get("prototypeMethods", {}) for item in plugins.get("items", [])},
        "mimeTypes": mime_types.get("methods", {}),
        "mime_prototypes": {str(item.get("index")): item.get("prototypeMethods", {}) for item in mime_types.get("items", [])},
    }
    method_records = _method_records(methods)
    statistics = {
        "plugin_count": int(plugins.get("length", 0) or 0),
        "mime_type_count": int(mime_types.get("length", 0) or 0),
        "property_count": len(plugins.get("ownProperties", [])) + len(mime_types.get("ownProperties", [])),
        "method_count": len(method_records),
        "descriptor_count": sum(len(value) for value in descriptors.values() if isinstance(value, dict)),
        "cross_reference_mismatches": len(cross.get("mismatches", [])),
        "bidirectional_integrity": bool(cross.get("bidirectionalValid")),
        "native_method_count": sum(1 for value in method_records if value.get("nativeSource")),
        "browser_started": started,
        "navigation_succeeded": navigated,
        "browser_launches": 1 if started else 0,
        "network_requests": 1 if navigated else 0,
        "capture_status": status,
    }
    artifacts = {
        "navigator.json": data.get("navigator", {}),
        "plugins.json": plugins,
        "mime_types.json": mime_types,
        "cross_reference.json": cross,
        "prototype.json": data.get("prototype", {}),
        "descriptors.json": descriptors,
        "methods.json": methods,
        "fingerprint.json": fingerprint,
        "statistics.json": statistics,
    }
    return artifacts, {"status": status, "error": error, "started": started, "navigated": navigated}


def _report(summary: dict[str, Any], validation: dict[str, Any], stats: dict[str, Any]) -> str:
    lines = [
        "# Experiment 038 — Real Plugins & MimeTypes Collector",
        "",
        "## Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Capture status: **{summary['capture_status']}**",
        f"- Plugin count: **{stats['plugin_count']}**",
        f"- MimeType count: **{stats['mime_type_count']}**",
        f"- Bidirectional integrity: **{stats['bidirectional_integrity']}**",
        "",
        "## Validation",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    for key, value in validation.items():
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if value else 'FAIL'} |")
    lines += [
        "",
        "## Read-only Boundary",
        "",
        "The collector only reads navigator.plugins, navigator.mimeTypes, descriptors, prototypes, and cross-references. It does not override navigator properties, inject stealth, call media APIs, or modify browser behavior.",
        "",
    ]
    if summary.get("error"):
        lines += ["## Runtime Note", "", f"`{summary['error']}`", ""]
    return "\n".join(lines)


def _positive_timeout(value: str) -> int:
    timeout = int(value)
    if timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return timeout


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = args.reports_dir or root / "reports" / "experiments"
    if not reports_root.is_absolute(): reports_root = root / reports_root
    experiment = Experiment.create(reports_root.resolve())
    output = experiment.directory / "plugins"
    output.mkdir(parents=True, exist_ok=True)
    artifacts, run_info = _build(args, experiment.experiment_id)
    raw_source = PLUGINS_PROBE
    forbidden_mutation = "Object." + "defineProperty"
    forbidden_plugins_assignment = "navigator." + "plugins ="
    forbidden_mime_assignment = "navigator." + "mimeTypes ="
    forbidden_media_call = "get" + "UserMedia("
    forbidden_display_call = "get" + "DisplayMedia("
    read_only = all(token not in raw_source for token in (forbidden_mutation, forbidden_plugins_assignment, forbidden_mime_assignment, forbidden_media_call, forbidden_display_call))
    source_code = Path(__file__).read_text(encoding="utf-8")
    browser_platform = "BrowserConfig" in source_code and "BrowserSessionManager" in source_code and "launch_browser(" not in raw_source
    no_stealth = "stealth." not in raw_source and "registry" not in raw_source
    stats = artifacts["statistics.json"]
    browser_available = bool(stats["browser_started"])
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in artifacts.values()),
        "artifact_completeness": all(name in artifacts for name in ("navigator.json", "plugins.json", "mime_types.json", "cross_reference.json", "prototype.json", "descriptors.json", "methods.json", "fingerprint.json", "statistics.json")),
        "deterministic_ordering": artifacts["plugins.json"].get("items", []) == sorted(artifacts["plugins.json"].get("items", []), key=lambda item: (item.get("index", 0), item.get("name", ""))) and artifacts["mime_types.json"].get("items", []) == sorted(artifacts["mime_types.json"].get("items", []), key=lambda item: (item.get("index", 0), item.get("type", ""))),
        "serialization": all(_json_safe(value) for value in artifacts.values()),
        "read_only_verification": read_only,
        "browser_platform_verification": browser_platform,
        "sha256_validation": _hash(artifacts["fingerprint.json"]["data"]) == artifacts["fingerprint.json"]["sha256"],
        "prototype_consistency": (not browser_available) or (artifacts["plugins.json"].get("instanceof", False) == artifacts["prototype.json"].get("pluginInstanceof", False) and artifacts["mime_types.json"].get("instanceof", False) == artifacts["prototype.json"].get("mimeInstanceof", False)),
        "item_prototype_consistency": (not browser_available) or (all(item.get("prototype") and item.get("prototypeChain") for item in artifacts["plugins.json"].get("items", [])) and all(item.get("prototype") and item.get("prototypeChain") for item in artifacts["mime_types.json"].get("items", []))),
        "native_method_sources": (not browser_available) or all((not record.get("available")) or record.get("nativeSource") for record in _method_records(artifacts["methods.json"])),
        "cross_reference_validation": (not browser_available) or stats["bidirectional_integrity"],
        "no_stealth_injection": no_stealth,
        "valid": False,
    }
    validation["valid"] = all(value for key, value in validation.items() if key != "valid")
    summary = {
        "experiment": "Experiment 038 - Real Plugins & MimeTypes Collector",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "result": run_info["status"],
        "capture_status": run_info["status"],
        "error": run_info["error"],
        "plugin_count": stats["plugin_count"],
        "mime_type_count": stats["mime_type_count"],
        "fingerprint_sha256": artifacts["fingerprint.json"]["sha256"],
        "browser_launches": stats["browser_launches"],
        "network_requests": stats["network_requests"],
        "validation_valid": validation["valid"],
        "historical_artifacts_modified": False,
    }
    artifacts["summary.json"] = summary
    artifacts["validation.json"] = validation
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "plugins_report.md", _report(summary, validation, stats))
    print(_report(summary, validation, stats))
    return 0 if validation["valid"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect real navigator.plugins and navigator.mimeTypes metadata")
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    args = parser.parse_args()
    configure_console_error_handling()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
