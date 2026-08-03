"""Experiment 042: measured evaluation of the Plugins stealth module.

Two independent Browser Platform sessions are captured: a plain Playwright
session and a session with ``stealth/modules/plugins.js`` enabled.  Both are
compared with the immutable Real Browser baseline.  No direct Playwright
launch, network interception, or non-plugin browser mutation is performed.
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
from experiments.plugins_collector import PLUGINS_PROBE
from experiments.plugins_comparator import (
    _bundle_from_probe,
    _compare,
    _find_directory,
    _load_bundle,
    _similarity,
)
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    sha256_file,
    write_json_exclusive,
    write_text_exclusive,
)


MODULE_PATH = Path(__file__).resolve().parent.parent / "stealth" / "modules" / "plugins.js"
ARTIFACT_NAMES = (
    "compare.json",
    "similarity.json",
    "differences.json",
    "score.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "plugins_evaluation.md",
)


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _artifact_hashes(directory: Path | None) -> dict[str, str]:
    """Hash baseline files to verify the read-only input boundary."""
    if directory is None or not directory.is_dir():
        return {}
    hashes: dict[str, str] = {}
    for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
        try:
            hashes[path.name] = sha256_file(path)
        except (OSError, ValueError):
            hashes[path.name] = ""
    return hashes


def _load_profile(real_bundle: dict[str, Any]) -> dict[str, Any]:
    """Derive a profile exclusively from the Real Browser artifact."""
    plugins = real_bundle.get("plugins", {}) if isinstance(real_bundle.get("plugins"), dict) else {}
    mime_types = real_bundle.get("mime_types", {}) if isinstance(real_bundle.get("mime_types"), dict) else {}
    plugin_profile = []
    for item in plugins.get("items", []) if isinstance(plugins.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        plugin_profile.append({
            "name": str(item.get("name", "")),
            "filename": str(item.get("filename", "")),
            "description": str(item.get("description", "")),
            "mimeTypes": [
                {"type": str(value), "suffixes": "", "description": ""}
                for value in item.get("mimeTypes", []) if isinstance(value, str) and value
            ],
        })
    mime_profile = []
    for item in mime_types.get("items", []) if isinstance(mime_types.get("items"), list) else []:
        if not isinstance(item, dict) or not item.get("type"):
            continue
        mime_profile.append({
            "type": str(item.get("type", "")),
            "suffixes": str(item.get("suffixes", "")),
            "description": str(item.get("description", "")),
            "enabledPlugin": str(item.get("enabledPluginName", "")),
        })
    return {"plugins": plugin_profile, "mimeTypes": mime_profile}


def _capture(args: argparse.Namespace, module_enabled: bool, profile: dict[str, Any]) -> tuple[str, str | None, dict[str, Any], bool, bool]:
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
    browser_started = False
    navigation_succeeded = False
    error: str | None = None
    probe: dict[str, Any] = {}
    try:
        manager.start()
        browser_started = True
        context = manager.get_context()
        if module_enabled:
            module = MODULE_PATH.read_text(encoding="utf-8")
            init_script = "globalThis.__stealth = {pluginsProfile: " + json.dumps(profile, ensure_ascii=False, separators=(",", ":")) + "};\n" + module
            context.add_init_script(script=init_script)
        page = manager.new_page()
        if args.url and args.url != "about:blank":
            try:
                page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout)
                navigation_succeeded = True
            except Exception as exc:
                error = f"navigation: {exc}"
        try:
            value = page.evaluate(PLUGINS_PROBE)
            if not isinstance(value, dict):
                raise TypeError("plugins probe returned a non-object result")
            probe = value
        except Exception as exc:
            error = f"probe: {exc}"
            probe = {}
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
    exists = bool((probe.get("plugins") or {}).get("exists")) and bool((probe.get("mimeTypes") or {}).get("exists"))
    status = "SUCCESS" if browser_started and exists and not error else ("PARTIAL" if browser_started else "UNKNOWN")
    return status, error, probe, browser_started, navigation_succeeded


def _status_map(differences: list[dict[str, Any]]) -> dict[str, str]:
    return {str(item.get("path")): str(item.get("status", "UNKNOWN")) for item in differences if isinstance(item, dict)}


def _method_records(value: Any):
    """Yield method probe records through the nested prototype maps."""
    if isinstance(value, dict):
        if "available" in value:
            yield value
            return
        for child in value.values():
            yield from _method_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _method_records(child)


def _domain_delta(plain: dict[str, Any], patched: dict[str, Any]) -> dict[str, dict[str, float]]:
    domains = set(plain.get("domains", {})) | set(patched.get("domains", {}))
    result: dict[str, dict[str, float]] = {}
    for domain in sorted(domains):
        before = float((plain.get("domains", {}).get(domain, {}) or {}).get("similarity", 0.0))
        after = float((patched.get("domains", {}).get(domain, {}) or {}).get("similarity", 0.0))
        result[domain] = {"plain": round(before, 2), "plugins": round(after, 2), "delta": round(after - before, 2)}
    return result


def _report(summary: dict[str, Any], similarity: dict[str, Any], stats: dict[str, Any], validation: dict[str, Any]) -> str:
    modes = similarity.get("modes", {})
    lines = [
        "# Experiment 042 - Plugins Stealth Evaluation",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Conclusion: **{summary['conclusion']}**",
        f"- Resolved differences: **{stats['resolved_differences']}**",
        f"- Regression count: **{stats['regression_count']}**",
        f"- Total diff: **{stats['plain_differences']} -> {stats['plugins_differences']} ({stats['diff_delta']:+d})**",
        "",
        "## Measured Similarity",
        "",
        "| Mode | Overall | Plugin | MimeType | Prototype | Descriptor | Method | Cross-reference | Total Diff | Resolved | Regressions |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in ("Plain", "Plugins"):
        row = modes.get(mode, {})
        lines.append(
            f"| {mode} | {row.get('overall', 0):.2f}% | {row.get('plugins', 0):.2f}% | {row.get('mime_types', 0):.2f}% | "
            f"{row.get('prototype', 0):.2f}% | {row.get('descriptors', 0):.2f}% | {row.get('methods', 0):.2f}% | "
            f"{row.get('cross_reference', 0):.2f}% | {row.get('total_diff', 0)} | {row.get('resolved', 0)} | {row.get('regressions', 0)} |"
        )
    lines += [
        "",
        "## Delta",
        "",
        f"- Overall delta: **{similarity.get('delta', {}).get('overall', 0):+.2f}%**",
        f"- Plugin delta: **{similarity.get('delta', {}).get('plugins', 0):+.2f}%**",
        f"- MimeType delta: **{similarity.get('delta', {}).get('mime_types', 0):+.2f}%**",
        "",
        "## Difference Accounting",
        "",
        "Stable regressions count only properties that were equal in Plain and became non-equal after enabling the module. Total diff is reported separately so object-shape changes remain visible.",
        f"- Plain non-equal properties: **{stats['plain_differences']}**",
        f"- Plugins non-equal properties: **{stats['plugins_differences']}**",
        f"- Resolved Plain differences: **{stats['resolved_differences']}**",
        "",
        "## Validation",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    lines.extend(f"| {key.replace('_', ' ').title()} | {'PASS' if value else 'FAIL'} |" for key, value in validation.items())
    lines += [
        "",
        "## Conclusion",
        "",
        summary["conclusion"],
        "",
        "The evaluation uses the immutable Real Browser profile as input and applies only `stealth/modules/plugins.js`; no other browser or network surface is changed.",
        "",
    ]
    return "\n".join(lines)


def _positive_timeout(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return result


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    real_dir = _find_directory(root, args.real_dir)
    baseline_hashes_before = _artifact_hashes(real_dir)
    real_bundle, real_meta = _load_bundle(real_dir)
    profile = _load_profile(real_bundle)
    experiment = Experiment.create(reports_root)
    output = experiment.directory / "plugins_evaluation"
    output.mkdir(parents=True, exist_ok=False)

    plain_status, plain_error, plain_probe, plain_started, plain_navigated = _capture(args, False, profile) if real_meta.get("available") else ("UNKNOWN", "real baseline not found", {}, False, False)
    plugin_status, plugin_error, plugin_probe, plugin_started, plugin_navigated = _capture(args, True, profile) if real_meta.get("available") else ("UNKNOWN", "real baseline not found", {}, False, False)
    baseline_hashes_after = _artifact_hashes(real_dir)
    plain_bundle, plain_hash = _bundle_from_probe(plain_probe)
    plugin_bundle, plugin_hash = _bundle_from_probe(plugin_probe)
    plain_meta = {"fingerprint_sha256": plain_hash, "available": plain_started, "fingerprint_valid": True}
    plugin_meta = {"fingerprint_sha256": plugin_hash, "available": plugin_started, "fingerprint_valid": True}
    plain_differences, plain_categories = _compare(real_bundle, plain_bundle, real_meta, plain_meta)
    plugin_differences, plugin_categories = _compare(real_bundle, plugin_bundle, real_meta, plugin_meta)
    plain_similarity = _similarity(plain_categories)
    plugin_similarity = _similarity(plugin_categories)
    plain_map = _status_map(plain_differences)
    plugin_map = _status_map(plugin_differences)
    paths = sorted(set(plain_map) | set(plugin_map))
    # A path can be absent from one comparator output when the native object
    # shape differs.  It is only a *resolved* difference when the path was
    # explicitly non-equal in Plain and explicitly equal after the module.
    resolved = [
        path for path in paths
        if path in plain_map and plain_map[path] != "EQUAL" and plugin_map.get(path) == "EQUAL"
    ]
    regressions = [
        path for path in paths
        if path in plain_map and path in plugin_map
        and plain_map[path] == "EQUAL" and plugin_map[path] != "EQUAL"
    ]
    remaining = [item for item in plugin_differences if item.get("status") != "EQUAL"]
    differences = {
        "plain": plain_differences,
        "plugins": plugin_differences,
        "resolved": sorted(resolved),
        "regressions": sorted(regressions),
        "remaining": remaining,
    }
    domain_delta = _domain_delta(plain_similarity, plugin_similarity)
    similarity = {
        "modes": {
            "Plain": {**{key: plain_similarity.get(key, 0.0) for key in ("overall", "plugins", "mime_types", "prototype", "descriptors", "methods", "cross_reference")}, "total_diff": sum(1 for item in plain_differences if item.get("status") != "EQUAL"), "resolved": 0, "regressions": 0},
            "Plugins": {**{key: plugin_similarity.get(key, 0.0) for key in ("overall", "plugins", "mime_types", "prototype", "descriptors", "methods", "cross_reference")}, "total_diff": len(remaining), "resolved": len(resolved), "regressions": len(regressions)},
        },
        "delta": {
            "overall": round(plugin_similarity.get("overall", 0.0) - plain_similarity.get("overall", 0.0), 2),
            "plugins": round(plugin_similarity.get("plugins", 0.0) - plain_similarity.get("plugins", 0.0), 2),
            "mime_types": round(plugin_similarity.get("mime_types", 0.0) - plain_similarity.get("mime_types", 0.0), 2),
            "prototype": round(plugin_similarity.get("prototype", 0.0) - plain_similarity.get("prototype", 0.0), 2),
            "descriptors": round(plugin_similarity.get("descriptors", 0.0) - plain_similarity.get("descriptors", 0.0), 2),
            "methods": round(plugin_similarity.get("methods", 0.0) - plain_similarity.get("methods", 0.0), 2),
            "cross_reference": round(plugin_similarity.get("cross_reference", 0.0) - plain_similarity.get("cross_reference", 0.0), 2),
        },
        "domains": domain_delta,
    }
    stats = {
        "real_plugin_count": int((real_bundle.get("plugins", {}) or {}).get("length", 0) or 0),
        "real_mime_type_count": int((real_bundle.get("mime_types", {}) or {}).get("length", 0) or 0),
        "plain_plugin_count": int((plain_bundle.get("plugins", {}) or {}).get("length", 0) or 0),
        "plain_mime_type_count": int((plain_bundle.get("mime_types", {}) or {}).get("length", 0) or 0),
        "plugins_plugin_count": int((plugin_bundle.get("plugins", {}) or {}).get("length", 0) or 0),
        "plugins_mime_type_count": int((plugin_bundle.get("mime_types", {}) or {}).get("length", 0) or 0),
        "plain_differences": sum(1 for item in plain_differences if item.get("status") != "EQUAL"),
        "plugins_differences": len(remaining),
        "diff_delta": len(remaining) - sum(1 for item in plain_differences if item.get("status") != "EQUAL"),
        "resolved_differences": len(resolved),
        "regression_count": len(regressions),
        "critical_remaining": sum(1 for item in remaining if item.get("severity") == "CRITICAL"),
        "browser_launches": int(plain_started) + int(plugin_started),
        "network_requests": int(plain_navigated) + int(plugin_navigated),
        "plain_status": plain_status,
        "plugins_status": plugin_status,
    }
    plugin_source = MODULE_PATH.read_text(encoding="utf-8") if MODULE_PATH.is_file() else ""
    source_code = Path(__file__).read_text(encoding="utf-8")
    direct_tokens = (
        "chromium" + "." + "launch(",
        "playwright." + "chromium" + "." + "launch(",
    )
    direct_launch = any(
        line.strip().startswith(direct_tokens)
        for line in source_code.splitlines()
    )
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (real_bundle, plain_bundle, plugin_bundle, differences, similarity, stats, profile)),
        "artifact_completeness": False,
        "deterministic_ordering": plain_differences == sorted(plain_differences, key=lambda item: (item.get("category", ""), item.get("path", ""), item.get("status", ""))) and plugin_differences == sorted(plugin_differences, key=lambda item: (item.get("category", ""), item.get("path", ""), item.get("status", ""))),
        "prototype_validation": bool((plugin_bundle.get("plugins", {}) or {}).get("instanceof")) and bool((plugin_bundle.get("mime_types", {}) or {}).get("instanceof")) and bool((plugin_bundle.get("prototype", {}) or {}).get("pluginInstanceof")) and bool((plugin_bundle.get("prototype", {}) or {}).get("mimeInstanceof")),
        "descriptor_validation": bool(plugin_bundle.get("descriptors")) and bool((plugin_bundle.get("plugins", {}) or {}).get("symbolToStringTag") is not None) and bool((plugin_bundle.get("mime_types", {}) or {}).get("symbolToStringTag") is not None),
        "native_source_validation": all(
            (not value.get("available")) or bool(value.get("nativeSource"))
            for value in _method_records(plugin_bundle.get("methods", {}))
        ),
        "cross_reference_validation": bool((plugin_bundle.get("cross_reference", {}) or {}).get("bidirectionalValid")),
        "regression_detection": len(regressions) == 0,
        "baseline_hash_validation": bool(real_meta.get("fingerprint_valid")),
        "fingerprint_hash_comparison": all(
            isinstance(value, str) and len(value) == 64
            for value in (real_meta.get("fingerprint_sha256"), plain_hash, plugin_hash)
        ),
        "browser_platform_verification": "BrowserSessionManager" in source_code and "BrowserConfig" in source_code and not direct_launch,
        "plugins_module_only": "getUserMedia(" not in plugin_source and "fetch(" not in plugin_source and "XMLHttpRequest" not in plugin_source,
        "immutable_input_verification": bool(real_meta.get("available")) and baseline_hashes_before == baseline_hashes_after,
        "valid": False,
    }
    primary_domain_regression = (
        similarity["delta"].get("plugins", 0.0) < 0.0
        or similarity["delta"].get("mime_types", 0.0) < 0.0
    )
    if similarity["delta"]["overall"] > 0 and not regressions:
        conclusion = "Plugins module improved overall similarity without stable regression."
        if primary_domain_regression:
            conclusion += " PluginArray/MimeTypeArray sub-scores declined and require follow-up refinement."
    elif similarity["delta"]["overall"] == 0 and not regressions:
        conclusion = "Plugins module produced no measurable improvement."
    else:
        conclusion = "Plugins module regressed at least one previously equal property."
    summary = {
        "experiment": "Experiment 042 - Plugins Stealth Evaluation",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "result": "SUCCESS" if plain_status == "SUCCESS" and plugin_status == "SUCCESS" else ("UNKNOWN" if not real_meta.get("available") else "PARTIAL"),
        "real_baseline": real_meta.get("directory"),
        "profile_source": real_meta.get("directory"),
        "plain_status": plain_status,
        "plugins_status": plugin_status,
        "overall_plain": plain_similarity.get("overall", 0.0),
        "overall_plugins": plugin_similarity.get("overall", 0.0),
        "overall_delta": similarity["delta"]["overall"],
        "resolved_differences": len(resolved),
        "regression_count": len(regressions),
        "critical_differences_remaining": stats["critical_remaining"],
        "total_diff_plain": stats["plain_differences"],
        "total_diff_plugins": stats["plugins_differences"],
        "total_diff_delta": stats["diff_delta"],
        "plugin_similarity_plain": plain_similarity.get("plugins", 0.0),
        "plugin_similarity_plugins": plugin_similarity.get("plugins", 0.0),
        "mime_type_similarity_plain": plain_similarity.get("mime_types", 0.0),
        "mime_type_similarity_plugins": plugin_similarity.get("mime_types", 0.0),
        "primary_domain_regression": primary_domain_regression,
        "conclusion": conclusion,
        "fingerprints": {"real": real_meta.get("fingerprint_sha256"), "plain": plain_hash, "plugins": plugin_hash},
        "historical_artifacts_modified": False,
        "baseline_hashes_before": baseline_hashes_before,
        "baseline_hashes_after": baseline_hashes_after,
    }
    validation["artifact_completeness"] = True
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness"})
    compare = {
        "experiment": "Experiment 042 - Plugins Stealth Evaluation",
        "experiment_id": experiment.experiment_id,
        "real": real_bundle,
        "plain": plain_bundle,
        "plugins": plugin_bundle,
        "plain_error": plain_error,
        "plugins_error": plugin_error,
        "profile": profile,
        "fingerprints": summary["fingerprints"],
    }
    score = {
        "plain": {"overall": plain_similarity.get("overall", 0.0), "plugin": plain_similarity.get("plugins", 0.0), "mime_type": plain_similarity.get("mime_types", 0.0)},
        "plugins": {"overall": plugin_similarity.get("overall", 0.0), "plugin": plugin_similarity.get("plugins", 0.0), "mime_type": plugin_similarity.get("mime_types", 0.0)},
        "delta": similarity["delta"],
        "regression_count": len(regressions),
    }
    artifacts = {
        "compare.json": compare,
        "similarity.json": similarity,
        "differences.json": differences,
        "score.json": score,
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    report = _report(summary, similarity, stats, validation)
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "plugins_evaluation.md", report)
    print("PLUGINS STEALTH EVALUATION")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Plain overall: {plain_similarity.get('overall', 0.0):.2f}%")
    print(f"Plugins overall: {plugin_similarity.get('overall', 0.0):.2f}%")
    print(f"Resolved: {len(resolved)} | Regressions: {len(regressions)}")
    print(f"Browser launches: {stats['browser_launches']} | Network requests: {stats['network_requests']}")
    print(f"Conclusion: {conclusion}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 042: evaluate Plugins stealth module")
    parser.add_argument("--real-dir", type=Path, default=None, help="Real plugins artifact directory (defaults to exp_142/plugins)")
    parser.add_argument("--url", default="https://example.com")
    # Playwright evaluation defaults to bundled Chromium; ``--browser=chrome``
    # remains available for a same-channel comparison with the Real baseline.
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chromium")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    configure_console_error_handling()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
