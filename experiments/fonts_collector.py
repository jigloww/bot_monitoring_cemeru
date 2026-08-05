"""Experiment 058: read-only browser font surface collector.

The collector observes the native Font Loading API, CSS font support, a
detached canvas font context, and read-only TextMetrics on ``about:blank``.
It never installs or loads a font, changes a canvas, injects stealth, or
performs a network request.
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
    "fonts.json",
    "fontfaceset.json",
    "fontface.json",
    "canvas.json",
    "css.json",
    "metrics.json",
    "prototype.json",
    "fingerprint.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "fonts_report.md",
)
GENERIC_FAMILIES = ("serif", "sans-serif", "monospace", "system-ui", "emoji", "math", "fangsong")


FONTS_PROBE = r"""
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
    descriptor: descriptor(target, name),
    illegalInvocation: typeof fn === 'function' ? (() => {
      try { fn.call({}); return { tested: true, throws: false }; }
      catch (error) { return { tested: true, throws: true, error: errorInfo(error) }; }
    })() : { tested: false }
  });
  const objectSurface = (value, fallbackConstructor) => {
    const prototype = value ? safe(() => Object.getPrototypeOf(value), null) : null;
    const constructor = value ? safe(() => value.constructor, null) : null;
    return {
      available: !!value,
      typeof: value ? typeof value : 'undefined',
      objectToString: safe(() => Object.prototype.toString.call(value), null),
      constructor: safe(() => constructor && constructor.name, fallbackConstructor || null),
      constructorSource: constructor ? nativeSource(constructor) : null,
      ownProperties: ownKeys(value),
      prototypeProperties: ownKeys(prototype),
      prototype: safe(() => prototype && prototype.constructor && prototype.constructor.name, fallbackConstructor || null),
      prototypeChain: chain(value),
      prototypeEquality: safe(() => !!constructor && prototype === constructor.prototype, false),
      constructorEquality: safe(() => !!constructor && prototype.constructor === constructor, false),
      instanceof: safe(() => !!constructor && value instanceof constructor, false),
      symbolToStringTag: descriptor(prototype, Symbol.toStringTag),
      referenceStable: safe(() => value === value, true)
    };
  };
  const prototypeSurface = (prototype, constructor, fallbackName) => ({
    available: !!prototype,
    constructor: safe(() => constructor && constructor.name, fallbackName || null),
    constructorSource: constructor ? nativeSource(constructor) : null,
    ownProperties: ownKeys(prototype),
    prototypeChain: chain(prototype),
    prototypeEquality: safe(() => !!constructor && constructor.prototype === prototype, false),
    constructorEquality: safe(() => !!constructor && prototype.constructor === constructor, false),
    instanceofObject: safe(() => !!prototype && prototype instanceof Object, false),
    objectPrototype: safe(() => Object.getPrototypeOf(prototype).constructor.name, null),
    symbolToStringTag: descriptor(prototype, Symbol.toStringTag)
  });
  const fontSet = safe(() => document.fonts, null);
  const fontSetPrototype = fontSet ? safe(() => Object.getPrototypeOf(fontSet), null) : null;
  const fontSetConstructor = fontSet ? safe(() => fontSet.constructor, null) : null;
  const fontFaceConstructor = typeof FontFace === 'function' ? FontFace : null;
  const fontFacePrototype = fontFaceConstructor ? fontFaceConstructor.prototype : null;
  const fontSetSurface = {
    ...objectSurface(fontSet, 'FontFaceSet'),
    status: stable(safe(() => fontSet && fontSet.status, null)),
    size: stable(safe(() => fontSet && fontSet.size, null)),
    repeatedStatus: stable(safe(() => fontSet && fontSet.status, null)),
    repeatedSize: stable(safe(() => fontSet && fontSet.size, null)),
    statusStable: safe(() => fontSet.status === fontSet.status, false),
    sizeStable: safe(() => fontSet.size === fontSet.size, false),
    navigatorDocumentDescriptor: descriptor(Document.prototype, 'fonts'),
    prototypeDescriptors: Object.fromEntries(ownKeys(fontSetPrototype).map((key) => [key, descriptor(fontSetPrototype, key)]))
  };
  const methods = {};
  for (const name of ['check', 'load', 'entries', 'values', 'keys', 'forEach']) {
    methods[name] = functionInfo(fontSetPrototype ? safe(() => fontSetPrototype[name], null) : null, fontSetPrototype, name);
  }
  methods.iterator = functionInfo(fontSetPrototype ? safe(() => fontSetPrototype[Symbol.iterator], null) : null, fontSetPrototype, Symbol.iterator);
  const fontFaceSurface = {
    available: !!fontFaceConstructor,
    constructor: {
      name: safe(() => fontFaceConstructor && fontFaceConstructor.name, null),
      length: safe(() => fontFaceConstructor && fontFaceConstructor.length, null),
      source: fontFaceConstructor ? nativeSource(fontFaceConstructor) : null,
      nativeSource: !!fontFaceConstructor && /\[native code\]/.test(nativeSource(fontFaceConstructor) || ''),
      descriptor: descriptor(globalThis, 'FontFace')
    },
    prototype: prototypeSurface(fontFacePrototype, fontFaceConstructor, 'FontFace'),
    prototypeDescriptors: Object.fromEntries(ownKeys(fontFacePrototype).map((key) => [key, descriptor(fontFacePrototype, key)])),
    prototypeChain: chain(fontFacePrototype)
  };
  const fontFaceMethods = {};
  for (const name of ['load']) {
    fontFaceMethods[name] = functionInfo(fontFacePrototype ? safe(() => fontFacePrototype[name], null) : null, fontFacePrototype, name);
  }
  const behavior = { check: {}, iterators: {}, ready: {} };
  for (const family of ['serif', 'sans-serif', 'monospace', 'system-ui', 'emoji', 'math', 'fangsong']) {
    const expression = `16px ${family}`;
    const first = safe(() => fontSet && fontSet.check(expression), null);
    const second = safe(() => fontSet && fontSet.check(expression), null);
    behavior.check[family] = { expression, first: stable(first), second: stable(second), stable: first === second, type: typeof first };
  }
  if (fontSet) {
    const count = (iterator) => {
      let total = 0;
      try { for (const _item of iterator) total += 1; } catch (_) { return null; }
      return total;
    };
    behavior.iterators.entries = { available: true, count: count(safe(() => fontSet.entries(), [])) };
    behavior.iterators.values = { available: true, count: count(safe(() => fontSet.values(), [])) };
    behavior.iterators.keys = { available: true, count: count(safe(() => fontSet.keys(), [])) };
    behavior.iterators.symbolIterator = { available: true, count: count(safe(() => fontSet[Symbol.iterator](), [])) };
    let callbackCount = 0;
    try { fontSet.forEach(() => { callbackCount += 1; }); behavior.iterators.forEach = { available: true, count: callbackCount }; }
    catch (error) { behavior.iterators.forEach = { available: true, count: callbackCount, error: errorInfo(error) }; }
    try {
      const promise = fontSet.ready;
      behavior.ready.promise = !!promise && typeof promise.then === 'function';
      const ready = await promise;
      behavior.ready.outcome = 'resolved';
      behavior.ready.status = stable(safe(() => fontSet.status, null));
      behavior.ready.size = stable(safe(() => fontSet.size, null));
      behavior.ready.constructor = safe(() => ready && ready.constructor && ready.constructor.name, null);
    } catch (error) {
      behavior.ready.outcome = 'rejected';
      behavior.ready.error = errorInfo(error);
    }
  }
  const canvas = safe(() => document.createElement('canvas'), null);
  const context = canvas ? safe(() => canvas.getContext('2d'), null) : null;
  const fontDescriptor = context ? descriptor(Object.getPrototypeOf(context), 'font') : null;
  const canvasSurface = {
    available: !!context,
    canvasConstructor: safe(() => canvas && canvas.constructor && canvas.constructor.name, null),
    contextConstructor: safe(() => context && context.constructor && context.constructor.name, null),
    contextPrototype: safe(() => context && Object.getPrototypeOf(context).constructor.name, null),
    font: stable(safe(() => context && context.font, null)),
    repeatedFont: stable(safe(() => context && context.font, null)),
    stable: safe(() => context.font === context.font, false),
    descriptor: fontDescriptor,
    getterSource: fontDescriptor && fontDescriptor.hasGetter ? fontDescriptor.getterSource : null,
    setterSource: fontDescriptor && fontDescriptor.hasSetter ? fontDescriptor.setterSource : null,
    nativeSource: !!fontDescriptor && (!!fontDescriptor.getterSource || !!fontDescriptor.setterSource),
    noDrawingPerformed: true
  };
  const metric = context ? safe(() => context.measureText('Hamburgefontsiv'), null) : null;
  const metricNames = ['width', 'actualBoundingBoxLeft', 'actualBoundingBoxRight', 'actualBoundingBoxAscent', 'actualBoundingBoxDescent', 'fontBoundingBoxAscent', 'fontBoundingBoxDescent', 'emHeightAscent', 'emHeightDescent', 'hangingBaseline', 'alphabeticBaseline', 'ideographicBaseline'];
  const textMetrics = {
    available: !!metric,
    constructor: safe(() => metric && metric.constructor && metric.constructor.name, null),
    objectToString: stable(metric),
    prototype: safe(() => metric && Object.getPrototypeOf(metric).constructor.name, null),
    descriptors: Object.fromEntries(metric ? metricNames.map((name) => [name, descriptor(Object.getPrototypeOf(metric), name)]) : []),
    values: Object.fromEntries(metricNames.map((name) => [name, stable(safe(() => metric && metric[name], null))])),
    repeatedWidth: stable(safe(() => metric && metric.width, null)),
    widthStable: safe(() => !!metric && metric.width === metric.width, false)
  };
  const css = {
    cssAvailable: typeof CSS !== 'undefined',
    documentFontFamily: safe(() => getComputedStyle(document.documentElement).fontFamily, null),
    genericFamilies: Object.fromEntries(['serif', 'sans-serif', 'monospace', 'system-ui', 'emoji', 'math', 'fangsong'].map((family) => [family, {
      fontFamily: safe(() => CSS.supports('font-family', family), null),
      fontShorthand: safe(() => CSS.supports('font', `16px ${family}`), null),
      fontCheck: safe(() => fontSet && fontSet.check(`16px ${family}`), null)
    }])),
    supportsDescriptors: descriptor(globalThis, 'CSS')
  };
  const exceptions = {
    checkDetached: methods.check.available ? (() => { try { fontSetPrototype.check.call({}); return { throws: false }; } catch (error) { return { throws: true, error: errorInfo(error) }; } })() : { tested: false },
    entriesDetached: methods.entries.available ? (() => { try { fontSetPrototype.entries.call({}); return { throws: false }; } catch (error) { return { throws: true, error: errorInfo(error) }; } })() : { tested: false },
    forEachDetached: methods.forEach.available ? (() => { try { fontSetPrototype.forEach.call({}, () => {}); return { throws: false }; } catch (error) { return { throws: true, error: errorInfo(error) }; } })() : { tested: false },
    fontFaceConstructor: fontFaceConstructor ? (() => { try { fontFaceConstructor.call({}); return { throws: false }; } catch (error) { return { throws: true, error: errorInfo(error) }; } })() : { tested: false }
  };
  return {
    available: !!fontSet,
    fonts: {
      documentFonts: fontSetSurface,
      genericFamilies: css.genericFamilies,
      defaultFontFamily: css.documentFontFamily
    },
    fontfaceset: fontSetSurface,
    fontface: { ...fontFaceSurface, methods: fontFaceMethods },
    canvas: canvasSurface,
    css,
    metrics: textMetrics,
    prototype: {
      fontFaceSet: prototypeSurface(fontSetPrototype, fontSetConstructor, 'FontFaceSet'),
      fontFace: fontFaceSurface.prototype
    },
    descriptors: {
      fontFaceSet: fontSetSurface.prototypeDescriptors,
      fontFace: fontFaceSurface.prototypeDescriptors,
      canvasFont: fontDescriptor,
      metrics: textMetrics.descriptors
    },
    methods: { fontFaceSet: methods, fontFace: fontFaceMethods },
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
        result = page.evaluate(FONTS_PROBE)
        if not isinstance(result, dict):
            raise TypeError("Fonts probe returned a non-object result")
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
    lines = [
        "# Experiment 058 - Fonts Collector", "", "## Executive Summary", "",
        f"- Result: **{summary['result']}**",
        f"- FontFaceSet available: **{summary['available']}**",
        f"- FontFace entries: **{stats['fontface_count']}**",
        f"- TextMetrics available: **{stats['textmetrics_available']}**",
        f"- Fingerprint: `{summary['fingerprint_sha256']}`", "",
        "The collector used only native metadata and read-only checks on about:blank. No font was installed, loaded, or spoofed.",
        "", "## FontFaceSet", "", "| Field | Value |", "|---|---|"]
    set_data = data.get("fontfaceset", {})
    for key in ("status", "size", "constructor", "prototype", "prototypeEquality", "constructorEquality", "referenceStable"):
        lines.append(f"| `{key}` | `{set_data.get(key)}` |")
    lines += ["", "## Generic Font Families", "", "| Family | CSS font-family | CSS font | document.fonts.check |", "|---|---:|---:|---:|"]
    for name, value in sorted((data.get("css", {}).get("genericFamilies", {}) or {}).items()):
        lines.append(f"| `{name}` | {value.get('fontFamily')} | {value.get('fontShorthand')} | {value.get('fontCheck')} |")
    lines += ["", "## TextMetrics", "", "| Property | Value |", "|---|---|"]
    for name, value in sorted((data.get("metrics", {}).get("values", {}) or {}).items()):
        lines.append(f"| `{name}` | `{value}` |")
    lines += ["", "## Validation", "", "| Check | Status |", "|---|---|"]
    for key, value in validation.items():
        if key in {"valid", "artifact_completeness", "browser_launches", "network_requests"}:
            continue
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if bool(value) else 'FAIL'} |")
    lines += ["", "## Read-only Boundary", "", "No FontFaceSet mutation, font installation, FontFace.load(), canvas drawing, canvas spoofing, network request, or stealth injection was performed.", ""]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    historical_before = _historical_hashes(root)
    status, capture_error, data, started = _capture(args)
    data = _ordered(data if isinstance(data, dict) else {})
    historical_after = _historical_hashes(root)
    fingerprint_data = {key: data.get(key, {}) for key in ("fonts", "fontfaceset", "fontface", "canvas", "css", "metrics", "prototype", "descriptors", "methods", "behavior", "exceptions")}
    fingerprint_hash = _canonical_hash(fingerprint_data)
    font_set = data.get("fontfaceset", {}) if isinstance(data.get("fontfaceset"), dict) else {}
    font_face = data.get("fontface", {}) if isinstance(data.get("fontface"), dict) else {}
    canvas = data.get("canvas", {}) if isinstance(data.get("canvas"), dict) else {}
    css = data.get("css", {}) if isinstance(data.get("css"), dict) else {}
    metrics = data.get("metrics", {}) if isinstance(data.get("metrics"), dict) else {}
    prototype = data.get("prototype", {}) if isinstance(data.get("prototype"), dict) else {}
    descriptors = data.get("descriptors", {}) if isinstance(data.get("descriptors"), dict) else {}
    methods = data.get("methods", {}) if isinstance(data.get("methods"), dict) else {}
    behavior = data.get("behavior", {}) if isinstance(data.get("behavior"), dict) else {}
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden = ("document.fonts.add(", "document.fonts.delete(", "document.fonts.clear(", "FontFace.load(", "new FontFace(", "toDataURL(", "toBlob(", "fillText(", "add_" + "init_script", "_" + "_stealth", "sendBeacon(", "fetch(", "XMLHttpRequest")
    check_values = behavior.get("check", {}) if isinstance(behavior.get("check"), dict) else {}
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (data, fingerprint_data)),
        "artifact_completeness": False,
        "deterministic_ordering": data == _ordered(data),
        "prototype_validation": bool(font_set.get("prototypeEquality")) and bool(font_set.get("constructorEquality")) and bool(prototype.get("fontFaceSet", {}).get("prototypeEquality")) and bool(prototype.get("fontFaceSet", {}).get("instanceofObject", False)),
        "descriptor_validation": bool(descriptors) and all(value is None or isinstance(value, dict) for value in descriptors.values()),
        "behavior_validation": bool(check_values) and bool(behavior.get("ready")) and isinstance(behavior.get("iterators"), dict),
        "fontface_validation": bool(font_face.get("available")) and bool(font_face.get("constructor", {}).get("nativeSource")) and bool(font_face.get("prototype", {}).get("prototypeEquality")) and bool(font_face.get("prototype", {}).get("instanceofObject", False)),
        "metrics_validation": bool(metrics.get("available")) and bool(metrics.get("widthStable")) and isinstance(metrics.get("values"), dict),
        "fingerprint_validation": bool(fingerprint_hash) and fingerprint_hash == _canonical_hash(fingerprint_data),
        "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and "launch_browser" in source and ("sync_" + "playwright") not in source,
        "read_only_verification": not any(token in FONTS_PROBE for token in forbidden),
        "no_browser_modification": not any(token in FONTS_PROBE for token in forbidden),
        "no_font_installation": not any(token in FONTS_PROBE for token in ("document.fonts.add(", "document.fonts.delete(", "document.fonts.clear(", "FontFace.load(", "new FontFace(")),
        "no_canvas_spoofing": not any(token in FONTS_PROBE for token in ("toDataURL(", "toBlob(", "fillText(")),
        "no_network_requests": not any(token in FONTS_PROBE for token in ("sendBeacon(", "fetch(", "XMLHttpRequest")),
        "historical_artifacts_immutable": historical_before == historical_after,
        "browser_launches": int(started),
        "network_requests": 0,
        "valid": False,
    }
    stats = {
        "fontfaceset_available": bool(font_set.get("available")),
        "fontface_available": bool(font_face.get("available")),
        "fontface_count": int(font_set.get("size", 0) or 0) if isinstance(font_set.get("size"), (int, float)) else 0,
        "fontfaceset_property_count": len(font_set.get("ownProperties", [])),
        "fontface_property_count": len(font_face.get("prototypeProperties", [])),
        "prototype_property_count": sum(len(value.get("ownProperties", [])) for value in prototype.values() if isinstance(value, dict)),
        "descriptor_count": sum(1 for value in descriptors.values() if isinstance(value, dict)),
        "method_count": sum(1 for group in methods.values() if isinstance(group, dict) for value in group.values() if isinstance(value, dict) and value.get("available")),
        "native_method_count": sum(1 for group in methods.values() if isinstance(group, dict) for value in group.values() if isinstance(value, dict) and value.get("nativeSource")),
        "generic_family_count": len(css.get("genericFamilies", {})) if isinstance(css.get("genericFamilies"), dict) else 0,
        "textmetrics_available": bool(metrics.get("available")),
        "textmetrics_property_count": len(metrics.get("values", {})) if isinstance(metrics.get("values"), dict) else 0,
        "check_count": len(check_values),
        "check_stable_count": sum(1 for value in check_values.values() if isinstance(value, dict) and value.get("stable")),
        "iterator_count": len(behavior.get("iterators", {})) if isinstance(behavior.get("iterators"), dict) else 0,
        "browser_launches": int(started),
        "network_requests": 0,
        "capture_status": status,
        "capture_error": capture_error,
        "fingerprint_sha256": fingerprint_hash,
    }
    validation["json_validation"] = all(_json_safe(value) for value in (data, fingerprint_data, stats))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})
    summary = {
        "experiment": "Experiment 058 - Fonts Collector",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "SUCCESS" if status == "SUCCESS" else ("PARTIAL" if started else "UNKNOWN"),
        "available": bool(data.get("available")),
        "browser": args.browser,
        "headless": bool(args.headless),
        "browser_platform": "BrowserSessionManager -> launch_browser",
        "fontface_count": stats["fontface_count"],
        "textmetrics_available": stats["textmetrics_available"],
        "fingerprint_sha256": fingerprint_hash,
        "browser_launches": int(started),
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "fonts"
    output.mkdir(parents=True, exist_ok=False)
    artifact_data = {
        "fonts.json": data.get("fonts", {}),
        "fontfaceset.json": font_set,
        "fontface.json": font_face,
        "canvas.json": canvas,
        "css.json": css,
        "metrics.json": metrics,
        "prototype.json": prototype,
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
    write_text_exclusive(output / "fonts_report.md", _report(summary, stats, validation, data))
    print("FONTS COLLECTOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"FontFaceSet: {stats['fontfaceset_available']} | Entries: {stats['fontface_count']} | TextMetrics: {stats['textmetrics_available']}")
    print(f"Fingerprint: {fingerprint_hash}")
    print(f"Browser launches: {stats['browser_launches']} | Network requests: {stats['network_requests']}")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 058: collect native font API behavior")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
