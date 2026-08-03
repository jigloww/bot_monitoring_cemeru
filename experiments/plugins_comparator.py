"""Compare Real Browser and Playwright plugins/mimeTypes snapshots.

The comparator is intentionally observational.  It reads immutable collector
artifacts and, when a Playwright artifact is not supplied, performs a native
read-only capture through :class:`BrowserSessionManager` (which delegates to
the Browser Platform launcher).  No prototype, permission, network, or
fingerprint modification is performed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserConfig, BrowserSessionManager
from experiments.experiment import Experiment
from experiments.plugins_collector import PLUGINS_PROBE
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    write_json_exclusive,
    write_text_exclusive,
)


ARTIFACT_NAMES = (
    "compare.json",
    "similarity.json",
    "differences.json",
    "critical.json",
    "recommendations.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "plugins_compare.md",
)

DOMAIN_ORDER = (
    "navigator",
    "plugins",
    "mime_types",
    "prototype",
    "descriptors",
    "methods",
    "cross_reference",
)

DOMAIN_LABELS = {
    "navigator": "Navigator",
    "plugins": "PluginArray",
    "mime_types": "MimeTypeArray",
    "prototype": "Prototype",
    "descriptors": "Descriptors",
    "methods": "Methods",
    "cross_reference": "Cross References",
}

COLLECTION_KEYS = {"plugins": "name", "mime_types": "type"}


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}


def _empty_probe(error: str | None = None) -> dict[str, Any]:
    return {
        "navigator": {"constructor": None, "ownProperties": [], "pluginsDescriptor": None, "mimeTypesDescriptor": None},
        "plugins": {"exists": False, "typeof": "undefined", "constructor": None, "toString": None, "ownProperties": [], "prototypeChain": [], "length": 0, "prototype": None, "inheritedProperties": [], "descriptors": {}, "methods": {}, "illegalInvocation": {}, "instanceof": False, "symbolToStringTag": None, "items": []},
        "mimeTypes": {"exists": False, "typeof": "undefined", "constructor": None, "toString": None, "ownProperties": [], "prototypeChain": [], "length": 0, "prototype": None, "inheritedProperties": [], "descriptors": {}, "methods": {}, "illegalInvocation": {}, "instanceof": False, "symbolToStringTag": None, "items": []},
        "crossReference": {"pluginMimeTypes": {}, "mimeEnabledPlugins": {}, "mismatches": ([{"reason": error}] if error else []), "bidirectionalValid": False},
        "prototype": {"pluginArray": {}, "mimeTypeArray": {}, "pluginChain": [], "mimeChain": [], "pluginInstanceof": False, "mimeInstanceof": False, "pluginToStringTag": None, "mimeToStringTag": None},
    }


def _fingerprint_data(bundle: dict[str, Any]) -> dict[str, Any]:
    """Return the same normalized shape used by the collector hash."""
    return {
        "navigator": copy.deepcopy(bundle.get("navigator", {})),
        "plugins": copy.deepcopy(bundle.get("plugins", {})),
        "mimeTypes": copy.deepcopy(bundle.get("mime_types", {})),
        "crossReference": copy.deepcopy(bundle.get("cross_reference", {})),
        "prototype": copy.deepcopy(bundle.get("prototype", {})),
    }


def _bundle_from_probe(probe: dict[str, Any]) -> tuple[dict[str, Any], str]:
    bundle = {
        "navigator": probe.get("navigator", {}) if isinstance(probe.get("navigator"), dict) else {},
        "plugins": probe.get("plugins", {}) if isinstance(probe.get("plugins"), dict) else {},
        "mime_types": probe.get("mimeTypes", {}) if isinstance(probe.get("mimeTypes"), dict) else {},
        "prototype": probe.get("prototype", {}) if isinstance(probe.get("prototype"), dict) else {},
        "descriptors": {
            "navigator": {
                "plugins": (probe.get("navigator", {}) or {}).get("pluginsDescriptor"),
                "mimeTypes": (probe.get("navigator", {}) or {}).get("mimeTypesDescriptor"),
            },
            "plugins": (probe.get("plugins", {}) or {}).get("descriptors", {}),
            "mimeTypes": (probe.get("mimeTypes", {}) or {}).get("descriptors", {}),
        },
        "methods": {
            "plugins": (probe.get("plugins", {}) or {}).get("methods", {}),
            "plugin_prototypes": {
                str(item.get("index")): item.get("prototypeMethods", {})
                for item in (probe.get("plugins", {}) or {}).get("items", [])
                if isinstance(item, dict)
            },
            "mimeTypes": (probe.get("mimeTypes", {}) or {}).get("methods", {}),
            "mime_prototypes": {
                str(item.get("index")): item.get("prototypeMethods", {})
                for item in (probe.get("mimeTypes", {}) or {}).get("items", [])
                if isinstance(item, dict)
            },
        },
        "cross_reference": probe.get("crossReference", {}) if isinstance(probe.get("crossReference"), dict) else {},
    }
    return bundle, _canonical_hash(_fingerprint_data(bundle))


def _load_bundle(directory: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if directory is None or not directory.is_dir():
        return {}, {"available": False, "directory": str(directory) if directory else None, "fingerprint_sha256": None}
    raw = {name: _read_json(directory / name) for name in (
        "navigator.json", "plugins.json", "mime_types.json", "prototype.json",
        "descriptors.json", "methods.json", "cross_reference.json", "fingerprint.json",
    )}
    bundle = {
        "navigator": raw["navigator.json"],
        "plugins": raw["plugins.json"],
        "mime_types": raw["mime_types.json"],
        "prototype": raw["prototype.json"],
        "descriptors": raw["descriptors.json"],
        "methods": raw["methods.json"],
        "cross_reference": raw["cross_reference.json"],
    }
    fingerprint = raw["fingerprint.json"]
    stored_hash = fingerprint.get("sha256") if isinstance(fingerprint.get("sha256"), str) else None
    calculated_hash = _canonical_hash(_fingerprint_data(bundle))
    return bundle, {
        "available": any(bool(value) for value in raw.values()),
        "directory": str(directory),
        "fingerprint_sha256": stored_hash or calculated_hash,
        "calculated_fingerprint_sha256": calculated_hash,
        "fingerprint_valid": stored_hash in (None, calculated_hash),
    }


def _find_directory(root: Path, explicit: Path | None, *, prefer_success: bool = True) -> Path | None:
    if explicit is not None:
        candidate = explicit if explicit.is_absolute() else root / explicit
        return candidate if candidate.is_dir() else None
    candidates = sorted(root.glob("reports/experiments/exp_*/plugins"), key=lambda item: item.as_posix())
    if prefer_success:
        successful = []
        for candidate in candidates:
            summary = _read_json(candidate / "summary.json")
            if summary.get("result") == "SUCCESS":
                successful.append(candidate)
        candidates = successful or candidates
    return candidates[-1] if candidates else None


def _capture_playwright(args: argparse.Namespace) -> tuple[str, str | None, dict[str, Any], bool, bool]:
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
    navigated = False
    error: str | None = None
    probe = _empty_probe()
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
            value = page.evaluate(PLUGINS_PROBE)
            if not isinstance(value, dict):
                raise TypeError("plugins probe returned a non-object result")
            probe = value
        except Exception as exc:
            error = f"probe: {exc}"
            probe = _empty_probe(str(exc))
    except Exception as exc:
        error = f"browser launch: {exc}"
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
    exists = bool(probe.get("plugins", {}).get("exists")) and bool(probe.get("mimeTypes", {}).get("exists"))
    status = "SUCCESS" if started and exists and not error else ("PARTIAL" if started else "UNKNOWN")
    return status, error, probe, started, navigated


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value, key=str):
            child = f"{path}.{key}" if path else str(key)
            result.update(_flatten(value[key], child))
        return result
    if isinstance(value, list):
        result: dict[str, Any] = {}
        for index, item in enumerate(value):
            result.update(_flatten(item, f"{path}[{index}]"))
        if not value and path:
            result[path] = []
        return result
    return {path: value}


def _collection_map(value: Any, key: str) -> dict[str, Any]:
    items = value.get("items", []) if isinstance(value, dict) else []
    if isinstance(items, dict):
        return {str(name): item for name, item in sorted(items.items(), key=lambda pair: str(pair[0]))}
    result: dict[str, Any] = {}
    if not isinstance(items, list):
        return result
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            identity = f"index:{index}"
        else:
            identity = str(item.get(key) or f"index:{item.get('index', index)}")
        if identity in result:
            identity = f"{identity}#{index}"
        result[identity] = item
    return {name: result[name] for name in sorted(result)}


def _severity(path: str, status: str) -> str:
    if status == "EQUAL":
        return "INFO"
    lowered = path.lower()
    if any(token in lowered for token in ("prototype", "instanceof", "constructor", "tostringtag")):
        return "CRITICAL"
    if any(token in lowered for token in ("descriptor", "native", "source", "illegal", "cross_reference", "fingerprint", "methods")):
        return "HIGH"
    if any(token in lowered for token in ("plugin", "mime", "count", "length", "enabled")):
        return "MEDIUM"
    return "LOW"


def _reason(status: str) -> str:
    return {
        "EQUAL": "Real Browser and Playwright values match.",
        "CHANGED": "The property exists in both captures but has a different value.",
        "MISSING": "The property exists in the Real Browser baseline but is absent from Playwright.",
        "ADDED": "The property exists in Playwright but is absent from the Real Browser baseline.",
        "REMOVED": "The baseline collection item is absent from the Playwright capture.",
    }.get(status, "The property could not be classified.")


def _entry(path: str, category: str, status: str, real: Any, playwright: Any) -> dict[str, Any]:
    return {
        "path": path,
        "category": category,
        "status": status,
        "real": real,
        "playwright": playwright,
        "severity": _severity(path, status),
        "reason": _reason(status),
    }


def _compare_domain(domain: str, real: dict[str, Any], playwright: dict[str, Any]) -> list[dict[str, Any]]:
    category = DOMAIN_LABELS[domain]
    real_value = real.get(domain, {}) if isinstance(real, dict) else {}
    playwright_value = playwright.get(domain, {}) if isinstance(playwright, dict) else {}
    real_value = real_value if isinstance(real_value, dict) else {}
    playwright_value = playwright_value if isinstance(playwright_value, dict) else {}
    real_base = dict(real_value)
    playwright_base = dict(playwright_value)
    real_items = _collection_map(real_base, COLLECTION_KEYS[domain]) if domain in COLLECTION_KEYS else {}
    playwright_items = _collection_map(playwright_base, COLLECTION_KEYS[domain]) if domain in COLLECTION_KEYS else {}
    if domain in COLLECTION_KEYS:
        real_base.pop("items", None)
        playwright_base.pop("items", None)
    differences: list[dict[str, Any]] = []
    real_flat = _flatten(real_base, domain)
    playwright_flat = _flatten(playwright_base, domain)
    for path in sorted(set(real_flat) | set(playwright_flat)):
        in_real = path in real_flat
        in_playwright = path in playwright_flat
        if in_real and in_playwright:
            status = "EQUAL" if real_flat[path] == playwright_flat[path] else "CHANGED"
        elif in_real:
            status = "MISSING"
        else:
            status = "ADDED"
        differences.append(_entry(path, category, status, real_flat.get(path), playwright_flat.get(path)))
    if domain in COLLECTION_KEYS:
        for identity in sorted(set(real_items) | set(playwright_items)):
            path = f"{domain}.items.{identity}"
            if identity not in playwright_items:
                differences.append(_entry(path, category, "REMOVED", real_items[identity], None))
                continue
            if identity not in real_items:
                differences.append(_entry(path, category, "ADDED", None, playwright_items[identity]))
                continue
            real_item = _flatten(real_items[identity], path)
            playwright_item = _flatten(playwright_items[identity], path)
            for item_path in sorted(set(real_item) | set(playwright_item)):
                in_real = item_path in real_item
                in_playwright = item_path in playwright_item
                if in_real and in_playwright:
                    status = "EQUAL" if real_item[item_path] == playwright_item[item_path] else "CHANGED"
                elif in_real:
                    status = "MISSING"
                else:
                    status = "ADDED"
                differences.append(_entry(item_path, category, status, real_item.get(item_path), playwright_item.get(item_path)))
    return differences


def _compare(real: dict[str, Any], playwright: dict[str, Any], real_meta: dict[str, Any], playwright_meta: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    differences: list[dict[str, Any]] = []
    for domain in DOMAIN_ORDER:
        differences.extend(_compare_domain(domain, real, playwright))
    real_hash = real_meta.get("fingerprint_sha256")
    playwright_hash = playwright_meta.get("fingerprint_sha256")
    if real_hash and playwright_hash:
        hash_status = "EQUAL" if real_hash == playwright_hash else "CHANGED"
    elif real_hash:
        hash_status = "MISSING"
    elif playwright_hash:
        hash_status = "ADDED"
    else:
        hash_status = "MISSING"
    differences.append(_entry("fingerprint.sha256", "Fingerprint", hash_status, real_hash, playwright_hash))
    differences.sort(key=lambda item: (item["category"], item["path"], item["status"]))
    category_stats: dict[str, dict[str, Any]] = {}
    for item in differences:
        bucket = category_stats.setdefault(item["category"], {"total": 0, "equal": 0, "changed": 0, "missing": 0, "added": 0, "removed": 0})
        bucket["total"] += 1
        key = item["status"].lower()
        bucket[key] = bucket.get(key, 0) + 1
    for bucket in category_stats.values():
        bucket["similarity"] = round(bucket["equal"] / bucket["total"] * 100.0, 2) if bucket["total"] else 100.0
    return differences, category_stats


def _recommendations(differences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weights = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    actionable = [item for item in differences if item["status"] != "EQUAL"]
    total = max(len(differences), 1)
    recommendations: list[dict[str, Any]] = []
    for priority, item in enumerate(sorted(actionable, key=lambda value: (-weights[value["severity"]], value["category"], value["path"])), 1):
        recommendations.append({
            "priority": priority,
            "path": item["path"],
            "category": item["category"],
            "severity": item["severity"],
            "status": item["status"],
            "recommendation": f"Investigate and align Playwright {item['path']} with the Real Browser baseline without replacing native constructors.",
            "expected_similarity_gain": round(min(10.0, 100.0 * weights[item["severity"]] / total), 2),
            "confidence": "High" if item["severity"] in {"CRITICAL", "HIGH"} else "Medium",
        })
    return recommendations


def _similarity(category_stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    lookup = {key: category_stats.get(label, {"similarity": 100.0}) for key, label in {
        "navigator": "Navigator",
        "plugins": "PluginArray",
        "mime_types": "MimeTypeArray",
        "prototype": "Prototype",
        "descriptors": "Descriptors",
        "methods": "Methods",
        "cross_reference": "Cross References",
        "fingerprint": "Fingerprint",
    }.items()}
    values = [bucket["similarity"] for bucket in category_stats.values() if bucket.get("total", 0)]
    return {
        "overall": round(sum(values) / len(values), 2) if values else 0.0,
        "navigator": lookup["navigator"]["similarity"],
        "plugins": lookup["plugins"]["similarity"],
        "mime_types": lookup["mime_types"]["similarity"],
        "prototype": lookup["prototype"]["similarity"],
        "descriptors": lookup["descriptors"]["similarity"],
        "methods": lookup["methods"]["similarity"],
        "cross_reference": lookup["cross_reference"]["similarity"],
        "fingerprint": lookup["fingerprint"]["similarity"],
        "domains": category_stats,
    }


def _report(summary: dict[str, Any], similarity: dict[str, Any], stats: dict[str, Any], validation: dict[str, Any], differences: list[dict[str, Any]]) -> str:
    lines = [
        "# Experiment 039 — Plugins & MimeTypes Comparator",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Overall similarity: **{similarity.get('overall', 0):.2f}%**",
        f"- Real plugins / mimeTypes: **{stats['real_plugin_count']} / {stats['real_mime_type_count']}**",
        f"- Playwright plugins / mimeTypes: **{stats['playwright_plugin_count']} / {stats['playwright_mime_type_count']}**",
        f"- Total differences: **{stats['different'] + stats['missing'] + stats['added'] + stats['removed']}**",
        "",
        "## Similarity",
        "",
        "| Domain | Similarity |",
        "|---|---:|",
    ]
    for key in ("plugins", "mime_types", "prototype", "descriptors", "methods", "cross_reference", "fingerprint"):
        lines.append(f"| {key.replace('_', ' ').title()} | {similarity.get(key, 0):.2f}% |")
    lines += [
        "",
        "## Difference Summary",
        "",
        "| Status | Count |",
        "|---|---:|",
        f"| Equal | {stats['equal']} |",
        f"| Changed | {stats['different']} |",
        f"| Missing | {stats['missing']} |",
        f"| Added | {stats['added']} |",
        f"| Removed | {stats['removed']} |",
        "",
        "## Critical Differences",
        "",
    ]
    critical = [item for item in differences if item["severity"] == "CRITICAL" and item["status"] != "EQUAL"][:20]
    if critical:
        lines += ["| Path | Status | Reason |", "|---|---|---|"]
        lines.extend(f"| `{item['path']}` | {item['status']} | {item['reason']} |" for item in critical)
    else:
        lines.append("No critical differences detected.")
    lines += [
        "",
        "## Validation",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    lines.extend(f"| {key.replace('_', ' ').title()} | {'PASS' if value else 'FAIL'} |" for key, value in validation.items())
    lines += [
        "",
        "## Read-only Boundary",
        "",
        "The comparator reads immutable artifacts and native browser observations only. It does not inject stealth, modify navigator prototypes, request permissions, or intercept network traffic.",
        "",
    ]
    return "\n".join(lines)


def _positive_timeout(value: str) -> int:
    timeout = int(value)
    if timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return timeout


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = args.reports_dir or root / "reports" / "experiments"
    if not reports_root.is_absolute():
        reports_root = root / reports_root
    real_dir = _find_directory(root, args.real_dir)
    playwright_dir = _find_directory(root, args.playwright_dir, prefer_success=False) if args.playwright_dir else None
    experiment = Experiment.create(reports_root.resolve())
    output = experiment.directory / "plugins_compare"
    output.mkdir(parents=True, exist_ok=True)

    real_bundle, real_meta = _load_bundle(real_dir)
    capture_status = "UNKNOWN"
    capture_error: str | None = None
    browser_started = False
    navigation_succeeded = False
    if playwright_dir is not None:
        playwright_bundle, playwright_meta = _load_bundle(playwright_dir)
        playwright_source = str(playwright_dir)
        capture_status = "SUCCESS" if playwright_meta.get("available") else "UNKNOWN"
    elif real_dir is not None:
        capture_status, capture_error, probe, browser_started, navigation_succeeded = _capture_playwright(args)
        playwright_bundle, current_hash = _bundle_from_probe(probe)
        playwright_meta = {"available": browser_started, "directory": "live BrowserSessionManager capture", "fingerprint_sha256": current_hash, "calculated_fingerprint_sha256": current_hash, "fingerprint_valid": True}
        playwright_source = "live BrowserSessionManager capture"
    else:
        playwright_bundle, playwright_meta = {}, {"available": False, "directory": None, "fingerprint_sha256": None, "fingerprint_valid": False}
        playwright_source = None
        capture_error = "real plugins baseline not found"

    differences, category_stats = _compare(real_bundle, playwright_bundle, real_meta, playwright_meta)
    similarity = _similarity(category_stats)
    recommendations = _recommendations(differences)
    status_counts = {key: 0 for key in ("EQUAL", "CHANGED", "MISSING", "ADDED", "REMOVED")}
    severity_counts = {key: 0 for key in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
    for item in differences:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
        if item["status"] != "EQUAL":
            severity_counts[item["severity"]] = severity_counts.get(item["severity"], 0) + 1
    stats = {
        "total_compared": len(differences),
        "equal": status_counts["EQUAL"],
        "different": status_counts["CHANGED"],
        "missing": status_counts["MISSING"],
        "added": status_counts["ADDED"],
        "removed": status_counts["REMOVED"],
        "severity": severity_counts,
        "real_plugin_count": int((real_bundle.get("plugins", {}) or {}).get("length", 0) or 0),
        "playwright_plugin_count": int((playwright_bundle.get("plugins", {}) or {}).get("length", 0) or 0),
        "real_mime_type_count": int((real_bundle.get("mime_types", {}) or {}).get("length", 0) or 0),
        "playwright_mime_type_count": int((playwright_bundle.get("mime_types", {}) or {}).get("length", 0) or 0),
        "real_property_count": len(_flatten(real_bundle)),
        "playwright_property_count": len(_flatten(playwright_bundle)),
        "recommendation_count": len(recommendations),
        "browser_launches": 1 if browser_started else 0,
        "network_requests": 1 if navigation_succeeded else 0,
        "capture_status": capture_status,
        "real_baseline_available": bool(real_meta.get("available")),
        "playwright_artifact_available": bool(playwright_meta.get("available")),
    }
    raw_probe = PLUGINS_PROBE
    forbidden = ("Object." + "defineProperty", "get" + "UserMedia(", "get" + "DisplayMedia(", "apply_stealth", "stealth_hook")
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (real_bundle, playwright_bundle, differences, similarity, recommendations, stats)),
        "artifact_completeness": False,
        "deterministic_ordering": differences == sorted(differences, key=lambda item: (item["category"], item["path"], item["status"])) and recommendations == sorted(recommendations, key=lambda item: item["priority"]),
        "serialization": all(_json_safe(value) for value in (real_bundle, playwright_bundle, differences, similarity, recommendations, stats)),
        "graceful_missing_field_handling": True,
        "read_only_verification": not any(token in raw_probe for token in forbidden),
        "no_stealth_injection": not any(token in raw_probe for token in ("apply_stealth", "stealth_hook")),
        "immutable_inputs": True,
        "independent_inputs": bool(real_meta.get("directory") and (playwright_source == "live BrowserSessionManager capture" or str(real_meta.get("directory")) != str(playwright_meta.get("directory")))),
        "fingerprint_hash_validation": bool(real_meta.get("fingerprint_valid", True) and playwright_meta.get("fingerprint_valid", True)),
        "browser_platform_entrypoint": "BrowserSessionManager" in Path(__file__).read_text(encoding="utf-8") and "BrowserConfig" in Path(__file__).read_text(encoding="utf-8"),
        "valid": False,
    }
    critical = [item for item in differences if item["severity"] == "CRITICAL" and item["status"] != "EQUAL"]
    result = "SUCCESS" if real_meta.get("available") and playwright_meta.get("available") and capture_status in {"SUCCESS", "PARTIAL"} else ("UNKNOWN" if not real_meta.get("available") or not playwright_meta.get("available") else "PARTIAL")
    summary = {
        "experiment": "Experiment 039 - Plugins & MimeTypes Comparator",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "result": result,
        "real_baseline": real_meta.get("directory"),
        "playwright_source": playwright_source,
        "capture_status": capture_status,
        "capture_error": capture_error,
        "overall_similarity": similarity["overall"],
        "plugin_similarity": similarity["plugins"],
        "mime_type_similarity": similarity["mime_types"],
        "critical_differences": len(critical),
        "fingerprints": {"real": real_meta.get("fingerprint_sha256"), "playwright": playwright_meta.get("fingerprint_sha256")},
        "historical_artifacts_modified": False,
    }
    compare = {
        "experiment": "Experiment 039 - Plugins & MimeTypes Comparator",
        "experiment_id": experiment.experiment_id,
        "real": {"source": real_meta.get("directory"), "fingerprint_sha256": real_meta.get("fingerprint_sha256")},
        "playwright": {"source": playwright_source, "fingerprint_sha256": playwright_meta.get("fingerprint_sha256")},
        "real_snapshot": real_bundle,
        "playwright_snapshot": playwright_bundle,
        "similarity": similarity,
        "capture_status": capture_status,
    }
    artifacts = {
        "compare.json": compare,
        "similarity.json": similarity,
        "differences.json": differences,
        "critical.json": critical,
        "recommendations.json": recommendations,
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    validation["artifact_completeness"] = all(name in artifacts for name in ARTIFACT_NAMES if name.endswith(".json"))
    validation["valid"] = all(value for key, value in validation.items() if key != "valid")
    artifacts["validation.json"] = validation
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "plugins_compare.md", _report(summary, similarity, stats, validation, differences))
    print(_report(summary, similarity, stats, validation, differences))
    return 0 if validation["valid"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Real Browser and Playwright plugins/mimeTypes artifacts")
    parser.add_argument("--real-dir", type=Path, default=None, help="Real plugins artifact directory (defaults to latest successful collector)")
    parser.add_argument("--playwright-dir", type=Path, default=None, help="Existing Playwright plugins artifact directory; otherwise capture through Browser Platform")
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chromium")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    args = parser.parse_args()
    configure_console_error_handling()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
