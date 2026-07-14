"""
tools/patch_generator.py — Automatic rule-based Playwright patch generator.

Reads fingerprint diffs, auto-classifies every property, generates patches.

Outputs:
    reports/patches/patch_report.json   — full analysis report
    reports/patches/patch_report.md     — markdown summary
    stealth/generated/patches_init.js   — JS init script for Playwright
    stealth/generated/patches.py        — Python wrapper
    stealth/generated/patches.json      — machine-readable patch list

Usage:
    python tools/patch_generator.py --diff comparison.json
    python tools/patch_generator.py --ref fingerprint_real.json --test fingerprint_playwright.json
    python tools/patch_generator.py --diff diff.json --output reports/patches/patch_report.json
"""
from __future__ import annotations
import argparse, json, sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools._shared import load_json, save_json, save_text, setup_logging
from tools.compare_fingerprint import flatten, compare_flat

log = setup_logging("patch_generator")

# ══════════════════════════════════════════════════════════════════
# ENUMS
# ══════════════════════════════════════════════════════════════════

class PatchType(str, Enum):
    STATIC_PROPERTY  = "STATIC_PROPERTY"    # Object.defineProperty — auto-generated
    FUNCTION         = "FUNCTION"           # callable — needs function spoofing
    READONLY_OBJECT  = "READONLY_OBJECT"    # complex object — needs dedicated module
    DYNAMIC_PROPERTY = "DYNAMIC_PROPERTY"   # runtime value — SKIPPED
    UNPATCHABLE      = "UNPATCHABLE"        # cannot patch


@dataclass
class PatchEntry:
    key:         str
    patch_type:  PatchType
    reason:      str
    namespace:   str          = ""
    property:    str          = ""
    ref_value:   Any          = None
    js_code:     str          = ""
    py_code:     str          = ""
    stars:        int          = 1   # CF risk priority (from KB if available)


# ══════════════════════════════════════════════════════════════════
# CLASSIFICATION RULES  (data-driven, no per-property hardcoding)
# ══════════════════════════════════════════════════════════════════

# Objects whose direct properties can be patched with Object.defineProperty
PATCHABLE_OBJECTS: frozenset[str] = frozenset({
    "navigator", "window", "screen", "document", "history", "location",
})

# Key prefixes → DYNAMIC_PROPERTY (skip)
_DYN_PREFIXES: tuple[str, ...] = (
    "audio.", "canvas.", "webgl.", "webgl2.",
    "performance.",
    "chrome.loadTimes", "chrome.csi",
    "battery.", "speech.", "fonts.",
    "window_keys", "navigator_keys", "navigator_own_keys",
    "navigator.keys", "navigator.prototype_keys",
    "media_devices", "media_capabilities",
    "indexeddb.",
    "document.cookie_names", "document.cookie_count",
    "document.readyState", "document.visibilityState",
    "document.title", "document.referrer", "document.domain",
    "history.", "location.",
    "navigator.javaEnabled", "navigator.media_devices",
    "navigator.keyboard_available", "navigator.bluetooth_available",
)

_DYN_EXACT: frozenset[str] = frozenset({
    "window_keys", "navigator_keys", "navigator_own_keys",
    "performance", "battery", "speech", "history", "location",
})

# Key prefixes → READONLY_OBJECT (complex, needs dedicated module)
_RO_PREFIXES: tuple[str, ...] = (
    "navigator.userAgentData", "navigator.connection",
    "screen.orientation",
    "permissions.", "timezone.", "intl.",
    "features.", "rtc.", "hardware_apis.", "css.", "gpu.", "storage.",
    "document.characterSet", "document.compatMode",
    "navigator.languages[",  # individual language array elements
)

# Top-level namespaces that are entirely UNPATCHABLE via Object.defineProperty
_UNPATCHABLE_NS: frozenset[str] = frozenset({
    "plugins", "webgl", "webgl2", "canvas", "audio", "fonts",
    "battery", "speech", "rtc", "performance", "intl", "timezone",
    "features", "hardware_apis", "css", "gpu", "storage",
    "permissions", "media_devices", "media_capabilities",
    "indexeddb", "window_keys", "navigator_keys", "navigator_own_keys",
})

# Chrome sub-keys that are functions
_CHROME_FUNCTIONS: frozenset[str] = frozenset({
    "chrome.loadTimes", "chrome.csi",
})

# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _is_primitive_list(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(e, (str, int, float, bool, type(None))) for e in v)


def render_js_value(v: Any) -> str:
    """Render a Python value as a JavaScript literal."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(str(v))


def _parse_key(key: str) -> tuple[str, str, int]:
    """Returns (namespace, property, depth)."""
    parts = key.split(".")
    return parts[0], parts[1] if len(parts) > 1 else "", len(parts)


# ══════════════════════════════════════════════════════════════════
# CLASSIFY
# ══════════════════════════════════════════════════════════════════

def classify_property(key: str, v1: Any, v2: Any) -> tuple[PatchType, str]:
    """Classify a diff entry into a PatchType. Returns (type, reason)."""

    # Missing value in one fingerprint
    if v1 == "<missing>" or v2 == "<missing>":
        return PatchType.UNPATCHABLE, "Value missing in one fingerprint"

    # Array elements from flatten() — patch the parent list instead
    if "[" in key:
        return PatchType.UNPATCHABLE, "Array element — patch parent property instead"

    ns, prop, depth = _parse_key(key)

    # ── Chrome namespace (check BEFORE dynamic patterns) ──────────
    # chrome.loadTimes and chrome.csi are in _DYN_PREFIXES, so check
    # chrome namespace first to return FUNCTION, not DYNAMIC_PROPERTY.
    if ns == "chrome":
        for fn_key in _CHROME_FUNCTIONS:
            if key == fn_key or key.startswith(fn_key + "."):
                return PatchType.FUNCTION, "Chrome function — requires function spoofing"
        if depth <= 2:
            return PatchType.READONLY_OBJECT, "Chrome object — use stealth/modules/chrome.js"
        return PatchType.READONLY_OBJECT, "Chrome sub-property — use stealth/modules/chrome.js"

    # ── Dynamic runtime values ────────────────────────────────────
    if key in _DYN_EXACT:
        return PatchType.DYNAMIC_PROPERTY, "Runtime dynamic value"
    for p in _DYN_PREFIXES:
        if key.startswith(p):
            return PatchType.DYNAMIC_PROPERTY, "Runtime dynamic value"

    # ── Readonly / complex objects ────────────────────────────────
    for p in _RO_PREFIXES:
        if key.startswith(p):
            return PatchType.READONLY_OBJECT, "Complex object — requires dedicated stealth module"

    # ── Simple patchable objects (navigator, window, screen …) ───
    if ns in PATCHABLE_OBJECTS and depth == 2:
        if v1 is None or isinstance(v1, (str, int, float, bool)):
            return PatchType.STATIC_PROPERTY, "Simple property — Object.defineProperty auto-generated"
        if _is_primitive_list(v1):
            return PatchType.STATIC_PROPERTY, "Primitive array — Object.defineProperty auto-generated"
        if isinstance(v1, list):
            return PatchType.READONLY_OBJECT, "Complex array — requires proxy hook"
        if isinstance(v1, dict):
            return PatchType.READONLY_OBJECT, "Object value — requires dedicated module"

    # ── Deep paths on patchable objects ──────────────────────────
    if ns in PATCHABLE_OBJECTS and depth > 2:
        return PatchType.READONLY_OBJECT, "Deep property — patch via parent object"

    # ── Unknown namespaces ────────────────────────────────────────
    if ns in _UNPATCHABLE_NS:
        return PatchType.UNPATCHABLE, f"Namespace '{ns}' not directly patchable"
    return PatchType.UNPATCHABLE, f"Unrecognised namespace '{ns}'"



def can_patch(patch_type: PatchType) -> bool:
    return patch_type == PatchType.STATIC_PROPERTY


# ══════════════════════════════════════════════════════════════════
# BUILD SINGLE PATCH
# ══════════════════════════════════════════════════════════════════

def build_patch(key: str, v1: Any, v2: Any, stars: int = 1) -> PatchEntry:
    """Build a PatchEntry for one diff key."""
    ptype, reason = classify_property(key, v1, v2)
    ns, prop, _   = _parse_key(key)

    entry = PatchEntry(
        key=key, patch_type=ptype, reason=reason,
        namespace=ns, property=prop, ref_value=v1, stars=stars,
    )

    if ptype == PatchType.STATIC_PROPERTY:
        js_val       = render_js_value(v1)
        entry.js_code = (
            f'Object.defineProperty({ns},"{prop}",'
            f'{{get:()=>{js_val},configurable:true}});'
        )
        entry.py_code = (
            f'page.add_init_script('
            f'"Object.defineProperty({ns},\\"{prop}\\",'
            f'{{get:()=>{js_val},configurable:true}});");'
        )
    return entry


# ══════════════════════════════════════════════════════════════════
# BATCH BUILD
# ══════════════════════════════════════════════════════════════════

def build_all_patches(diffs: list[dict]) -> list[PatchEntry]:
    """Build PatchEntry list from a list of diff records."""
    return [build_patch(d["key"], d.get("v1"), d.get("v2"), d.get("stars", 1)) for d in diffs]


# ══════════════════════════════════════════════════════════════════
# RENDER STATISTICS
# ══════════════════════════════════════════════════════════════════

def render_statistics(entries: list[PatchEntry]) -> dict:
    counts: dict[str, int] = {t.value: 0 for t in PatchType}
    for e in entries:
        counts[e.patch_type.value] += 1
    auto = counts[PatchType.STATIC_PROPERTY.value]
    return {
        "total_diffs":          len(entries),
        "auto_patchable":       auto,
        "function_patch":       counts[PatchType.FUNCTION.value],
        "dynamic_skipped":      counts[PatchType.DYNAMIC_PROPERTY.value],
        "readonly_object":      counts[PatchType.READONLY_OBJECT.value],
        "unpatchable":          counts[PatchType.UNPATCHABLE.value],
        "patch_coverage_pct":   round(auto / len(entries) * 100, 1) if entries else 0,
    }


# ══════════════════════════════════════════════════════════════════
# RENDER JS
# ══════════════════════════════════════════════════════════════════

def render_js(entries: list[PatchEntry]) -> str:
    patchable = [e for e in entries if e.patch_type == PatchType.STATIC_PROPERTY]
    by_ns: dict[str, list[PatchEntry]] = {}
    for e in sorted(patchable, key=lambda x: (x.namespace, x.property)):
        by_ns.setdefault(e.namespace, []).append(e)

    lines = [
        "// stealth/generated/patches_init.js",
        "// Auto-generated by tools/patch_generator.py — DO NOT EDIT",
        f"// Generated: {datetime.now().isoformat()}",
        f"// Auto patches: {len(patchable)}",
        "(() => {",
        "  'use strict';",
        "  const _p = (obj, prop, val) => {",
        "    try { Object.defineProperty(obj, prop, {get: ()=>val, configurable: true}); }",
        "    catch(e) { console.warn('[stealth] patch failed:', prop, e); }",
        "  };",
        "",
    ]

    for ns, items in by_ns.items():
        lines.append(f"  // ── {ns} {'─'*(48-len(ns))}")
        for e in items:
            js_val = render_js_value(e.ref_value)
            lines.append(f'  _p({ns}, "{e.property}", {js_val});')
        lines.append("")

    lines += ["})();"]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# RENDER PYTHON
# ══════════════════════════════════════════════════════════════════

def render_python(entries: list[PatchEntry]) -> str:
    patchable = [e for e in entries if e.patch_type == PatchType.STATIC_PROPERTY]
    lines = [
        '"""',
        "stealth/generated/patches.py",
        "Auto-generated by tools/patch_generator.py — DO NOT EDIT",
        f"Generated: {datetime.now().isoformat()}",
        f"Auto patches: {len(patchable)}",
        '"""',
        "from playwright.sync_api import Page",
        "",
        "",
        "def apply_patches(page: Page) -> None:",
        '    """Apply all auto-generated fingerprint patches."""',
        "",
    ]
    cur_ns = None
    for e in sorted(patchable, key=lambda x: (x.namespace, x.property)):
        if e.namespace != cur_ns:
            lines.append(f"    # ── {e.namespace}")
            cur_ns = e.namespace
        js_val = render_js_value(e.ref_value)
        js_val_esc = js_val.replace('"', '\\"').replace("'", "\\'")
        lines.append(
            f'    page.add_init_script('
            f'"Object.defineProperty({e.namespace},'
            f'\\"{e.property}\\",'
            f'{{get:()=>{js_val_esc},configurable:true}});");'
        )
    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# RENDER MARKDOWN
# ══════════════════════════════════════════════════════════════════

def render_markdown(entries: list[PatchEntry], stats: dict, ref: str, test: str) -> str:
    stars_s = lambda n: "★" * n + "☆" * (5 - n)
    md = [
        "# Patch Generator Report",
        "",
        f"- **Reference**: `{ref}`",
        f"- **Test**: `{test}`",
        f"- **Generated**: `{datetime.now().isoformat()}`",
        "",
        "## Statistics",
        "",
        f"| Metric | Count |",
        "| --- | --- |",
        f"| Total differences | {stats['total_diffs']} |",
        f"| **Auto patchable (STATIC_PROPERTY)** | **{stats['auto_patchable']}** |",
        f"| Function patch needed | {stats['function_patch']} |",
        f"| Dynamic / skipped | {stats['dynamic_skipped']} |",
        f"| Readonly object | {stats['readonly_object']} |",
        f"| Unpatchable | {stats['unpatchable']} |",
        f"| **Coverage** | **{stats['patch_coverage_pct']}%** |",
        "",
        "## Auto-Generated Patches",
        "",
    ]
    patchable = [e for e in entries if e.patch_type == PatchType.STATIC_PROPERTY]
    cur_ns = None
    for e in sorted(patchable, key=lambda x: (-x.stars, x.namespace, x.property)):
        if e.namespace != cur_ns:
            md.append(f"### {e.namespace}")
            md.append("")
            cur_ns = e.namespace
        md += [
            f"**`{e.key}`** {stars_s(e.stars)}",
            f"```javascript",
            e.js_code,
            "```",
            "",
        ]
    md += ["## Skipped / Manual Patches", "", "| Key | Type | Reason |", "| --- | --- | --- |"]
    for e in entries:
        if e.patch_type != PatchType.STATIC_PROPERTY:
            md.append(f"| `{e.key}` | {e.patch_type.value} | {e.reason} |")
    md += ["", "## Future Module Roadmap", "",
           "| Module | Status | Target |",
           "| --- | --- | --- |",
           "| `stealth/modules/chrome.js` | Placeholder | chrome.* spoofing |",
           "| `stealth/modules/navigator.js` | Active | navigator.* overrides |",
           "| `stealth/modules/window.js` | Active | window.* overrides |",
           "| `stealth/modules/screen.js` | Active | screen.* overrides |",
           "| `stealth/modules/permissions.js` | Placeholder | Permissions API spoofing |",
           "| `stealth/modules/performance.js` | Placeholder | Performance timing spoofing |",
           ""]
    return "\n".join(md)


# ══════════════════════════════════════════════════════════════════
# RENDER REPORT (JSON)
# ══════════════════════════════════════════════════════════════════

def render_report(entries: list[PatchEntry], stats: dict, meta: dict) -> dict:
    return {
        "_meta": {**meta, "generated_at": datetime.now().isoformat(),
                  "tool": "patch_generator.py"},
        "statistics": stats,
        "patches": [
            {"key": e.key, "patch_type": e.patch_type.value, "reason": e.reason,
             "namespace": e.namespace, "property": e.property,
             "ref_value": e.ref_value, "stars": e.stars,
             "js_code": e.js_code, "py_code": e.py_code}
            for e in entries
        ],
        "recommendations": _build_recommendations(entries, stats),
    }


def _build_recommendations(entries: list[PatchEntry], stats: dict) -> list[str]:
    recs = []
    if stats["auto_patchable"] > 0:
        recs.append(f"Apply {stats['auto_patchable']} auto-patches via stealth/generated/patches_init.js")
    fn = stats["function_patch"]
    if fn:
        recs.append(f"{fn} function patches need stealth/modules/chrome.js implementation")
    ro = stats["readonly_object"]
    if ro:
        recs.append(f"{ro} readonly objects need dedicated stealth modules (chrome, userAgentData, etc.)")
    recs.append("Run fingerprint_dump.py again after applying patches to measure improvement")
    recs.append("Use browser_score.py to track CF risk score reduction per iteration")
    return recs


def render_patch_summary(entries: list[PatchEntry], stats: dict) -> str:
    lines = [
        "═" * 54,
        "  PATCH GENERATOR REPORT",
        "═" * 54,
        f"  Total differences   : {stats['total_diffs']}",
        f"  Auto patchable      : {stats['auto_patchable']}",
        f"  Function patch      : {stats['function_patch']}",
        f"  Dynamic / skipped   : {stats['dynamic_skipped']}",
        f"  Readonly object     : {stats['readonly_object']}",
        f"  Unpatchable         : {stats['unpatchable']}",
        f"  Coverage            : {stats['patch_coverage_pct']}%",
        "═" * 54,
    ]
    patchable = [e for e in entries if e.patch_type == PatchType.STATIC_PROPERTY]
    if patchable:
        lines.append("  AUTO-GENERATED PATCHES")
        lines.append("  " + "─" * 40)
        for e in sorted(patchable, key=lambda x: (x.namespace, x.property)):
            lines.append(f"  ✓  {e.key}")
        lines.append("")
    skipped = [e for e in entries if e.patch_type != PatchType.STATIC_PROPERTY]
    if skipped:
        lines.append("  SKIPPED / MANUAL")
        lines.append("  " + "─" * 40)
        for e in skipped[:20]:
            lines.append(f"  ✗  [{e.patch_type.value[:3]}] {e.key}")
        if len(skipped) > 20:
            lines.append(f"  ... and {len(skipped)-20} more")
    lines.append("═" * 54)
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# SAVE OUTPUTS
# ══════════════════════════════════════════════════════════════════

def _save_reports(entries: list[PatchEntry], stats: dict, report: dict,
                  md: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    save_json(report, out_dir / "patch_report.json")
    log.info("Report JSON → %s", out_dir / "patch_report.json")
    save_text(md, out_dir / "patch_report.md")
    log.info("Report MD   → %s", out_dir / "patch_report.md")


def _save_stealth(entries: list[PatchEntry], gen_dir: Path) -> None:
    gen_dir.mkdir(parents=True, exist_ok=True)

    # patches_init.js
    save_text(render_js(entries), gen_dir / "patches_init.js")
    log.info("JS init     → %s", gen_dir / "patches_init.js")

    # patches.py
    save_text(render_python(entries), gen_dir / "patches.py")
    log.info("Python      → %s", gen_dir / "patches.py")

    # patches.json  (machine-readable list)
    patchable = [e for e in entries if e.patch_type == PatchType.STATIC_PROPERTY]
    save_json({
        "generated_at": datetime.now().isoformat(),
        "count": len(patchable),
        "patches": [{"key": e.key, "namespace": e.namespace, "property": e.property,
                     "ref_value": e.ref_value, "js_code": e.js_code, "stars": e.stars}
                    for e in sorted(patchable, key=lambda x: x.key)],
    }, gen_dir / "patches.json")
    log.info("Patches JSON→ %s", gen_dir / "patches.json")


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Automatic rule-based Playwright patch generator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/patch_generator.py --diff compare_diff.json
  python tools/patch_generator.py --ref fingerprint_real.json --test fingerprint_playwright.json
  python tools/patch_generator.py --diff diff.json --output reports/patches/patch_report.json
""",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--diff", help="Diff JSON from compare_fingerprint.py (--output *.json)")
    src.add_argument("--ref",  help="Reference (real Chrome) fingerprint JSON")
    p.add_argument("--test",   help="Test (Playwright) fingerprint JSON (required with --ref)")
    p.add_argument("--output", default="",
                   help="Primary report output path (default: reports/patches/patch_report.json)")
    p.add_argument("--report-dir", default="reports/patches",
                   help="Report directory (default: reports/patches)")
    p.add_argument("--stealth-dir", default="stealth/generated",
                   help="Stealth generated directory (default: stealth/generated)")
    return p


def main() -> int:
    args = build_parser().parse_args()
    root = Path(__file__).parent.parent

    # ── Load diffs ───────────────────────────────────────────────
    if args.diff:
        raw       = load_json(Path(args.diff))
        diffs     = raw.get("diffs", [])
        ref_label = raw.get("label1", "ref")
        tst_label = raw.get("label2", "test")
    else:
        if not args.test:
            build_parser().error("--test required when using --ref")
        raw_ref  = load_json(Path(args.ref))
        raw_test = load_json(Path(args.test))
        fp_ref   = raw_ref.get("fingerprint",  raw_ref)
        fp_test  = raw_test.get("fingerprint", raw_test)
        records  = compare_flat(flatten(fp_ref), flatten(fp_test), show_equal=False, only=[])
        diffs    = [{"key": r.key, "v1": r.v1, "v2": r.v2,
                     "category": r.category, "stars": r.stars}
                    for r in records if not r.equal]
        ref_label = Path(args.ref).stem
        tst_label = Path(args.test).stem

    log.info("Diffs loaded: %d", len(diffs))

    # ── Build patches ────────────────────────────────────────────
    entries = build_all_patches(diffs)
    stats   = render_statistics(entries)
    meta    = {"ref": ref_label, "test": tst_label}
    report  = render_report(entries, stats, meta)
    md      = render_markdown(entries, stats, ref_label, tst_label)

    # Print summary to console
    print(render_patch_summary(entries, stats))

    # ── Save reports ─────────────────────────────────────────────
    report_dir = Path(args.output).parent if args.output else root / args.report_dir
    _save_reports(entries, stats, report, md, report_dir)

    # ── Save stealth generated ───────────────────────────────────
    stealth_dir = root / args.stealth_dir
    _save_stealth(entries, stealth_dir)

    log.info("Done. Auto patches: %d / %d diffs", stats["auto_patchable"], stats["total_diffs"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
