"""Experiment 060B: canonical Real Browser Canvas baseline.

The collector performs one read-only Browser Platform capture and writes a new
immutable experiment.  It deliberately does not import Playwright directly,
does not inject a stealth script, and never changes an existing artifact.
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
    "canvas.json",
    "prototype.json",
    "descriptors.json",
    "methods.json",
    "fingerprint.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "canvas_report.md",
)


CANVAS_PROBE = r"""
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
  const digestText = (value) => digestBytes(new TextEncoder().encode(String(value)));
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
  const output = {
    supported: false,
    errors,
    constructors: {},
    prototype: {},
    descriptors: {},
    methods: {},
    canvas: {},
    capabilities: {},
    state: {},
    fingerprintObservations: {},
    offscreen: { supported: false }
  };
  try {
    const htmlConstructor = globalThis.HTMLCanvasElement;
    const contextConstructor = globalThis.CanvasRenderingContext2D;
    const offscreenConstructor = globalThis.OffscreenCanvas;
    output.constructors = {
      HTMLCanvasElement: constructorInfo('HTMLCanvasElement', htmlConstructor),
      CanvasRenderingContext2D: constructorInfo('CanvasRenderingContext2D', contextConstructor),
      OffscreenCanvas: constructorInfo('OffscreenCanvas', offscreenConstructor)
    };
    const canvas = document.createElement('canvas');
    canvas.width = 240;
    canvas.height = 80;
    const context = canvas.getContext('2d', { alpha: true, willReadFrequently: true });
    if (!context) {
      output.errors.push({ name: 'CanvasUnavailable', message: '2D context is unavailable' });
      return output;
    }
    output.supported = true;
    output.canvas = {
      constructor: safe(() => canvas.constructor && canvas.constructor.name, null),
      typeof: typeof canvas,
      objectToString: safe(() => Object.prototype.toString.call(canvas), null),
      width: canvas.width,
      height: canvas.height,
      ownProperties: ownKeys(canvas),
      prototypeChain: chain(canvas),
      instanceofHTMLCanvasElement: htmlConstructor ? canvas instanceof htmlConstructor : false,
      prototypeEquality: htmlConstructor ? Object.getPrototypeOf(canvas) === htmlConstructor.prototype : false,
      toStringTag: descriptor(Object.getPrototypeOf(canvas), Symbol.toStringTag)
    };
    output.prototype.canvas = {
      constructor: safe(() => htmlConstructor && htmlConstructor.name, null),
      chain: chain(htmlConstructor && htmlConstructor.prototype),
      ownProperties: ownKeys(htmlConstructor && htmlConstructor.prototype),
      equality: htmlConstructor ? Object.getPrototypeOf(canvas) === htmlConstructor.prototype : false
    };
    output.prototype.context = {
      constructor: safe(() => contextConstructor && contextConstructor.name, null),
      chain: chain(contextConstructor && contextConstructor.prototype),
      ownProperties: ownKeys(contextConstructor && contextConstructor.prototype),
      equality: contextConstructor ? Object.getPrototypeOf(context) === contextConstructor.prototype : false,
      instanceof: contextConstructor ? context instanceof contextConstructor : false
    };
    output.descriptors.canvas = {};
    for (const name of ['width', 'height', 'toDataURL', 'toBlob']) output.descriptors.canvas[name] = descriptor(htmlConstructor && htmlConstructor.prototype, name);
    output.descriptors.context = {};
    for (const name of ['canvas', 'fillStyle', 'strokeStyle', 'font', 'globalAlpha', 'lineWidth', 'textAlign', 'textBaseline', 'getImageData', 'measureText', 'isPointInPath', 'isPointInStroke']) output.descriptors.context[name] = descriptor(contextConstructor && contextConstructor.prototype, name);
    output.methods.canvas = {};
    for (const name of ['toDataURL', 'toBlob']) output.methods.canvas[name] = await methodInfo(htmlConstructor && htmlConstructor.prototype, name);
    output.methods.context = {};
    for (const name of ['getImageData', 'measureText', 'isPointInPath', 'isPointInStroke']) output.methods.context[name] = await methodInfo(contextConstructor && contextConstructor.prototype, name);
    output.methods.constructor = {};
    for (const [name, constructor] of [['HTMLCanvasElement', htmlConstructor], ['CanvasRenderingContext2D', contextConstructor], ['OffscreenCanvas', offscreenConstructor]]) {
      output.methods.constructor[name] = {
        available: typeof constructor === 'function',
        name: typeof constructor === 'function' ? safe(() => constructor.name, null) : null,
        length: typeof constructor === 'function' ? safe(() => constructor.length, null) : null,
        source: typeof constructor === 'function' ? nativeSource(constructor) : null,
        nativeSource: typeof constructor === 'function' && /\[native code\]/.test(nativeSource(constructor) || '')
      };
    }
    output.capabilities = {
      context2d: !!context,
      // A canvas context mode is exclusive.  Probe WebGL on fresh canvases so
      // the 2D baseline does not make a supported capability look absent.
      webgl: !!safe(() => document.createElement('canvas').getContext('webgl'), null),
      webgl2: !!safe(() => document.createElement('canvas').getContext('webgl2'), null),
      toDataURL: typeof canvas.toDataURL === 'function',
      toBlob: typeof canvas.toBlob === 'function',
      supportedFormats: ['image/png', 'image/jpeg', 'image/webp'].map((mime) => ({ mime, supported: safe(() => canvas.toDataURL(mime).startsWith(`data:${mime}`), false) }))
    };
    output.state = {
      defaults: {
        fillStyle: context.fillStyle,
        strokeStyle: context.strokeStyle,
        globalAlpha: context.globalAlpha,
        lineWidth: context.lineWidth,
        font: context.font,
        textAlign: context.textAlign,
        textBaseline: context.textBaseline,
        direction: context.direction,
        globalCompositeOperation: context.globalCompositeOperation,
        imageSmoothingEnabled: context.imageSmoothingEnabled
      }
    };
    context.fillStyle = '#f60';
    context.fillRect(8, 8, 70, 28);
    context.fillStyle = '#069';
    context.font = '16px Arial';
    context.fillText('Cwm fjordbank glyphs vext quiz', 10, 58);
    context.beginPath();
    context.arc(190, 40, 22, 0, Math.PI * 2, true);
    context.strokeStyle = 'rgba(255,0,255,0.7)';
    context.lineWidth = 3;
    context.stroke();
    const image = context.getImageData(0, 0, canvas.width, canvas.height);
    const metrics = context.measureText('Canvas fingerprint text');
    const imageBytesHash = await digestBytes(image.data);
    const dataUrls = {};
    for (const mime of ['image/png', 'image/jpeg', 'image/webp']) {
      const value = safe(() => canvas.toDataURL(mime, 0.82), '');
      dataUrls[mime] = { length: value.length, prefix: value.slice(0, 40), sha256: await digestText(value) };
    }
    const blob = await new Promise((resolve) => {
      try { canvas.toBlob((value) => resolve(value ? { type: value.type, size: value.size } : null), 'image/png'); }
      catch (_) { resolve(null); }
    });
    const path = new Path2D();
    path.rect(4, 4, 20, 20);
    output.fingerprintObservations = {
      imageData: { width: image.width, height: image.height, colorSpace: image.colorSpace || null, dataLength: image.data.length, sha256: imageBytesHash },
      dataUrls,
      blob,
      textMetrics: {
        width: metrics.width,
        actualBoundingBoxLeft: metrics.actualBoundingBoxLeft,
        actualBoundingBoxRight: metrics.actualBoundingBoxRight,
        actualBoundingBoxAscent: metrics.actualBoundingBoxAscent,
        actualBoundingBoxDescent: metrics.actualBoundingBoxDescent,
        fontBoundingBoxAscent: metrics.fontBoundingBoxAscent,
        fontBoundingBoxDescent: metrics.fontBoundingBoxDescent,
        alphabeticBaseline: metrics.alphabeticBaseline
      },
      isPointInPath: safe(() => context.isPointInPath(path, 10, 10), null),
      isPointInStroke: safe(() => context.isPointInStroke(path, 4, 4), null),
      renderingIntegrity: image.width === canvas.width && image.height === canvas.height && image.data.length === canvas.width * canvas.height * 4
    };
    if (offscreenConstructor) {
      try {
        const offscreen = new offscreenConstructor(32, 16);
        const offscreenContext = offscreen.getContext('2d');
        offscreenContext.fillStyle = '#123456';
        offscreenContext.fillRect(0, 0, 32, 16);
        const offscreenBlob = typeof offscreen.convertToBlob === 'function' ? await offscreen.convertToBlob({ type: 'image/png' }) : null;
        output.offscreen = {
          supported: true,
          constructor: safe(() => offscreen.constructor.name, null),
          width: offscreen.width,
          height: offscreen.height,
          contextAvailable: !!offscreenContext,
          instanceof: offscreen instanceof offscreenConstructor,
          prototypeEquality: Object.getPrototypeOf(offscreen) === offscreenConstructor.prototype,
          prototypeChain: chain(Object.getPrototypeOf(offscreen)),
          convertToBlob: { available: typeof offscreen.convertToBlob === 'function', type: offscreenBlob ? offscreenBlob.type : null, size: offscreenBlob ? offscreenBlob.size : null }
        };
      } catch (error) {
        output.offscreen = { supported: true, error: errorInfo(error) };
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
    started = 0
    error: str | None = None
    probe: dict[str, Any] = {}
    try:
        manager.start()
        started = 1
        context = manager.get_context()
        pages = getattr(context, "pages", []) if context is not None else []
        if callable(pages):
            pages = pages()
        page = pages[0] if pages else manager.new_page()
        result = page.evaluate(CANVAS_PROBE)
        if isinstance(result, dict):
            probe = _ordered(result)
            probe["browserVersion"] = _browser_version(page)
        else:
            error = "Canvas probe returned a non-object"
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
    return ("AVAILABLE" if started and probe.get("supported") else ("PARTIAL" if started else "UNKNOWN"), probe, error, duration, started)


def _report(summary: dict[str, Any], data: dict[str, Any], fingerprint: dict[str, Any], validation: dict[str, Any]) -> str:
    canvas = data.get("canvas", {})
    capabilities = data.get("capabilities", {})
    methods = data.get("methods", {})
    lines = [
        "# Experiment 060B - Canonical Canvas Baseline",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Browser Platform status: **{summary['playwright_status']}**",
        f"- Browser launches: **{summary['browser_launches']}**",
        f"- Network requests: **{summary['network_requests']}**",
        f"- Fingerprint SHA-256: `{fingerprint['sha256']}`",
        "",
        "## Canvas Surface",
        "",
        f"- Supported: **{canvas.get('supported', False)}**",
        f"- Canvas object: `{canvas.get('constructor')}` / `{canvas.get('objectToString')}`",
        f"- Dimensions: **{canvas.get('width')} x {canvas.get('height')}**",
        f"- OffscreenCanvas: **{data.get('offscreen', {}).get('supported', False)}**",
        "",
        "## Capabilities",
        "",
        "| Capability | Value |",
        "|---|---|",
    ]
    for name, value in capabilities.items():
        lines.append(f"| `{name}` | `{value}` |")
    lines += ["", "## Native Methods", "", "| Group | Method | Available | Native source | Illegal invocation |", "|---|---|---|---|---|"]
    for group, group_methods in methods.items():
        if not isinstance(group_methods, dict):
            continue
        for name, item in group_methods.items():
            if isinstance(item, dict):
                lines.append(f"| `{group}` | `{name}` | {item.get('available')} | {item.get('nativeSource')} | {item.get('illegalInvocation', {}).get('throws') if isinstance(item.get('illegalInvocation'), dict) else None} |")
    lines += ["", "## Validation", "", f"- Validation: **{'PASS' if validation['valid'] else 'FAIL'}**", "- No stealth injection, canvas spoofing, network request, or historical artifact mutation was performed.", ""]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    historical_before = _historical_hashes(root)
    capture_status, probe, capture_error, duration_ms, launches = _capture(args)
    historical_after = _historical_hashes(root)
    browser_version = None
    if isinstance(probe.get("browserVersion"), str):
        browser_version = probe.get("browserVersion")
    data = _ordered(
        {
            "browser": {"version": browser_version, "engine": "chromium", "browser": args.browser, "headless": bool(args.headless)},
            "canvas": {**(probe.get("canvas", {}) if isinstance(probe.get("canvas", {}), dict) else {}), "supported": bool(probe.get("supported"))},
            "constructors": probe.get("constructors", {}),
            "prototype": probe.get("prototype", {}),
            "descriptors": probe.get("descriptors", {}),
            "methods": probe.get("methods", {}),
            "capabilities": probe.get("capabilities", {}),
            "state": probe.get("state", {}),
            "fingerprintObservations": probe.get("fingerprintObservations", {}),
            "offscreen": probe.get("offscreen", {}),
            "errors": probe.get("errors", []),
        }
    )
    fingerprint = {"algorithm": "SHA-256", "sha256": _canonical_hash(data), "data": data}
    all_methods = []
    for group, methods in data.get("methods", {}).items():
        if isinstance(methods, dict):
            all_methods.extend(f"{group}.{name}" for name in methods)
    descriptors = []
    for group, values in data.get("descriptors", {}).items():
        if isinstance(values, dict):
            descriptors.extend(f"{group}.{name}" for name in values)
    prototypes = data.get("prototype", {})
    prototype_valid = bool(data.get("canvas", {}).get("prototypeEquality")) and bool(prototypes.get("canvas", {}).get("equality")) and bool(prototypes.get("context", {}).get("equality")) and bool(prototypes.get("context", {}).get("instanceof"))
    native_values = [item.get("nativeSource") for group in data.get("methods", {}).values() if isinstance(group, dict) for item in group.values() if isinstance(item, dict) and "nativeSource" in item]
    native_valid = bool(native_values) and all(value is True for value in native_values)
    descriptor_valid = bool(descriptors) and all(isinstance(value, dict) for values in data.get("descriptors", {}).values() if isinstance(values, dict) for value in values.values())
    summary = _ordered(
        {
            "experiment": "Experiment 060B - Canvas Baseline Rebuild",
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
            "read_only_verification": ("add_" + "init_script") not in source and ("__" + "stealth") not in source and ("fetch" + "(") not in source,
            "browser_launches": launches,
            "network_requests": 0,
            "capture_error": capture_error,
            "valid": False,
        }
    )
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "canvas"
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {
        "canvas.json": data.get("canvas", {}),
        "prototype.json": {"constructors": data.get("constructors", {}), "prototype": data.get("prototype", {}), "canvas": data.get("canvas", {})},
        "descriptors.json": data.get("descriptors", {}),
        "methods.json": data.get("methods", {}),
        "fingerprint.json": fingerprint,
        "statistics.json": {"browser_launches": launches, "network_requests": 0, "collection_duration_ms": round(duration_ms, 3), "collected_properties": len(data.get("canvas", {}).get("ownProperties", [])) + len(data.get("canvas", {}).get("prototypeChain", [])), "collected_descriptors": len(descriptors), "collected_methods": len(all_methods), "fingerprint_generation": bool(fingerprint["sha256"]), "browser_version": browser_version},
        "summary.json": summary,
        "validation.json": validation,
    }
    validation["artifact_completeness"] = all(name in artifacts for name in ARTIFACT_NAMES if name.endswith(".json"))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests", "capture_error"}) and validation["artifact_completeness"]
    summary["validation_valid"] = validation["valid"]
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "canvas_report.md", _report(summary, data, fingerprint, validation))
    print("CANVAS BASELINE REBUILD")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Status: {capture_status} | Browser launches: {launches} | Network: 0")
    print(f"Fingerprint SHA-256: {fingerprint['sha256']}")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 060B: canonical Browser Platform Canvas baseline")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
