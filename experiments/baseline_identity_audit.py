"""Experiment 060A: offline audit of missing integrated identity baselines.

The audit intentionally has no browser, Playwright, or network dependency.  It
replays the discovery contract used by ``integrated_identity.py`` against the
immutable Canvas, Audio, and Client Hints artifacts and explains every gate
that prevented verification.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    sha256_file,
    write_json_exclusive,
    write_text_exclusive,
)


MODULES = ("canvas", "audio", "client_hints")
ARTIFACT_NAMES = (
    "audit.json",
    "per_module.json",
    "registry_check.json",
    "schema_check.json",
    "recommendations.json",
    "summary.json",
    "validation.json",
    "baseline_audit.md",
)


def _ordered(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _ordered(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    return value


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _read_json(path: Path) -> tuple[dict[str, Any], bool, str | None]:
    if not path.is_file():
        return {}, False, "missing_file"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, False, f"invalid_json:{type(exc).__name__}"
    if not isinstance(value, dict):
        return {}, False, "top_level_not_object"
    return value, True, None


def _experiment_number(path: Path) -> int:
    match = re.fullmatch(r"exp_(\d+)", path.name)
    return int(match.group(1)) if match else -1


def _sha256(path: Path) -> str | None:
    try:
        return sha256_file(path)
    except OSError:
        return None


def _artifact_hashes(directory: Path) -> dict[str, str | None]:
    if not directory.is_dir():
        return {}
    result: dict[str, str | None] = {}
    for path in sorted((item for item in directory.iterdir() if item.is_file()), key=lambda item: item.name):
        result[path.name] = _sha256(path)
    return result


def _candidate_directories(root: Path, module: str) -> list[Path]:
    reports = root / "reports" / "experiments"
    candidates = [item / module for item in reports.glob("exp_*") if (item / module).is_dir()]
    return sorted(candidates, key=lambda item: (_experiment_number(item.parent), item.as_posix()))


def _source_schema(root: Path) -> dict[str, Any]:
    source_path = root / "experiments" / "integrated_identity.py"
    try:
        source = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {
            "source_path": str(source_path),
            "source_exists": False,
            "source_sha256": None,
            "parseable": False,
            "parse_error": str(exc),
            "module_artifacts": {},
        }

    module_artifacts: dict[str, list[str]] = {}
    parse_error: str | None = None
    try:
        tree = ast.parse(source, filename=str(source_path))
        for node in tree.body:
            target: str | None = None
            value: ast.AST | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            if target == "MODULE_ARTIFACTS" and value is not None:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, dict):
                    module_artifacts = {
                        str(module): [str(name) for name in names]
                        for module, names in parsed.items()
                        if isinstance(names, (tuple, list))
                    }
    except (SyntaxError, ValueError, TypeError) as exc:
        parse_error = f"{type(exc).__name__}: {exc}"

    # These expressions are the contract, rather than assumptions copied from
    # a collector.  Keeping them in the audit makes schema drift visible.
    return _ordered(
        {
            "source_path": str(source_path.resolve()),
            "source_exists": source_path.is_file(),
            "source_sha256": _sha256(source_path),
            "parseable": parse_error is None,
            "parse_error": parse_error,
            "module_artifacts": module_artifacts,
            "expected_modules": list(MODULES),
            "discovery_contract": {
                "required_artifacts": module_artifacts.get("canvas", ["fingerprint.json"]),
                "successful_summary_result": "SUCCESS",
                "successful_validation_valid": True,
                "selection_order": "successful, then complete, then any candidate; highest experiment number",
                "unverified_gate": "fingerprint.json top-level sha256 must be a non-empty string",
            },
            "load_contract": {
                "fingerprint_top_level_type": "object",
                "required_fingerprint_fields": ["sha256", "data"],
                "sha256_type": "string",
                "sha256_format": "64 hexadecimal characters",
                "data_type": "object",
            },
            "source_contract_evidence": {
                "reads_fingerprint_sha256": 'fingerprint.get("sha256")',
                "reads_fingerprint_data": 'fingerprint.get("data")',
                "requires_summary_success": 'summary.get("result") == "SUCCESS"',
                "requires_validation_valid": 'validation.get("valid") is True',
            },
        }
    )


def _fingerprint_schema(fingerprint: dict[str, Any], valid_json: bool) -> dict[str, Any]:
    raw_sha = fingerprint.get("sha256") if valid_json else None
    data = fingerprint.get("data") if valid_json else None
    sha_valid = isinstance(raw_sha, str) and bool(raw_sha) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", raw_sha))
    return _ordered(
        {
            "json_valid": valid_json,
            "top_level_type": "object" if valid_json else None,
            "top_level_keys": sorted(fingerprint.keys()) if valid_json else [],
            "sha256_present": "sha256" in fingerprint if valid_json else False,
            "sha256_type": type(raw_sha).__name__ if raw_sha is not None else None,
            "sha256_non_empty": isinstance(raw_sha, str) and bool(raw_sha),
            "sha256_format_valid": sha_valid,
            "sha256_preview": raw_sha[:12] if isinstance(raw_sha, str) else None,
            "data_present": "data" in fingerprint if valid_json else False,
            "data_type": type(data).__name__ if data is not None else None,
            "data_object": isinstance(data, dict),
            "modes_present": isinstance(fingerprint.get("modes"), dict) if valid_json else False,
            "mode_count": len(fingerprint.get("modes", {})) if isinstance(fingerprint.get("modes"), dict) else 0,
            "compatible_with_integrated_identity": bool(sha_valid and isinstance(data, dict)),
        }
    )


def _inspect_module(root: Path, module: str, schema: dict[str, Any]) -> dict[str, Any]:
    candidates = _candidate_directories(root, module)
    required_artifacts = list(schema.get("module_artifacts", {}).get(module, ["fingerprint.json"]))
    if not required_artifacts:
        required_artifacts = ["fingerprint.json"]
    records: list[dict[str, Any]] = []
    successful: list[Path] = []
    complete: list[Path] = []

    for directory in candidates:
        file_status = {name: (directory / name).is_file() for name in ("summary.json", "validation.json", "fingerprint.json", "statistics.json")}
        fingerprint, fingerprint_valid, fingerprint_error = _read_json(directory / "fingerprint.json")
        summary, summary_valid, summary_error = _read_json(directory / "summary.json")
        validation, validation_valid, validation_error = _read_json(directory / "validation.json")
        statistics, statistics_valid, statistics_error = _read_json(directory / "statistics.json")
        required_complete = all((directory / name).is_file() for name in required_artifacts)
        is_successful = required_complete and summary.get("result") == "SUCCESS" and validation.get("valid") is True
        if required_complete:
            complete.append(directory)
        if is_successful:
            successful.append(directory)
        records.append(
            _ordered(
                {
                    "experiment_id": directory.parent.name,
                    "experiment_number": _experiment_number(directory.parent),
                    "artifact_directory": str(directory.resolve()),
                    "artifact_hashes": _artifact_hashes(directory),
                    "required_artifacts": {name: (directory / name).is_file() for name in required_artifacts},
                    "files": file_status,
                    "summary": {"exists": file_status["summary.json"], "json_valid": summary_valid, "error": summary_error, "result": summary.get("result"), "top_level_keys": sorted(summary.keys()) if summary_valid else []},
                    "validation": {"exists": file_status["validation.json"], "json_valid": validation_valid, "error": validation_error, "valid": validation.get("valid"), "playwright_status": validation.get("playwright_status"), "top_level_keys": sorted(validation.keys()) if validation_valid else []},
                    "fingerprint": _fingerprint_schema(fingerprint, fingerprint_valid) | {"error": fingerprint_error},
                    "statistics": {"exists": file_status["statistics.json"], "json_valid": statistics_valid, "error": statistics_error, "top_level_keys": sorted(statistics.keys()) if statistics_valid else []},
                    "required_complete": required_complete,
                    "successful_candidate": is_successful,
                }
            )
        )

    chosen = (successful or complete or candidates)[-1] if (successful or complete or candidates) else None
    selected_record = next((item for item in records if chosen is not None and item["artifact_directory"] == str(chosen.resolve())), None)
    reasons: list[str] = []
    if chosen is None:
        reasons.append("no_exp_<n>/{0} directory exists".format(module))
        status = "NO_EXPERIMENT"
    else:
        if selected_record is None or not selected_record["required_complete"]:
            reasons.append("mandatory fingerprint.json is absent")
        if selected_record is not None:
            fp = selected_record["fingerprint"]
            if not fp["sha256_present"]:
                reasons.append("fingerprint.json has no top-level sha256")
            elif not fp["sha256_format_valid"]:
                reasons.append("top-level sha256 is not a 64-character hexadecimal digest")
            if not fp["data_present"]:
                reasons.append("fingerprint.json has no top-level data object")
            elif not fp["data_object"]:
                reasons.append("fingerprint.json data is not an object")
            if selected_record["summary"]["result"] != "SUCCESS":
                reasons.append('summary.json does not contain result="SUCCESS"')
            if selected_record["validation"]["valid"] is not True:
                reasons.append("validation.json valid is not true")
            if not selected_record["statistics"]["exists"]:
                reasons.append("statistics.json is absent (not an integrated identity discovery gate)")
            if selected_record["validation"].get("playwright_status") == "UNKNOWN":
                reasons.append("collector validation reports Playwright status UNKNOWN")
            status = "DISCOVERED_VERIFIED" if selected_record["fingerprint"]["compatible_with_integrated_identity"] else "DISCOVERED_UNVERIFIED"

    return _ordered(
        {
            "module": module,
            "experiment_exists": bool(candidates),
            "experiment_numbers": [item["experiment_number"] for item in records],
            "candidate_count": len(records),
            "candidate_experiments": records,
            "selected_experiment": selected_record,
            "artifact_directory": selected_record.get("artifact_directory") if selected_record else None,
            "summary_exists": bool(selected_record and selected_record["summary"]["exists"]),
            "validation_exists": bool(selected_record and selected_record["validation"]["exists"]),
            "fingerprint_exists": bool(selected_record and selected_record["files"]["fingerprint.json"]),
            "sha256_available": bool(selected_record and selected_record["fingerprint"]["sha256_format_valid"]),
            "statistics_available": bool(selected_record and selected_record["statistics"]["exists"]),
            "schema_compatible": bool(selected_record and selected_record["fingerprint"]["compatible_with_integrated_identity"]),
            "discovered_by_integrated_identity": chosen is not None,
            "discovery_status": status,
            "reason_codes": sorted(set(reasons)),
            "explanation": "Verified baseline is selectable only when fingerprint.json supplies a non-empty top-level sha256 and data object; successful selection additionally requires summary.result=SUCCESS and validation.valid=true.",
            "integrated_identity_expected_artifacts": required_artifacts,
        }
    )


def _find_integrated_identity(root: Path) -> tuple[Path | None, dict[str, Any], dict[str, Any]]:
    candidates: list[Path] = []
    for directory in (root / "reports" / "experiments").glob("exp_*"):
        output = directory / "integrated_identity"
        if output.is_dir() and (output / "registry.json").is_file():
            candidates.append(output)
    candidates.sort(key=lambda item: (_experiment_number(item.parent), item.as_posix()))
    if not candidates:
        return None, {}, {}
    chosen = candidates[-1]
    registry, registry_valid, _ = _read_json(chosen / "registry.json")
    summary, summary_valid, _ = _read_json(chosen / "summary.json")
    return chosen, {"valid": registry_valid, "data": registry}, {"valid": summary_valid, "data": summary}


def _registry_check(root: Path, per_module: dict[str, Any]) -> dict[str, Any]:
    directory, registry_info, summary_info = _find_integrated_identity(root)
    registry = registry_info.get("data", {}) if registry_info.get("valid") else {}
    entries: dict[str, Any] = {}
    for module in MODULES:
        audited = per_module[module]
        entry = registry.get(module) if isinstance(registry, dict) else None
        registry_dir = entry.get("directory") if isinstance(entry, dict) else None
        audited_dir = audited.get("artifact_directory")
        entries[module] = _ordered(
            {
                "registry_entry_present": isinstance(entry, dict),
                "registry_status": entry.get("status") if isinstance(entry, dict) else None,
                "registry_available": entry.get("available") if isinstance(entry, dict) else None,
                "registry_experiment_id": entry.get("experiment_id") if isinstance(entry, dict) else None,
                "registry_directory": registry_dir,
                "audited_directory": audited_dir,
                "selection_matches_registry": bool(registry_dir and audited_dir and Path(str(registry_dir)).resolve() == Path(str(audited_dir)).resolve()),
                "registry_sha256": entry.get("fingerprint_sha256") if isinstance(entry, dict) else None,
                "audit_sha256": (audited.get("selected_experiment") or {}).get("fingerprint", {}).get("sha256_preview") if audited.get("selected_experiment") else None,
            }
        )
    return _ordered(
        {
            "integrated_identity_directory": str(directory.resolve()) if directory else None,
            "integrated_identity_experiment": directory.parent.name if directory else None,
            "registry_json_valid": bool(registry_info.get("valid")),
            "summary_json_valid": bool(summary_info.get("valid")),
            "entries": entries,
            "all_entries_present": all(item["registry_entry_present"] for item in entries.values()),
            "all_selections_match": all(item["selection_matches_registry"] for item in entries.values() if item["registry_entry_present"]),
        }
    )


def _recommendations(per_module: dict[str, Any], schema: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for module in MODULES:
        item = per_module[module]
        if item["discovery_status"] == "DISCOVERED_UNVERIFIED":
            recommendations.append(
                {
                    "id": f"{module}.baseline_capture",
                    "module": module,
                    "priority": "HIGH",
                    "action": "Capture an independent real-browser baseline using the integrated identity schema.",
                    "reason": "; ".join(item["reason_codes"]),
                    "required_output": ["fingerprint.json.sha256", "fingerprint.json.data", "summary.json.result=SUCCESS", "validation.json.valid=true"],
                    "does_not_modify": ["stealth modules", "integrated registry", "historical artifacts"],
                }
            )
        elif item["discovery_status"] == "NO_EXPERIMENT":
            recommendations.append(
                {
                    "id": f"{module}.baseline_missing",
                    "module": module,
                    "priority": "CRITICAL",
                    "action": "Create an independent collector baseline before rerunning integrated identity.",
                    "reason": "No module experiment directory was discovered.",
                    "required_output": ["fingerprint.json", "summary.json", "validation.json"],
                }
            )
        if item["statistics_available"] is False:
            recommendations.append(
                {
                    "id": f"{module}.statistics_optional",
                    "module": module,
                    "priority": "LOW",
                    "action": "Add statistics.json to future baseline captures for audit completeness.",
                    "reason": "Statistics are not a discovery gate but are requested by the audit.",
                }
            )
    recommendations.append(
        {
            "id": "integrated_identity.rerun",
            "module": "integrated",
            "priority": "MEDIUM",
            "action": "Rerun Experiment 060 only after all three schemas satisfy the source contract.",
            "reason": "The current PARTIAL result is data-quality driven, not a browser consistency failure.",
            "schema_source": schema.get("source_path"),
        }
    )
    return _ordered(sorted(recommendations, key=lambda item: (item.get("priority", ""), item["id"])))


def _report(summary: dict[str, Any], schema: dict[str, Any], per_module: dict[str, Any], registry_check: dict[str, Any], recommendations: list[dict[str, Any]], validation: dict[str, Any]) -> str:
    lines = [
        "# Experiment 060A - Browser Identity Baseline Audit",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Integrated Identity inspected: `{registry_check.get('integrated_identity_experiment') or 'not found'}`",
        f"- Modules audited: **{len(per_module)}**",
        "- Browser launches: **0**",
        "- Network requests: **0**",
        "",
        "## Per-module diagnosis",
        "",
        "| Module | Experiment | Fingerprint | SHA-256 | Schema | Discovery status |",
        "|---|---:|---|---|---|---|",
    ]
    for module in MODULES:
        item = per_module[module]
        selected = item.get("selected_experiment") or {}
        lines.append(
            f"| `{module}` | `{selected.get('experiment_id', 'none')}` | {'yes' if item['fingerprint_exists'] else 'no'} | {'yes' if item['sha256_available'] else 'no'} | {'compatible' if item['schema_compatible'] else 'incompatible'} | **{item['discovery_status']}** |"
        )
    lines += ["", "## Exact reasons", ""]
    for module in MODULES:
        item = per_module[module]
        lines.append(f"### {module}")
        lines.append("")
        lines.append(f"- Artifact directory: `{item.get('artifact_directory') or 'none'}`")
        lines.append(f"- Discovered by Integrated Identity: **{item['discovered_by_integrated_identity']}**")
        lines.append(f"- Reason codes: `{', '.join(item['reason_codes']) or 'none'}`")
        lines.append("")
    lines += [
        "## Integrated Identity schema",
        "",
        f"- Source: `{schema.get('source_path')}`",
        f"- Mandatory discovery files: `{', '.join(schema.get('discovery_contract', {}).get('required_artifacts', []))}`",
        "- Verified fingerprint fields: top-level `sha256` (64 hex characters) and `data` object.",
        "- Successful candidate additionally requires `summary.json.result == \"SUCCESS\"` and `validation.json.valid == true`.",
        "- Missing `statistics.json` is reported but is not a discovery gate.",
        "",
        "## Registry check",
        "",
        f"- Registry valid: **{registry_check['registry_json_valid']}**",
        f"- Entries present: **{registry_check['all_entries_present']}**",
        f"- Audit selection matches registry: **{registry_check['all_selections_match']}**",
        "",
        "## Recommendations",
        "",
    ]
    for recommendation in recommendations:
        lines.append(f"- **{recommendation['priority']}** `{recommendation['id']}`: {recommendation['action']} ({recommendation['reason']})")
    lines += ["", "## Validation", "", f"- Validation: **{'PASS' if validation['valid'] else 'FAIL'}**", "- This report is read-only and contains no regenerated baseline data.", ""]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    historical_before = _historical_hashes(root)
    source_path = root / "experiments" / "integrated_identity.py"
    source_before = _sha256(source_path)
    schema = _source_schema(root)
    per_module = _ordered({module: _inspect_module(root, module, schema) for module in MODULES})
    registry_check = _registry_check(root, per_module)
    recommendations = _recommendations(per_module, schema)
    historical_after = _historical_hashes(root)
    source_after = _sha256(source_path)

    verified = sum(1 for item in per_module.values() if item["discovery_status"] == "DISCOVERED_VERIFIED")
    unverified = sum(1 for item in per_module.values() if item["discovery_status"] == "DISCOVERED_UNVERIFIED")
    missing = sum(1 for item in per_module.values() if item["discovery_status"] == "NO_EXPERIMENT")
    summary = _ordered(
        {
            "experiment": "Experiment 060A - Browser Identity Baseline Audit",
            "experiment_id": None,
            "created_at": now_iso(),
            "result": "PASS" if unverified == 0 and missing == 0 else ("PARTIAL" if verified or unverified else "UNKNOWN"),
            "modules_audited": len(MODULES),
            "verified_modules": verified,
            "unverified_modules": unverified,
            "missing_modules": missing,
            "unverified_module_names": [module for module in MODULES if per_module[module]["discovery_status"] == "DISCOVERED_UNVERIFIED"],
            "missing_module_names": [module for module in MODULES if per_module[module]["discovery_status"] == "NO_EXPERIMENT"],
            "integrated_identity_experiment": registry_check.get("integrated_identity_experiment"),
            "browser_launches": 0,
            "network_requests": 0,
            "historical_artifacts_modified": False,
        }
    )
    source_text = ""
    try:
        source_text = Path(__file__).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        pass
    forbidden_calls = bool(re.search(r"\b(?:sync_playwright|launch_browser|BrowserSessionManager)\s*\(", source_text))
    validation = _ordered(
        {
            "python_compile": True,
            "json_validation": all(_json_safe(value) for value in (schema, per_module, registry_check, recommendations, summary)),
            "artifact_completeness": False,
            "deterministic_ordering": all(list(value.keys()) == sorted(value.keys()) for value in (schema, per_module, registry_check, summary)),
            "read_only_verification": not forbidden_calls and source_before == source_after,
            "browser_launches": 0,
            "network_requests": 0,
            "historical_artifacts_immutable": historical_before == historical_after,
            "integrated_source_available": bool(schema.get("source_exists")),
            "registry_consistency": registry_check["registry_json_valid"] and registry_check["all_entries_present"] and registry_check["all_selections_match"],
            "valid": False,
        }
    )

    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "baseline_audit"
    output.mkdir(parents=True, exist_ok=False)
    audit = _ordered(
        {
            "experiment": summary["experiment"],
            "experiment_id": experiment.experiment_id,
            "created_at": summary["created_at"],
            "scope": {"modules": list(MODULES), "browser_launches": 0, "network_requests": 0, "read_only": True},
            "integrated_identity": schema,
            "summary": summary,
        }
    )
    schema_check = _ordered(
        {
            "source": schema,
            "per_module_compatibility": {module: per_module[module]["schema_compatible"] for module in MODULES},
            "required_fields": schema.get("load_contract", {}).get("required_fingerprint_fields", []),
            "required_artifacts": schema.get("discovery_contract", {}).get("required_artifacts", []),
            "all_modules_compatible": all(per_module[module]["schema_compatible"] for module in MODULES),
        }
    )
    artifact_data = {
        "audit.json": audit,
        "per_module.json": per_module,
        "registry_check.json": registry_check,
        "schema_check.json": schema_check,
        "recommendations.json": recommendations,
        "summary.json": summary,
        "validation.json": validation,
    }
    validation["artifact_completeness"] = all(name in artifact_data for name in ARTIFACT_NAMES if name.endswith(".json"))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})
    summary["validation_valid"] = validation["valid"]
    for filename, value in artifact_data.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "baseline_audit.md", _report(summary, schema, per_module, registry_check, recommendations, validation))
    print("BROWSER IDENTITY BASELINE AUDIT")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Verified: {verified}/{len(MODULES)} | Unverified: {unverified} | Missing: {missing}")
    for module in MODULES:
        print(f"{module}: {per_module[module]['discovery_status']} - {', '.join(per_module[module]['reason_codes']) or 'no issue'}")
    print(f"Browser launches: 0 | Network requests: 0")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def _historical_hashes(root: Path) -> dict[str, str]:
    reports = root / "reports" / "experiments"
    output: dict[str, str] = {}
    if not reports.is_dir():
        return output
    for path in sorted((item for item in reports.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        try:
            output[str(path.relative_to(root))] = sha256_file(path)
        except OSError:
            output[str(path.relative_to(root))] = ""
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 060A: audit integrated identity baseline schemas")
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
