"""Experiment 003: explain remaining Navigator-module fingerprint gaps.

This experiment consumes immutable Experiment 001 artifacts. It does not run a
browser, edit a stealth module, or generate a patch. The plain fingerprint is
used only to distinguish a module regression from a gap that already existed
before the Navigator module was applied.
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
from experiments.navigator_audit import _fingerprint, _surface_values
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    relative_path,
    write_json_exclusive,
    write_text_exclusive,
    read_json,
)
from tools.compare_fingerprint import lookup_kb, vals_equal


MISSING = "<missing>"
SEVERITY_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
CONFIDENCE_RANK = {"High": 3, "Medium": 2, "Low": 1}
STATUSES = ("Equal", "Remaining Difference", "Regression", "Unexpected Difference")

TARGET_PREFIXES = (
    "navigator.webdriver",
    "navigator.languages",
    "navigator.language",
    "navigator.platform",
    "navigator.vendor",
    "navigator.deviceMemory",
    "navigator.hardwareConcurrency",
    "navigator.userAgentData",
    "navigator.plugins",
    "navigator.mimeTypes",
    "navigator.pdfViewerEnabled",
    "navigator.maxTouchPoints",
    "navigator.cookieEnabled",
    "navigator.onLine",
    "navigator.doNotTrack",
    "plugins.plugin_count",
    "plugins.mime_count",
)

CAUSES = (
    "Wrong descriptor",
    "Wrong prototype",
    "Missing getter",
    "Wrong enumerable",
    "Wrong configurable",
    "Wrong object shape",
    "Wrong array order",
    "Wrong native function",
    "Wrong instance type",
    "Cross-property inconsistency",
    "Environment dependent",
    "Dynamic value",
    "Unknown",
)


@dataclass(frozen=True)
class Gap:
    property: str
    reference: Any
    navigator: Any
    plain: Any
    status: str
    severity: str
    reason: str
    possible_cause: str
    recommended_fix: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "property": self.property,
            "reference_value": self.reference,
            "navigator_value": self.navigator,
            "plain_value": self.plain,
            "status": self.status,
            "severity": self.severity,
            "reason": self.reason,
            "possible_cause": self.possible_cause,
            "recommended_fix": self.recommended_fix,
            "confidence": self.confidence,
        }


def _document_metadata(path: Path) -> dict[str, Any]:
    raw = read_json(path)
    metadata = raw.get("_meta", {}) if isinstance(raw, dict) else {}
    return metadata if isinstance(metadata, dict) else {}


def _is_module_target(key: str) -> bool:
    return any(key == prefix or key.startswith(prefix + ".") or key.startswith(prefix + "[")
               for prefix in TARGET_PREFIXES)


def _is_navigator_surface(key: str) -> bool:
    return key.startswith("navigator.") or key.startswith("plugins.")


def _present(values: dict[str, Any], key: str) -> bool:
    return key in values


def _value(values: dict[str, Any], key: str) -> Any:
    return values[key] if key in values else MISSING


def _equal(reference: dict[str, Any], candidate: dict[str, Any], key: str) -> bool:
    return key in reference and key in candidate and vals_equal(reference[key], candidate[key])


def _severity(key: str, status: str) -> str:
    _category, _recommendation, stars = lookup_kb(key)
    if status == "Equal":
        return "Low"
    return {5: "Critical", 4: "High", 3: "Medium"}.get(stars, "Low")


def _shape(value: Any) -> str:
    if value == MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _same_members_different_order(reference: Any, candidate: Any) -> bool:
    if not isinstance(reference, list) or not isinstance(candidate, list):
        return False
    if len(reference) != len(candidate):
        return False
    try:
        return reference != candidate and sorted(map(str, reference)) == sorted(map(str, candidate))
    except (TypeError, ValueError):
        return False


def _cause(key: str, reference: Any, navigator: Any, plain: Any, status: str) -> tuple[str, str]:
    if status == "Equal":
        return "Unknown", "No gap remains; no root-cause investigation is required."
    if navigator == MISSING:
        return "Missing getter", "Expose the property on Navigator.prototype with its native accessor shape."
    if _shape(reference) != _shape(navigator):
        return "Wrong object shape", "Preserve the reference value's object/array/scalar shape and own members."
    if key.endswith("prototype_keys") or key.endswith(".keys"):
        return "Wrong prototype", "Compare the Navigator prototype chain and enumerable own-key surface."
    if _same_members_different_order(reference, navigator):
        return "Wrong array order", "Keep the same array members and order as the reference profile."
    if key.endswith("userAgent") or key.endswith("appVersion"):
        return "Cross-property inconsistency", "Align UA, platform, vendor, and UA-CH as one browser profile."
    if key.startswith("navigator.userAgentData"):
        return "Cross-property inconsistency", "Keep UA-CH brands, platform, mobile, and high-entropy values coherent."
    if key in {"navigator.platform", "navigator.vendor", "navigator.language", "navigator.languages"}:
        return "Cross-property inconsistency", "Derive this value from the same locale, OS, and browser profile."
    if key in {"navigator.deviceMemory", "navigator.hardwareConcurrency", "navigator.maxTouchPoints"}:
        return "Environment dependent", "Use a profile bucket matched to the browser/OS environment; avoid per-run values."
    if key.startswith("navigator.connection"):
        return "Dynamic value", "Do not hardcode network telemetry; collect or model it consistently for the environment."
    if key.startswith("plugins.") or "plugins" in key or "mime" in key.lower():
        return "Wrong instance type", "Preserve PluginArray/MimeTypeArray prototypes, relationships, and collection shape."
    if key.endswith("webdriver"):
        return "Missing getter", "Expose the expected Navigator.prototype getter with a native-looking callable."
    if status == "Regression":
        return "Cross-property inconsistency", "Re-check module precedence and ensure the patch does not alter a matching value."
    return "Unknown", "Inspect the property descriptor, prototype, and browser-context inputs before changing the module."


def _reason(status: str, reference: Any, navigator: Any, plain: Any) -> str:
    if status == "Equal":
        return "Navigator value matches the reference."
    if status == "Regression":
        return "Plain matched the reference, but the Navigator module changed this property away from it."
    if status == "Unexpected Difference":
        return "The module changed or exposed a difference outside its declared Navigator target surface."
    if navigator == MISSING:
        return "Navigator artifact is missing a value present in the reference."
    if plain == MISSING:
        return "Navigator supplied a value that was absent in Plain, but it still does not match the reference."
    return "Navigator value remains different from the reference after the module was applied."


def _status(key: str, reference: dict[str, Any], plain: dict[str, Any], navigator: dict[str, Any]) -> str:
    navigator_match = _equal(reference, navigator, key)
    plain_match = _equal(reference, plain, key)
    if navigator_match:
        return "Equal"
    if plain_match:
        return "Regression"
    if key not in reference or key not in navigator:
        return "Remaining Difference"
    if _present(plain, key) != _present(navigator, key) and not _is_module_target(key):
        return "Unexpected Difference"
    if _present(plain, key) != _present(navigator, key) and key.startswith("navigator."):
        return "Remaining Difference"
    return "Remaining Difference" if _is_module_target(key) else "Unexpected Difference"


def _confidence(status: str, cause: str, key: str, reference: Any, navigator: Any) -> str:
    if status == "Equal":
        return "High"
    if cause in {"Missing getter", "Wrong object shape", "Wrong array order", "Wrong prototype"}:
        return "High"
    if cause in {"Dynamic value", "Environment dependent", "Cross-property inconsistency"}:
        return "Medium"
    if key.startswith("navigator.userAgentData") or key.startswith("plugins."):
        return "Medium"
    return "Low"


def classify(reference: dict[str, Any], plain: dict[str, Any], navigator: dict[str, Any]) -> list[Gap]:
    # Empty plain collections are encoded as "[]" by the shared flattener,
    # while a non-empty Navigator collection is represented by its leaves.
    # Do not report a parent collection as missing when neither reference nor
    # Navigator has that flattened parent key.
    keys = sorted(
        key for key in set(reference) | set(plain) | set(navigator)
        if _is_navigator_surface(key) and (key in reference or key in navigator)
    )
    gaps: list[Gap] = []
    for key in keys:
        status = _status(key, reference, plain, navigator)
        reference_value = _value(reference, key)
        navigator_value = _value(navigator, key)
        plain_value = _value(plain, key)
        cause, fix = _cause(key, reference_value, navigator_value, plain_value, status)
        gaps.append(
            Gap(
                property=key,
                reference=reference_value,
                navigator=navigator_value,
                plain=plain_value,
                status=status,
                severity=_severity(key, status),
                reason=_reason(status, reference_value, navigator_value, plain_value),
                possible_cause=cause if cause in CAUSES else "Unknown",
                recommended_fix=fix,
                confidence=_confidence(status, cause, key, reference_value, navigator_value),
            )
        )
    return gaps


def _top(gaps: list[Gap], *, limit: int, highest_impact: bool) -> list[dict[str, Any]]:
    candidates = [gap for gap in gaps if gap.status != "Equal"]
    if highest_impact:
        candidates.sort(key=lambda gap: (-SEVERITY_RANK[gap.severity], -CONFIDENCE_RANK[gap.confidence], gap.property))
    else:
        easy_causes = {"Missing getter", "Wrong array order", "Wrong enumerable", "Wrong configurable"}
        candidates.sort(key=lambda gap: (0 if gap.possible_cause in easy_causes else 1,
                                         SEVERITY_RANK[gap.severity], gap.property))
    return [gap.to_dict() for gap in candidates[:limit]]


def build_analysis(root: Path, reference_path: Path, plain_path: Path, navigator_path: Path) -> dict[str, Any]:
    reference = _surface_values(_fingerprint(reference_path))
    plain = _surface_values(_fingerprint(plain_path))
    navigator = _surface_values(_fingerprint(navigator_path))
    gaps = classify(reference, plain, navigator)
    counts = {status.lower().replace(" ", "_"): sum(gap.status == status for gap in gaps)
              for status in STATUSES}
    remaining = [gap for gap in gaps if gap.status != "Equal"]
    equal_count = counts["equal"]
    success = equal_count / len(gaps) * 100.0 if gaps else 100.0
    severity_remaining = {
        severity.lower(): sum(gap.status != "Equal" and gap.severity == severity for gap in gaps)
        for severity in ("Critical", "High", "Medium", "Low")
    }
    return {
        "experiment": "Experiment 003 - Navigator Gap Analysis",
        "generated_at": now_iso(),
        "inputs": {
            "reference": relative_path(reference_path, root),
            "plain_context": relative_path(plain_path, root),
            "navigator_module": relative_path(navigator_path, root),
            "metadata": {
                "reference": _document_metadata(reference_path),
                "plain_context": _document_metadata(plain_path),
                "navigator_module": _document_metadata(navigator_path),
            },
        },
        "summary": {
            "navigator_property_count": len(gaps),
            "equal_count": equal_count,
            "remaining_difference_count": counts["remaining_difference"],
            "regression_count": counts["regression"],
            "unexpected_difference_count": counts["unexpected_difference"],
            "navigator_success_pct": round(success, 2),
            "remaining_critical": severity_remaining["critical"],
            "remaining_high": severity_remaining["high"],
            "remaining_medium": severity_remaining["medium"],
            "remaining_low": severity_remaining["low"],
        },
        "top_10_easiest_fixes": _top(gaps, limit=10, highest_impact=False),
        "top_10_highest_impact_fixes": _top(gaps, limit=10, highest_impact=True),
        "properties": [gap.to_dict() for gap in gaps],
    }


def _display(value: Any, limit: int = 90) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_markdown(analysis: dict[str, Any]) -> str:
    summary = analysis["summary"]
    lines = [
        "# Experiment 003 — Navigator Gap Analysis",
        "",
        f"Reference: `{analysis['inputs']['reference']}`  ",
        f"Navigator Module: `{analysis['inputs']['navigator_module']}`  ",
        f"Plain Context: `{analysis['inputs']['plain_context']}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Navigator Success % | {summary['navigator_success_pct']:.2f}% |",
        f"| Navigator Properties | {summary['navigator_property_count']} |",
        f"| Equal | {summary['equal_count']} |",
        f"| Remaining Difference | {summary['remaining_difference_count']} |",
        f"| Regression | {summary['regression_count']} |",
        f"| Unexpected Difference | {summary['unexpected_difference_count']} |",
        f"| Remaining Critical | {summary['remaining_critical']} |",
        f"| Remaining High | {summary['remaining_high']} |",
        f"| Remaining Medium | {summary['remaining_medium']} |",
        f"| Remaining Low | {summary['remaining_low']} |",
        "",
        "## Property Analysis",
        "",
        "| Property | Reference | Navigator | Severity | Reason | Possible Cause | Recommended Fix | Confidence |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in analysis["properties"]:
        lines.append(
            f"| `{item['property']}` | {_display(item['reference_value'])} | "
            f"{_display(item['navigator_value'])} | {item['severity']} | "
            f"{item['reason']} | {item['possible_cause']} | "
            f"{item['recommended_fix']} | {item['confidence']} |"
        )

    def section(title: str, key: str) -> None:
        lines.extend(["", f"## {title}", ""])
        items = analysis[key]
        if not items:
            lines.append("- None")
            return
        lines.extend(
            f"- `{item['property']}` ({item['severity']}, {item['possible_cause']}): "
            f"{item['recommended_fix']}"
            for item in items
        )

    section("Top 10 Easiest Fixes", "top_10_easiest_fixes")
    section("Top 10 Highest Impact Fixes", "top_10_highest_impact_fixes")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze remaining Navigator module gaps from Experiment 001 artifacts.")
    parser.add_argument("--reference", type=Path, default=None)
    parser.add_argument("--plain", type=Path, default=None)
    parser.add_argument("--navigator", type=Path, default=None,
                        help="Full Navigator artifact (default: exp_001/navigator/fingerprint.json)")
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    configure_console_error_handling()
    root = project_root()
    reference = (args.reference or root / "reports/fingerprint/fingerprint_real.json").resolve()
    plain = (args.plain or root / "reports/experiments/exp_001/plain/fingerprint.json").resolve()
    navigator = (args.navigator or root / "reports/experiments/exp_001/navigator/fingerprint.json").resolve()
    reports_dir = args.reports_dir or root / "reports/experiments"
    if not reports_dir.is_absolute():
        reports_dir = root / reports_dir
    for path in (reference, plain, navigator):
        if not path.is_file():
            raise FileNotFoundError(f"Navigator gap input not found: {path}")

    experiment = Experiment.create(reports_dir.resolve())
    analysis = build_analysis(root, reference, plain, navigator)
    analysis["experiment_id"] = experiment.experiment_id
    experiment.write_json("navigator_gap_analysis.json", analysis)
    experiment.write_text("navigator_gap_analysis.md", render_markdown(analysis))

    summary = analysis["summary"]
    print(f"Experiment {experiment.experiment_id} - Navigator Gap Analysis")
    print(f"Navigator properties : {summary['navigator_property_count']}")
    print(f"Success             : {summary['navigator_success_pct']:.2f}%")
    print(f"Equal               : {summary['equal_count']}")
    print(f"Remaining           : {summary['remaining_difference_count']}")
    print(f"Regression          : {summary['regression_count']}")
    print(f"Unexpected          : {summary['unexpected_difference_count']}")
    print(f"Output              : {experiment.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
