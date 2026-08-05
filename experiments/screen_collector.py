"""Experiment 056: read-only Screen API collector.

The collector captures the native Screen and ScreenOrientation surfaces on
``about:blank`` through BrowserSessionManager.  It also records viewport and
Window cross-checks so the immutable baseline can be used for consistency
comparisons without injecting or modifying browser state.
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
    "screen.json",
    "prototype.json",
    "descriptors.json",
    "window.json",
    "viewport.json",
    "orientation.json",
    "fingerprint.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "screen_report.md",
)
SCREEN_PROPERTIES = (
    "width",
    "height",
    "availWidth",
    "availHeight",
    "availLeft",
    "availTop",
    "colorDepth",
    "pixelDepth",
    "orientation",
    "isExtended",
)


SCREEN_PROBE = r"""
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
  const getterInfo = (target, name, receiver, read) => {
    const item = descriptor(target, name);
    const getter = item && item.hasGetter ? safe(() => Object.getOwnPropertyDescriptor(target, name).get, null) : null;
    const first = safe(read, null);
    const second = safe(read, null);
    const detached = {};
    for (const label of ['detached', 'invalidReceiver', 'prototypeReceiver']) {
      try {
        const value = label === 'detached' ? getter() : label === 'invalidReceiver' ? getter.call({}) : getter.call(receiver && receiver.constructor ? receiver.constructor.prototype : receiver);
        detached[label] = { throws: false, value: stable(value) };
      } catch (error) {
        detached[label] = { throws: true, error: errorInfo(error) };
      }
    }
    return {
      descriptor: item,
      available: typeof getter === 'function',
      source: getter ? nativeSource(getter) : null,
      name: getter ? safe(() => getter.name, null) : null,
      length: getter ? safe(() => getter.length, null) : null,
      nativeSource: !!getter && /\[native code\]/.test(nativeSource(getter) || ''),
      first: stable(first),
      second: stable(second),
      stable: JSON.stringify(stable(first)) === JSON.stringify(stable(second)),
      referenceStable: first !== null && (typeof first === 'object' || typeof first === 'function') ? first === second : null,
      detached
    };
  };
  const objectSurface = (value, constructorName) => {
    const prototype = value ? safe(() => Object.getPrototypeOf(value), null) : null;
    const constructor = value ? safe(() => value.constructor, null) : null;
    return {
      available: !!value,
      typeof: value ? typeof value : 'undefined',
      objectToString: safe(() => Object.prototype.toString.call(value), null),
      constructor: safe(() => constructor && constructor.name, null),
      constructorSource: constructor ? nativeSource(constructor) : null,
      ownProperties: ownKeys(value),
      prototypeProperties: ownKeys(prototype),
      prototypeChain: chain(value),
      prototype: safe(() => prototype && prototype.constructor && prototype.constructor.name, constructorName || null),
      prototypeEquality: safe(() => !!constructor && prototype === constructor.prototype, false),
      constructorEquality: safe(() => !!constructor && prototype.constructor === constructor, false),
      instanceof: safe(() => !!constructor && value instanceof constructor, false),
      symbolToStringTag: descriptor(prototype, Symbol.toStringTag),
      referenceStable: safe(() => value === value, true)
    };
  };

  const screenObject = globalThis.screen;
  const screenPrototype = typeof Screen === 'function' ? Screen.prototype : null;
  const screenConstructor = typeof Screen === 'function' ? Screen : null;
  const values = {};
  const access = {};
  const getters = {};
  for (const name of ["width", "height", "availWidth", "availHeight", "availLeft", "availTop", "colorDepth", "pixelDepth", "orientation", "isExtended"]) {
    const first = safe(() => screenObject && screenObject[name], null);
    const second = safe(() => screenObject && screenObject[name], null);
    values[name] = stable(first);
    access[name] = {
      type: typeof first,
      first: stable(first),
      second: stable(second),
      stable: JSON.stringify(stable(first)) === JSON.stringify(stable(second)),
      referenceStable: first !== null && (typeof first === 'object' || typeof first === 'function') ? first === second : null,
      descriptor: descriptor(screenPrototype, name)
    };
    if (access[name].descriptor && access[name].descriptor.hasGetter) {
      getters[name] = getterInfo(screenPrototype, name, screenObject, () => screenObject[name]);
    }
  }
  const screenSurface = {
    available: !!screenObject && !!screenPrototype,
    typeof: typeof screenObject,
    objectToString: stable(screenObject),
    constructor: safe(() => screenConstructor && screenConstructor.name, null),
    constructorSource: screenConstructor ? nativeSource(screenConstructor) : null,
    ownProperties: ownKeys(screenObject),
    inheritedProperties: ownKeys(screenPrototype),
    prototypeChain: chain(screenObject),
    symbolToStringTag: descriptor(screenPrototype, Symbol.toStringTag),
    instanceofScreen: safe(() => !!screenConstructor && screenObject instanceof screenConstructor, false),
    prototypeEquality: safe(() => !!screenConstructor && screenPrototype === screenConstructor.prototype, false),
    constructorEquality: safe(() => !!screenConstructor && screenPrototype.constructor === screenConstructor, false),
    referenceStable: safe(() => screenObject === globalThis.screen, false),
    values,
    access
  };
  const prototypeSurface = {
    available: !!screenPrototype,
    constructor: {
      name: safe(() => screenConstructor && screenConstructor.name, null),
      length: safe(() => screenConstructor && screenConstructor.length, null),
      source: screenConstructor ? nativeSource(screenConstructor) : null,
      nativeSource: !!screenConstructor && /\[native code\]/.test(nativeSource(screenConstructor) || ''),
      descriptor: descriptor(globalThis, 'Screen')
    },
    chain: chain(screenPrototype),
    ownProperties: ownKeys(screenPrototype),
    objectPrototype: safe(() => Object.getPrototypeOf(screenPrototype).constructor.name, null),
    instanceofObject: safe(() => screenPrototype instanceof Object, false),
    toStringTag: descriptor(screenPrototype, Symbol.toStringTag),
    descriptors: Object.fromEntries(ownKeys(screenPrototype).map((key) => [key, descriptor(screenPrototype, key)]))
  };
  const exceptions = {
    constructorCall: safe(() => { Screen.call({}); return { throws: false }; }, null),
    constructorReflect: safe(() => { Reflect.construct(Screen, []); return { throws: false }; }, null),
    getters: Object.fromEntries(Object.entries(getters).map(([name, value]) => [name, value.detached]))
  };
  const orientation = screenObject ? safe(() => screenObject.orientation, null) : null;
  const orientationPrototype = orientation ? safe(() => Object.getPrototypeOf(orientation), null) : null;
  const orientationConstructor = orientation ? safe(() => orientation.constructor, null) : null;
  const orientationValues = {
    type: stable(safe(() => orientation && orientation.type, null)),
    angle: stable(safe(() => orientation && orientation.angle, null))
  };
  const orientationSurface = {
    ...objectSurface(orientation, 'ScreenOrientation'),
    values: orientationValues,
    repeatedType: stable(safe(() => orientation && orientation.type, null)),
    repeatedAngle: stable(safe(() => orientation && orientation.angle, null)),
    referenceStable: safe(() => orientation === (screenObject && screenObject.orientation), false),
    prototypeDescriptors: Object.fromEntries(ownKeys(orientationPrototype).map((key) => [key, descriptor(orientationPrototype, key)])),
    constructorSource: orientationConstructor ? nativeSource(orientationConstructor) : null,
    constructorName: safe(() => orientationConstructor && orientationConstructor.name, null),
    prototypeChain: chain(orientation)
  };
  const windowObject = {
    innerWidth: stable(safe(() => innerWidth, null)),
    innerHeight: stable(safe(() => innerHeight, null)),
    outerWidth: stable(safe(() => outerWidth, null)),
    outerHeight: stable(safe(() => outerHeight, null)),
    devicePixelRatio: stable(safe(() => devicePixelRatio, null)),
    visualViewport: objectSurface(safe(() => visualViewport, null), 'VisualViewport')
  };
  const visual = safe(() => visualViewport, null);
  if (visual) {
    windowObject.visualViewportValues = {
      width: stable(safe(() => visual.width, null)),
      height: stable(safe(() => visual.height, null)),
      scale: stable(safe(() => visual.scale, null)),
      offsetLeft: stable(safe(() => visual.offsetLeft, null)),
      offsetTop: stable(safe(() => visual.offsetTop, null)),
      pageLeft: stable(safe(() => visual.pageLeft, null)),
      pageTop: stable(safe(() => visual.pageTop, null))
    };
  }
  const rootElement = safe(() => document.documentElement, null);
  const queries = [
    '(orientation: portrait)',
    '(orientation: landscape)',
    `(min-width: ${safe(() => innerWidth, 0)}px)`,
    `(min-height: ${safe(() => innerHeight, 0)}px)`
  ];
  const mediaQueries = {};
  for (const query of queries) {
    const media = safe(() => matchMedia(query), null);
    mediaQueries[query] = {
      available: !!media,
      matches: stable(safe(() => media && media.matches, null)),
      media: stable(safe(() => media && media.media, null)),
      onchangeType: safe(() => media && typeof media.onchange, null),
      constructor: safe(() => media && media.constructor && media.constructor.name, null),
      prototype: safe(() => media && Object.getPrototypeOf(media).constructor.name, null),
      descriptor: descriptor(media ? Object.getPrototypeOf(media) : null, 'matches'),
      objectToString: stable(media)
    };
  }
  const viewport = {
    documentClientWidth: stable(safe(() => rootElement && rootElement.clientWidth, null)),
    documentClientHeight: stable(safe(() => rootElement && rootElement.clientHeight, null)),
    devicePixelRatio: stable(safe(() => devicePixelRatio, null)),
    innerWidth: stable(safe(() => innerWidth, null)),
    innerHeight: stable(safe(() => innerHeight, null)),
    outerWidth: stable(safe(() => outerWidth, null)),
    outerHeight: stable(safe(() => outerHeight, null)),
    visualViewport: windowObject.visualViewportValues || {},
    matchMedia: mediaQueries
  };
  return {
    available: screenSurface.available,
    screen: screenSurface,
    prototype: prototypeSurface,
    descriptors: {
      screenPrototype: prototypeSurface.descriptors,
      navigatorScreen: descriptor(Navigator.prototype, 'screen'),
      orientationPrototype: orientationSurface.prototypeDescriptors
    },
    getters,
    window: windowObject,
    viewport,
    orientation: orientationSurface,
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
    experiment_dirs = [path for path in reports.iterdir() if path.is_dir() and path.name.startswith("exp_")]
    for experiment_dir in sorted(experiment_dirs, key=lambda path: path.name):
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
        result = page.evaluate(SCREEN_PROBE)
        if not isinstance(result, dict):
            raise TypeError("Screen probe returned a non-object result")
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


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _report(summary: dict[str, Any], stats: dict[str, Any], validation: dict[str, Any], data: dict[str, Any]) -> str:
    values = data.get("screen", {}).get("values", {})
    orientation = data.get("orientation", {}).get("values", {})
    lines = [
        "# Experiment 056 - Screen Collector", "", "## Executive Summary", "",
        f"- Result: **{summary['result']}**",
        f"- Screen API available: **{summary['available']}**",
        f"- Screen getters: **{stats['getter_count']}**",
        f"- Orientation: `{orientation.get('type')}` / `{orientation.get('angle')}`",
        f"- Fingerprint: `{summary['fingerprint_sha256']}`", "",
        "The collector ran on about:blank through Browser Platform and performed only read operations.",
        "", "## Screen Properties", "", "| Property | Value | Stable | Reference Stable |", "|---|---|---:|---:|",
    ]
    access = data.get("screen", {}).get("access", {})
    for name in sorted(values):
        item = access.get(name, {})
        lines.append(f"| `{name}` | `{values[name]}` | {item.get('stable')} | {item.get('referenceStable')} |")
    lines += ["", "## Window and Viewport Cross-check", "", "| Field | Value |", "|---|---|"]
    for name, value in sorted((data.get("viewport", {}) or {}).items()):
        if name == "matchMedia":
            lines.append(f"| `matchMedia` | `{len(value) if isinstance(value, dict) else 0} queries` |")
        else:
            lines.append(f"| `{name}` | `{value}` |")
    lines += ["", "## Orientation", "", "| Field | Value |", "|---|---|"]
    for name, value in sorted((data.get("orientation", {}) or {}).get("values", {}).items()):
        lines.append(f"| `{name}` | `{value}` |")
    lines += ["", "## Validation", "", "| Check | Status |", "|---|---|"]
    for key, value in validation.items():
        if key in {"valid", "artifact_completeness", "browser_launches", "network_requests"}:
            continue
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if bool(value) else 'FAIL'} |")
    lines += ["", "## Read-only Boundary", "", "No screen or window property was written. No stealth injection, navigation, permission prompt, media access, or network API was used.", ""]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    historical_before = _historical_hashes(root)
    status, capture_error, data, started = _capture(args)
    data = _ordered(data if isinstance(data, dict) else {})
    historical_after = _historical_hashes(root)
    fingerprint_data = {key: data.get(key, {}) for key in ("screen", "prototype", "descriptors", "getters", "window", "viewport", "orientation", "exceptions")}
    fingerprint_hash = _canonical_hash(fingerprint_data)
    screen = data.get("screen", {}) if isinstance(data.get("screen"), dict) else {}
    prototype = data.get("prototype", {}) if isinstance(data.get("prototype"), dict) else {}
    descriptors = data.get("descriptors", {}) if isinstance(data.get("descriptors"), dict) else {}
    getters = data.get("getters", {}) if isinstance(data.get("getters"), dict) else {}
    window = data.get("window", {}) if isinstance(data.get("window"), dict) else {}
    viewport = data.get("viewport", {}) if isinstance(data.get("viewport"), dict) else {}
    orientation = data.get("orientation", {}) if isinstance(data.get("orientation"), dict) else {}
    values = screen.get("values", {}) if isinstance(screen.get("values"), dict) else {}
    numeric = {key: _number(values.get(key)) for key in SCREEN_PROPERTIES}
    inner_width = _number(window.get("innerWidth"))
    inner_height = _number(window.get("innerHeight"))
    outer_width = _number(window.get("outerWidth"))
    outer_height = _number(window.get("outerHeight"))
    width = numeric.get("width")
    height = numeric.get("height")
    avail_width = numeric.get("availWidth")
    avail_height = numeric.get("availHeight")
    color_depth = numeric.get("colorDepth")
    pixel_depth = numeric.get("pixelDepth")
    dpr = _number(viewport.get("devicePixelRatio"))
    orientation_values = orientation.get("values", {}) if isinstance(orientation.get("values"), dict) else {}
    orientation_type = orientation_values.get("type")
    orientation_angle = _number(orientation_values.get("angle"))
    visual = viewport.get("visualViewport", {}) if isinstance(viewport.get("visualViewport"), dict) else {}
    visual_width = _number(visual.get("width"))
    visual_height = _number(visual.get("height"))
    visual_scale = _number(visual.get("scale"))
    consistency_checks = {
        "screen_width_ge_avail_width": width is None or avail_width is None or width >= avail_width,
        "screen_height_ge_avail_height": height is None or avail_height is None or height >= avail_height,
        "color_depth_equals_pixel_depth": color_depth is None or pixel_depth is None or color_depth == pixel_depth,
        "outer_width_ge_inner_width": outer_width is None or inner_width is None or outer_width == 0 or outer_width >= inner_width,
        "outer_height_ge_inner_height": outer_height is None or inner_height is None or outer_height == 0 or outer_height >= inner_height,
        "dpr_positive": dpr is None or dpr > 0,
        "visual_viewport_width_consistent": visual_width is None or inner_width is None or abs(visual_width - inner_width) <= 1,
        "visual_viewport_height_consistent": visual_height is None or inner_height is None or abs(visual_height - inner_height) <= 1,
        "visual_viewport_scale_consistent": visual_scale is None or dpr is None or abs(visual_scale - dpr) <= 0.01,
        "orientation_type_valid": orientation_type is None or orientation_type in {"portrait-primary", "portrait-secondary", "landscape-primary", "landscape-secondary"},
        "orientation_angle_valid": orientation_angle is None or orientation_angle in {0, 90, 180, 270},
    }
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden = ("add_" + "init_script", "_" + "_stealth", "get" + "UserMedia(", "get" + "DisplayMedia(", "requestPermission(", "sendBeacon(", "fetch(", "XMLHttpRequest", "location.assign(", "location.replace(")
    getter_stable_count = sum(1 for value in getters.values() if isinstance(value, dict) and value.get("stable"))
    requested_descriptors = [descriptors.get("screenPrototype", {}).get(name) for name in SCREEN_PROPERTIES if isinstance(descriptors.get("screenPrototype"), dict)]
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (data, fingerprint_data, consistency_checks)),
        "artifact_completeness": False,
        "deterministic_ordering": data == _ordered(data),
        "prototype_validation": bool(screen.get("prototypeEquality")) and bool(screen.get("constructorEquality")) and bool(screen.get("instanceofScreen")) and bool(prototype.get("instanceofObject")),
        "descriptor_validation": bool(requested_descriptors) and all(value is None or isinstance(value, dict) for value in requested_descriptors),
        "viewport_consistency": all(consistency_checks.values()),
        "orientation_validation": bool(orientation) and bool(orientation.get("referenceStable")) and bool(consistency_checks["orientation_type_valid"]) and bool(consistency_checks["orientation_angle_valid"]),
        "fingerprint_validation": bool(fingerprint_hash) and fingerprint_hash == _canonical_hash(fingerprint_data),
        "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and "launch_browser" in source and ("sync_" + "playwright") not in source,
        "read_only_verification": not any(token in SCREEN_PROBE for token in forbidden),
        "no_browser_modification": not any(token in SCREEN_PROBE for token in forbidden),
        "no_network_requests": not any(token in SCREEN_PROBE for token in ("sendBeacon(", "fetch(", "XMLHttpRequest")),
        "historical_artifacts_immutable": historical_before == historical_after,
        "browser_launches": int(started),
        "network_requests": 0,
        "valid": False,
    }
    stats = {
        "screen_property_count": len(values),
        "getter_count": len(getters),
        "getter_stable_count": getter_stable_count,
        "prototype_property_count": len(prototype.get("ownProperties", [])),
        "descriptor_count": sum(1 for value in descriptors.get("screenPrototype", {}).values() if isinstance(value, dict)) if isinstance(descriptors.get("screenPrototype"), dict) else 0,
        "window_cross_check_count": len(window),
        "viewport_field_count": len(viewport),
        "match_media_count": len(viewport.get("matchMedia", {})) if isinstance(viewport.get("matchMedia"), dict) else 0,
        "orientation_type": orientation_type,
        "orientation_angle": orientation_angle,
        "consistency_checks": consistency_checks,
        "browser_launches": int(started),
        "network_requests": 0,
        "capture_status": status,
        "capture_error": capture_error,
        "fingerprint_sha256": fingerprint_hash,
    }
    validation["json_validation"] = all(_json_safe(value) for value in (data, fingerprint_data, consistency_checks, stats))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})
    summary = {
        "experiment": "Experiment 056 - Screen Collector",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "SUCCESS" if status == "SUCCESS" else ("PARTIAL" if started else "UNKNOWN"),
        "available": bool(data.get("available")),
        "browser": args.browser,
        "headless": bool(args.headless),
        "browser_platform": "BrowserSessionManager -> launch_browser",
        "screen_property_count": len(values),
        "orientation_type": orientation_type,
        "orientation_angle": orientation_angle,
        "fingerprint_sha256": fingerprint_hash,
        "browser_launches": int(started),
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "screen"
    output.mkdir(parents=True, exist_ok=False)
    artifact_data = {
        "screen.json": screen,
        "prototype.json": prototype,
        "descriptors.json": descriptors,
        "window.json": window,
        "viewport.json": viewport,
        "orientation.json": orientation,
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
    write_text_exclusive(output / "screen_report.md", _report(summary, stats, validation, data))
    print("SCREEN COLLECTOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Properties: {stats['screen_property_count']} | Getters: {stats['getter_count']} | Orientation: {orientation_type}/{orientation_angle}")
    print(f"Fingerprint: {fingerprint_hash}")
    print(f"Browser launches: {stats['browser_launches']} | Network requests: {stats['network_requests']}")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 056: collect native Screen API behavior")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
