"""
tools/compare_fingerprint.py — Recursive fingerprint comparison with multi-format export.

Input:  two JSON files from fingerprint_dump.py
Output: summary, diffs with recommendations, priority patches
Format: determined by --output file extension (.json .txt .md .html)

Usage:
    python tools/compare_fingerprint.py fingerprint_real.json fingerprint_playwright.json
    python tools/compare_fingerprint.py A.json B.json --output reports/comparison/comparison.json
    python tools/compare_fingerprint.py A.json B.json --output comparison.html
    python tools/compare_fingerprint.py A.json B.json --output comparison.md
    python tools/compare_fingerprint.py A.json B.json --only navigator webgl chrome
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools._shared import (
    ensure_output_dir,
    save_json,
    setup_logging,
    add_output_arg
)

log = setup_logging("compare_fingerprint")

# ── Knowledge base: key → (category, recommendation, cf_stars) ───
KB: dict[str, tuple[str, str, int]] = {
    "navigator.webdriver":           ("Navigator", "Override navigator.webdriver → false", 5),
    "navigator.userAgentData":       ("Navigator", "Provide realistic high-entropy userAgentData", 5),
    "navigator.hardwareConcurrency": ("Navigator", "Set to realistic value (e.g. 8)", 4),
    "navigator.deviceMemory":        ("Navigator", "Set deviceMemory=8", 4),
    "navigator.platform":            ("Navigator", "Set platform=Win32 to match UA", 4),
    "navigator.vendor":              ("Navigator", "Must be 'Google Inc.'", 4),
    "navigator.pdfViewerEnabled":    ("Navigator", "Set pdfViewerEnabled=true (false in headless)", 3),
    "navigator.languages":           ("Navigator", "Override languages array", 3),
    "plugins.plugin_count":          ("Plugins",   "Headless returns 0. Real Chrome has 2+.", 4),
    "plugins.mime_count":            ("Plugins",   "Override MimeTypes", 3),
    "window.outerWidth":             ("Window",    "outerWidth=0 in headless — set equal to innerWidth", 4),
    "window.outerHeight":            ("Window",    "outerHeight=0 in headless — set equal to innerHeight", 4),
    "webgl.unmasked_renderer":       ("WebGL",     "Playwright uses SwiftShader. Use GPU passthrough.", 5),
    "webgl.unmasked_vendor":         ("WebGL",     "Must show Intel/AMD/NVIDIA, not Google", 5),
    "webgl.renderer":                ("WebGL",     "WebGL renderer leaks software backend", 4),
    "webgl.extension_count":         ("WebGL",     "Extension count differs between GPU and SwiftShader", 3),
    "canvas.hash":                   ("Canvas",    "Canvas fingerprint differs due to GPU rendering", 4),
    "audio.sample_sum":              ("Audio",     "AudioContext fingerprint differs per environment", 4),
    "fonts.count":                   ("Fonts",     "Fewer fonts in server environments", 4),
    "chrome.present":                ("Chrome",    "window.chrome must exist", 5),
    "chrome.runtime.present":        ("Chrome",    "chrome.runtime must exist with realistic props", 5),
    "chrome.loadTimes.present":      ("Chrome",    "chrome.loadTimes() must be callable", 5),
    "chrome.csi.present":            ("Chrome",    "chrome.csi() must be callable", 5),
    "chrome.loadTimes.value":        ("Chrome",    "loadTimes() values must be realistic", 4),
    "chrome.csi.value":              ("Chrome",    "csi() values must be realistic", 4),
    "permissions.notifications":     ("Permissions", "Notification permission state differs", 3),
    "speech.count":                  ("Speech",    "Playwright has 0 voices. Real Chrome has many.", 3),
    "performance.memory":            ("Performance","performance.memory must exist in Chrome", 3),
    "battery.charging":              ("Battery",   "Battery API may be absent in headless", 2),
    "rtc.RTCPeerConnection":         ("RTC",       "RTCPeerConnection must be defined", 2),
    "features.SharedArrayBuffer":    ("Features",  "SharedArrayBuffer availability may differ", 2),
}

CATEGORY_ORDER = [
    "Navigator","WebGL","Canvas","Audio","Chrome","Plugins","Fonts",
    "Window","Screen","Permissions","Speech","Performance","Storage",
    "Battery","RTC","Features","Other",
]


@dataclass
class DiffRecord:
    key: str; equal: bool; v1: Any; v2: Any
    category: str = "Other"; recommendation: str = ""; stars: int = 1
    missing_in: str = ""


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list):
        if not obj:
            out[prefix] = "[]"
        elif all(not isinstance(e, (dict, list)) for e in obj):
            out[prefix] = obj
        else:
            for i, item in enumerate(obj):
                out.update(flatten(item, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def vals_equal(a: Any, b: Any) -> bool:
    if a == b: return True
    try:
        fa, fb = float(a), float(b)  # type: ignore[arg-type]
        return abs(fa - fb) / max(abs(fa), abs(fb), 1e-12) < 1e-9
    except (TypeError, ValueError):
        return False


def lookup_kb(key: str) -> tuple[str, str, int]:
    if key in KB: return KB[key]
    for k, v in KB.items():
        if key.startswith(k + ".") or key.startswith(k + "["):
            return v
    return ("Other", "", 1)


def compare_flat(flat1: dict, flat2: dict, show_equal: bool, only: list[str]) -> list[DiffRecord]:
    keys = sorted(set(flat1) | set(flat2))
    if only:
        keys = [k for k in keys if any(k.startswith(p) for p in only)]
    records: list[DiffRecord] = []
    for key in keys:
        v1, v2 = flat1.get(key, "<missing>"), flat2.get(key, "<missing>")
        eq = (key in flat1) and (key in flat2) and vals_equal(v1, v2)
        if eq and not show_equal: continue
        cat, rec, stars = lookup_kb(key)
        missing = "file2" if key in flat1 and key not in flat2 else ("file1" if key not in flat1 else "")
        records.append(DiffRecord(key=key, equal=eq, v1=v1, v2=v2, category=cat, recommendation=rec, stars=stars, missing_in=missing))
    return records


def fv(v: Any, max_len: int = 100) -> str:
    if v is None: return "null"
    if v == "<missing>": return "<missing>"
    if isinstance(v, bool): return str(v).lower()
    if isinstance(v, float): return f"{v:.8g}"
    if isinstance(v, list):
        s = json.dumps(v, ensure_ascii=False)
        return s if len(s) <= max_len else s[:max_len] + f" …({len(v)} items)"
    s = str(v)
    return s if len(s) <= max_len else s[:max_len] + "…"

def stars_str(n: int) -> str:
    return "★" * n + "☆" * (5 - n)


def render_text(records: list[DiffRecord], label1: str, label2: str) -> str:
    W = 56
    lines: list[str] = []
    by_cat: dict[str, dict] = defaultdict(lambda: {"total": 0, "diff": 0})
    for r in records:
        by_cat[r.category]["total"] += 1
        if not r.equal: by_cat[r.category]["diff"] += 1

    lines += ["═"*W, "  FINGERPRINT COMPARISON REPORT",
               f"  File 1 : {label1}", f"  File 2 : {label2}", "═"*W, "", "  SUMMARY", "  "+"─"*40]
    for cat in CATEGORY_ORDER:
        if cat not in by_cat: continue
        d = by_cat[cat]["diff"]
        lines.append(f"  {cat:<22}  {'✗ '+str(d)+' diff(s)' if d else '✓'}")
    td = sum(1 for r in records if not r.equal)
    lines += ["", f"  Total: {len(records)}  Same: {len(records)-td}  Diff: {td}", "═"*W, ""]

    grouped: dict[str, list[DiffRecord]] = defaultdict(list)
    for r in records: grouped[r.category].append(r)
    for cat in CATEGORY_ORDER + sorted(c for c in grouped if c not in CATEGORY_ORDER):
        if cat not in grouped: continue
        diffs = [r for r in grouped[cat] if not r.equal]
        same  = [r for r in grouped[cat] if r.equal]
        if not diffs and not same: continue
        lines += ["", "─"*W, f"  {cat.upper()}", "─"*W, ""]
        for r in diffs:
            lines.append(f"  ✗  {r.key}")
            if r.missing_in:
                lines.append(f"     (missing in {r.missing_in})")
            else:
                lines += [f"     {label1}: {fv(r.v1)}", f"     {label2}: {fv(r.v2)}"]
            if r.recommendation:
                lines += [f"     ⚑  {r.recommendation}", f"     {stars_str(r.stars)}"]
            lines += ["", "  "+"·"*46, ""]
        for r in same:
            lines.append(f"  ✓  {r.key}  →  {fv(r.v1)}")

    lines += ["", "═"*W, "  PRIORITY PATCHES", "═"*W, ""]
    seen: set[str] = set()
    for r in sorted([r for r in records if not r.equal and r.recommendation], key=lambda r: (-r.stars, r.key)):
        if r.key in seen: continue
        seen.add(r.key)
        lines += [f"  {stars_str(r.stars)}  {r.key}", f"  ↳ {r.recommendation}", ""]
    lines.append("═"*W)
    return "\n".join(lines)


def render_markdown(records: list[DiffRecord], label1: str, label2: str) -> str:
    md = [f"# Fingerprint Comparison: {label1} vs {label2}", ""]
    by_cat: dict[str, dict] = defaultdict(lambda: {"d": 0, "t": 0})
    for r in records:
        by_cat[r.category]["t"] += 1
        if not r.equal: by_cat[r.category]["d"] += 1
    md += ["## Summary", "", "| Category | Diffs | Total |", "|---|---|---|"]
    for cat in CATEGORY_ORDER:
        if cat in by_cat: md.append(f"| {cat} | {by_cat[cat]['d']} | {by_cat[cat]['t']} |")
    md += ["", "## Differences", ""]
    grouped: dict[str, list[DiffRecord]] = defaultdict(list)
    for r in records:
        if not r.equal: grouped[r.category].append(r)
    for cat in CATEGORY_ORDER + sorted(c for c in grouped if c not in CATEGORY_ORDER):
        if cat not in grouped: continue
        md += [f"### {cat}", ""]
        for r in grouped[cat]:
            md += [f"#### `{r.key}`", "",
                   f"- **{label1}**: `{fv(r.v1)}`", f"- **{label2}**: `{fv(r.v2)}`"]
            if r.recommendation:
                md += [f"- **Recommendation**: {r.recommendation}", f"- **Priority**: {stars_str(r.stars)}"]
            md.append("")
    md += ["## Priority Patches", ""]
    seen: set[str] = set()
    for r in sorted([r for r in records if not r.equal and r.recommendation], key=lambda r: (-r.stars, r.key)):
        if r.key in seen: continue
        seen.add(r.key)
        md += [f"**{stars_str(r.stars)}** `{r.key}`", f"> {r.recommendation}", ""]
    return "\n".join(md)


def render_html(records: list[DiffRecord], label1: str, label2: str) -> str:
    body = render_text(records, label1, label2).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>Fingerprint Comparison</title>'
            f'<style>body{{font-family:monospace;background:#111;color:#eee;padding:2rem;line-height:1.5}}'
            f'pre{{white-space:pre-wrap;word-break:break-all}}</style></head><body><pre>{body}</pre></body></html>')


def _detect_format(path: str) -> str:
    """Detect output format from file extension."""
    return {".json": "json", ".md": "markdown", ".html": "html", ".txt": "text"}.get(
        Path(path).suffix.lower(), "text"
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description="Compare two browser fingerprint JSON files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Formats (determined by --output extension):
  .json   → JSON diff export
  .txt    → plain text report
  .md     → Markdown report
  .html   → HTML report

Examples:
  python tools/compare_fingerprint.py real.json playwright.json --output reports/comparison.json
  python tools/compare_fingerprint.py real.json playwright.json --output comparison.html
  python tools/compare_fingerprint.py real.json playwright.json  # text to stdout only
"""
    )
    p.add_argument("file1")
    p.add_argument("file2")
    p.add_argument("--label1",     default="")
    p.add_argument("--label2",     default="")
    p.add_argument("--show-equal", action="store_true")
    p.add_argument("--only",       nargs="+", default=[], metavar="PREFIX")
    add_output_arg(p, default="")  # extension determines format
    args   = p.parse_args()
    label1 = args.label1 or Path(args.file1).stem
    label2 = args.label2 or Path(args.file2).stem

    raw1   = load_json(Path(args.file1)); raw2 = load_json(Path(args.file2))
    fp1    = raw1.get("fingerprint", raw1); fp2 = raw2.get("fingerprint", raw2)
    records = compare_flat(flatten(fp1), flatten(fp2), args.show_equal, args.only)
    text    = render_text(records, label1, label2)
    print(text)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fmt = _detect_format(args.output)
        if fmt == "json":
            save_json({"label1": label1, "label2": label2,
                       "diffs": [{"key": r.key, "v1": r.v1, "v2": r.v2,
                                  "category": r.category, "recommendation": r.recommendation,
                                  "stars": r.stars}
                                 for r in records if not r.equal]}, out_path)
        elif fmt == "markdown":
            save_text(render_markdown(records, label1, label2), out_path)
        elif fmt == "html":
            save_text(render_html(records, label1, label2), out_path)
        else:  # txt / default
            save_text(text, out_path)
        log.info("→ %s  (format: %s)", out_path, fmt)
    return 0

if __name__ == "__main__":
    sys.exit(main())
