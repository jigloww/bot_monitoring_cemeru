"""Experiment 002: audit the Navigator fingerprint surface.

The audit is intentionally read-only. It consumes the three fingerprints
already produced by the collectors and reuses the comparator's flattening,
numeric equality, category, severity, and recommendation knowledge base.

Run from the repository root::

    python experiments/navigator_audit.py
"""
from __future__ import annotations

import argparse
import json
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    read_json,
    relative_path,
)
from tools.compare_fingerprint import flatten, lookup_kb, vals_equal


STATUS_ORDER = ("Improved", "Still Different", "Regression", "Missing", "Equal")
SEVERITY_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
MISSING = "<missing>"

# Exact Navigator members not all have entries in the comparator KB. These
# recommendations are descriptive only; this experiment never creates patches.
RECOMMENDATIONS = {
    "navigator.webdriver": "Keep false and expose it as a Navigator.prototype getter.",
    "navigator.languages": "Align the frozen language list with the browser locale profile.",
    "navigator.language": "Keep equal to languages[0].",
    "navigator.platform": "Keep consistent with the UA and UA-CH platform.",
    "navigator.vendor": "Keep consistent with the selected Chromium family.",
    "navigator.deviceMemory": "Use a realistic Chromium memory bucket.",
    "navigator.hardwareConcurrency": "Use a realistic logical-core value for the profile.",
    "navigator.userAgentData": "Keep brands, platform, mobile, and high-entropy hints coherent.",
    "navigator.plugins": "Expose a stable PluginArray with realistic PDF plugin relationships.",
    "navigator.mimeTypes": "Expose a stable MimeTypeArray linked to the PDF plugin.",
    "navigator.pdfViewerEnabled": "Match the desktop Chromium PDF viewer capability.",
    "navigator.maxTouchPoints": "Match the selected desktop/mobile profile.",
    "navigator.cookieEnabled": "Preserve the normal browser cookie capability.",
    "navigator.onLine": "Preserve the browser's current network state.",
    "navigator.doNotTrack": "Preserve the browser preference or null when unspecified.",
    "plugins.plugin_count": "Match the real browser plugin count/profile.",
    "plugins.mime_count": "Match the real browser MIME type count/profile.",
}


@dataclass(frozen=True)
class PropertyAudit:
    key: str
    category: str
    reference: Any
    plain: Any
    patched: Any
    status: str
    severity: str
    recommendation: str
    missing_in: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "property": self.key,
            "category": self.category,
            "reference_value": self.reference,
            "plain_value": self.plain,
            "patched_value": self.patched,
            "status": self.status,
            "severity": self.severity,
            "recommendation": self.recommendation,
            "missing_in": list(self.missing_in),
        }


def _fingerprint(path: Path) -> dict[str, Any]:
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise ValueError(f"Fingerprint root must be an object: {path}")
    fingerprint = raw.get("fingerprint", raw)
    if not isinstance(fingerprint, dict) or not fingerprint:
        raise ValueError(f"Fingerprint object missing or empty: {path}")
    return fingerprint


def _metadata(path: Path) -> dict[str, Any]:
    raw = read_json(path)
    metadata = raw.get("_meta", {}) if isinstance(raw, dict) else {}
    return metadata if isinstance(metadata, dict) else {}


def _surface_values(fingerprint: dict[str, Any]) -> dict[str, Any]:
    """Flatten leaves and retain object-level Navigator properties."""
    values = flatten(fingerprint)
    navigator = fingerprint.get("navigator")
    if isinstance(navigator, dict):
        for property_name, value in navigator.items():
            values[f"navigator.{property_name}"] = value
    # Plugin counts are scalar Navigator collection observations. The nested
    # plugin entries remain represented by their flattened leaf keys.
    plugins = fingerprint.get("plugins")
    if isinstance(plugins, dict):
        for property_name in ("plugin_count", "mime_count"):
            if property_name in plugins:
                values[f"plugins.{property_name}"] = plugins[property_name]
    return values


def _navigator_key(key: str) -> bool:
    # plugins.* is collected outside navigator in the existing fingerprint
    # schema, but is part of navigator.plugins/mimeTypes and must be audited.
    return key.startswith("navigator.") or key.startswith("plugins.")


def _severity(stars: int, status: str) -> str:
    if status == "Equal":
        return "Low"
    return {5: "Critical", 4: "High", 3: "Medium"}.get(stars, "Low")


def _recommendation(key: str, status: str, knowledge: str) -> str:
    if status == "Equal":
        return "No patch required; matches the reference."
    if key in RECOMMENDATIONS:
        return RECOMMENDATIONS[key]
    for prefix, recommendation in sorted(RECOMMENDATIONS.items(), key=lambda item: -len(item[0])):
        if key.startswith(prefix + ".") or key.startswith(prefix + "["):
            return recommendation
    return knowledge or "Review this Navigator value against the selected browser profile."


def _value(flat: dict[str, Any], key: str) -> Any:
    return flat[key] if key in flat else MISSING


def _matches(reference: dict[str, Any], candidate: dict[str, Any], key: str) -> bool:
    return key in reference and key in candidate and vals_equal(reference[key], candidate[key])


def classify(
    reference: dict[str, Any],
    plain: dict[str, Any],
    patched: dict[str, Any],
) -> list[PropertyAudit]:
    keys = sorted(
        key
        for key in set(reference) | set(plain) | set(patched)
        if _navigator_key(key)
    )
    audits: list[PropertyAudit] = []
    for key in keys:
        category, knowledge_recommendation, stars = lookup_kb(key)
        reference_present = key in reference
        plain_present = key in plain
        patched_present = key in patched
        plain_match = _matches(reference, plain, key)
        patched_match = _matches(reference, patched, key)
        missing_in = tuple(
            name
            for name, present in (
                ("reference", reference_present),
                ("plain", plain_present),
                ("patched", patched_present),
            )
            if not present
        )

        if reference_present and not patched_present:
            status = "Missing"
        elif not reference_present:
            status = "Still Different"
        elif patched_match and not plain_match:
            status = "Improved"
        elif plain_match and not patched_match:
            status = "Regression"
        elif patched_match:
            status = "Equal"
        else:
            status = "Still Different"

        audits.append(
            PropertyAudit(
                key=key,
                category="Navigator" if key.startswith("navigator.") else category,
                reference=_value(reference, key),
                plain=_value(plain, key),
                patched=_value(patched, key),
                status=status,
                severity=_severity(stars, status),
                recommendation=_recommendation(key, status, knowledge_recommendation),
                missing_in=missing_in,
            )
        )
    return audits


def _counts(audits: list[PropertyAudit]) -> dict[str, int]:
    return {status.lower().replace(" ", "_"): sum(item.status == status for item in audits)
            for status in STATUS_ORDER}


def _top(audits: list[PropertyAudit], statuses: set[str], limit: int = 20) -> list[dict[str, Any]]:
    selected = [item for item in audits if item.status in statuses]
    selected.sort(key=lambda item: (-SEVERITY_RANK[item.severity], item.key))
    return [item.to_dict() for item in selected[:limit]]


def build_audit(
    root: Path,
    reference_path: Path,
    plain_path: Path,
    patched_path: Path,
) -> dict[str, Any]:
    reference = _surface_values(_fingerprint(reference_path))
    plain = _surface_values(_fingerprint(plain_path))
    patched = _surface_values(_fingerprint(patched_path))
    audits = classify(reference, plain, patched)
    counts = _counts(audits)
    total = len(audits)
    initially_different = sum(
        not _matches(reference, plain, item.key) for item in audits if item.key in reference
    )
    matched_after = counts["improved"] + counts["equal"]
    success_rate = (matched_after / total * 100.0) if total else 100.0
    repair_rate = (counts["improved"] / initially_different * 100.0) if initially_different else 100.0
    remaining = {"Still Different", "Regression", "Missing"}

    input_metadata = {
        "reference": _metadata(reference_path),
        "plain": _metadata(plain_path),
        "patched": _metadata(patched_path),
    }
    warnings: list[str] = []
    if input_metadata["patched"].get("stealth") == "stealth/generated/patches_init.js":
        warnings.append(
            "Patched input metadata identifies generated patches only; it does not prove "
            "that the Navigator module was applied."
        )

    return {
        "experiment": "Experiment 002 - Navigator Audit",
        "generated_at": now_iso(),
        "inputs": {
            "reference": relative_path(reference_path, root),
            "plain": relative_path(plain_path, root),
            "patched": relative_path(patched_path, root),
            "metadata": input_metadata,
        },
        "warnings": warnings,
        "summary": {
            "navigator_key_count": total,
            "improved_count": counts["improved"],
            "still_different_count": counts["still_different"],
            "regression_count": counts["regression"],
            "missing_count": counts["missing"],
            "equal_count": counts["equal"],
            "initially_different_count": initially_different,
            "navigator_success_rate": round(success_rate, 2),
            "repair_rate_of_initial_differences": round(repair_rate, 2),
            "critical_remaining": sum(
                item.status in remaining and item.severity == "Critical" for item in audits
            ),
        },
        "groups": {
            status: [item.key for item in audits if item.status == status]
            for status in STATUS_ORDER
        },
        "top_20_still_different": _top(audits, remaining),
        "top_regression": _top(audits, {"Regression"}),
        "top_improvement": _top(audits, {"Improved"}),
        "properties": [item.to_dict() for item in audits],
    }


def _display(value: Any, limit: int = 100) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_markdown(audit: dict[str, Any]) -> str:
    summary = audit["summary"]
    properties = audit["properties"]
    lines = [
        "# Experiment 002 — Navigator Audit",
        "",
        f"Reference: `{audit['inputs']['reference']}`  ",
        f"Plain: `{audit['inputs']['plain']}`  ",
        f"Patched: `{audit['inputs']['patched']}`",
        "",
    ]
    if audit.get("warnings"):
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in audit["warnings"])
        lines.append("")
    lines.extend([
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Jumlah key Navigator | {summary['navigator_key_count']} |",
        f"| Navigator Success Rate | {summary['navigator_success_rate']:.2f}% |",
        f"| Repair Rate (initial differences) | {summary['repair_rate_of_initial_differences']:.2f}% |",
        f"| Critical Remaining | {summary['critical_remaining']} |",
        f"| Regression Count | {summary['regression_count']} |",
        f"| Improvement Count | {summary['improved_count']} |",
        f"| Still Different | {summary['still_different_count']} |",
        f"| Missing | {summary['missing_count']} |",
        f"| Equal | {summary['equal_count']} |",
        "",
        "## Property Audit",
        "",
        "| Property | Plain | Patched | Reference | Status | Severity | Recommendation |",
        "|---|---|---|---|---|---|---|",
    ])
    for item in properties:
        lines.append(
            f"| `{item['property']}` | {_display(item['plain_value'])} | "
            f"{_display(item['patched_value'])} | {_display(item['reference_value'])} | "
            f"{item['status']} | {item['severity']} | {item['recommendation']} |"
        )

    def section(title: str, key: str) -> None:
        lines.extend(["", f"## {title}", ""])
        items = audit[key]
        if not items:
            lines.append("- None")
            return
        lines.extend(
            f"- `{item['property']}` ({item['severity']}): {item['recommendation']}"
            for item in items
        )

    section("Top 20 Properties Still Different", "top_20_still_different")
    section("Top Regression", "top_regression")
    section("Top Improvement", "top_improvement")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Navigator properties against a real-browser baseline.")
    parser.add_argument("--reference", type=Path, default=None,
                        help="Reference fingerprint (default: reports/fingerprint/fingerprint_real.json)")
    parser.add_argument("--plain", type=Path, default=None,
                        help="Plain Playwright fingerprint (default: reports/fingerprint/fingerprint_playwright.json)")
    parser.add_argument("--patched", type=Path, default=None,
                        help="Patched fingerprint (default: reports/fingerprint/fingerprint_playwright_patched.json)")
    parser.add_argument("--reports-dir", type=Path, default=None,
                        help="Experiment reports root (default: reports/experiments)")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    configure_console_error_handling()
    root = project_root()
    reference = (args.reference or root / "reports/fingerprint/fingerprint_real.json").resolve()
    plain = (args.plain or root / "reports/fingerprint/fingerprint_playwright.json").resolve()
    patched = (args.patched or root / "reports/fingerprint/fingerprint_playwright_patched.json").resolve()
    reports_dir = args.reports_dir or root / "reports/experiments"
    if not reports_dir.is_absolute():
        reports_dir = root / reports_dir
    for path in (reference, plain, patched):
        if not path.is_file():
            raise FileNotFoundError(f"Fingerprint not found: {path}")

    experiment = Experiment.create(reports_dir.resolve())
    audit = build_audit(root, reference, plain, patched)
    audit["experiment_id"] = experiment.experiment_id
    experiment.write_json("navigator_audit.json", audit)
    experiment.write_text("navigator_audit.md", render_markdown(audit))

    summary = audit["summary"]
    print(f"Experiment {experiment.experiment_id} - Navigator Audit")
    print(f"Navigator keys : {summary['navigator_key_count']}")
    print(f"Improved      : {summary['improved_count']}")
    print(f"Still different: {summary['still_different_count']}")
    print(f"Regression    : {summary['regression_count']}")
    print(f"Missing       : {summary['missing_count']}")
    print(f"Equal         : {summary['equal_count']}")
    print(f"Success rate  : {summary['navigator_success_rate']:.2f}%")
    print(f"Output        : {experiment.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
