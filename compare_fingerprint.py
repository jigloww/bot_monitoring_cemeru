"""
compare_fingerprint.py — Production-grade fingerprint comparator.

Compares two JSON files produced by fingerprint_dump.py.
Outputs: category summary → detailed diffs → priority patch list.

Usage:
    python compare_fingerprint.py fingerprint_real.json fingerprint_playwright.json
    python compare_fingerprint.py A.json B.json --show-equal --only navigator webgl
    python compare_fingerprint.py A.json B.json --output report.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ══════════════════════════════════════════════════════════════════
# KNOWN FIELD KNOWLEDGE BASE
# Maps flattened dot-notation key → (category, recommendation, cf_stars 1-5)
# ══════════════════════════════════════════════════════════════════

_KNOWN: dict[str, tuple[str, str, int]] = {
    # ── Navigator ────────────────────────────────────────────────
    "navigator.webdriver":           ("Navigator", "Patch navigator.webdriver to return false (stealth already does this, verify it works)", 5),
    "navigator.userAgentData":       ("Navigator", "Provide realistic userAgentData via Playwright context userAgent + navigator.userAgentData override", 5),
    "navigator.hardwareConcurrency": ("Navigator", "Set hardwareConcurrency to match real machine (e.g. 8 or 16)", 4),
    "navigator.deviceMemory":        ("Navigator", "Set deviceMemory to realistic value (e.g. 8)", 4),
    "navigator.platform":            ("Navigator", "Ensure platform matches UA string (Win32 for Windows UA)", 4),
    "navigator.vendor":              ("Navigator", "Should be 'Google Inc.' for Chrome", 4),
    "navigator.pdfViewerEnabled":    ("Navigator", "Set pdfViewerEnabled to true (false in headless)", 3),
    "navigator.languages":           ("Navigator", "Override languages to realistic array e.g. ['id-ID','id','en']", 3),
    "navigator.language":            ("Navigator", "Set language to match locale config", 3),
    "navigator.oscpu":               ("Navigator", "Should be undefined in Chrome (only Firefox sets this)", 2),
    "navigator.doNotTrack":          ("Navigator", "Typically null in real Chrome", 2),
    "navigator.connection":          ("Navigator", "navigator.connection differs; minor signal", 2),
    "navigator.onLine":              ("Navigator", "Should be true", 2),
    "navigator.cookieEnabled":       ("Navigator", "Should be true", 2),
    "navigator.media_devices":       ("Navigator", "Real browser enumerates real devices; Playwright returns empty/generic list", 3),

    # ── Plugins ──────────────────────────────────────────────────
    "plugins.plugin_count":          ("Plugins", "Real Chrome has 2+ plugins (PDF, Chrome PDF Viewer). Playwright headless has 0.", 4),
    "plugins.mime_count":            ("Plugins", "Override MimeTypes to match real browser", 3),

    # ── Window ───────────────────────────────────────────────────
    "window.outerWidth":             ("Window", "outerWidth is 0 in headless. Override to match innerWidth or realistic value.", 4),
    "window.outerHeight":            ("Window", "outerHeight is 0 in headless. Override to match innerHeight or realistic value.", 4),
    "window.devicePixelRatio":       ("Window", "Should be 1.0 or 2.0, matching the configured viewport", 2),

    # ── Screen ───────────────────────────────────────────────────
    "screen.availWidth":             ("Screen", "In headless, screen.availWidth may equal width or be 0", 2),
    "screen.availHeight":            ("Screen", "In headless, screen.availHeight may be wrong", 2),

    # ── WebGL ────────────────────────────────────────────────────
    "webgl.unmasked_renderer":       ("WebGL", "Playwright uses SwiftShader (software renderer). Override WEBGL_debug_renderer_info or use GPU passthrough.", 5),
    "webgl.unmasked_vendor":         ("WebGL", "Should show Intel/AMD/NVIDIA vendor, not Google.", 5),
    "webgl.renderer":                ("WebGL", "WebGL renderer string leaks software rendering", 5),
    "webgl.vendor":                  ("WebGL", "WebGL vendor string leaks software rendering", 4),
    "webgl.extension_count":         ("WebGL", "Extension count differs between real GPU and SwiftShader", 3),
    "webgl.max_texture_size":        ("WebGL", "Max texture size differs between real GPU and SwiftShader", 2),

    # ── Canvas ───────────────────────────────────────────────────
    "canvas.hash":                   ("Canvas", "Canvas fingerprint differs due to different GPU/font rendering. Very hard to spoof exactly.", 4),
    "canvas.length":                 ("Canvas", "Canvas data URL length correlates with rendering backend", 3),

    # ── Audio ─────────────────────────────────────────────────────
    "audio.sample_sum":              ("Audio", "AudioContext fingerprint differs between environments. Consider patching OfflineAudioContext.", 4),
    "audio.samples_4500_4520":       ("Audio", "Audio sample values differ per environment", 4),

    # ── Fonts ─────────────────────────────────────────────────────
    "fonts.count":                   ("Fonts", "Playwright has fewer fonts installed. Install common Windows fonts or override font detection.", 4),
    "fonts.detected":                ("Fonts", "Match detected font list to real browser environment", 3),

    # ── Chrome Object ─────────────────────────────────────────────
    "chrome.present":                ("Chrome", "window.chrome must be present. Stealth should provide this.", 5),
    "chrome.runtime.present":        ("Chrome", "chrome.runtime must be present with realistic properties.", 5),
    "chrome.loadTimes.present":      ("Chrome", "chrome.loadTimes() must be a callable function.", 5),
    "chrome.loadTimes.value":        ("Chrome", "chrome.loadTimes() return values must be realistic", 4),
    "chrome.csi.present":            ("Chrome", "chrome.csi() must be a callable function.", 5),
    "chrome.csi.value":              ("Chrome", "chrome.csi() return values must be realistic", 4),
    "chrome.runtime.has_connect":    ("Chrome", "chrome.runtime.connect must be a function", 4),
    "chrome.keys":                   ("Chrome", "window.chrome keys should match real Chrome", 3),

    # ── Permissions ───────────────────────────────────────────────
    "permissions.notifications":     ("Permissions", "Notification permission state differs (default vs denied)", 3),
    "permissions.clipboard-read":    ("Permissions", "Clipboard permission state differs", 2),
    "permissions.geolocation":       ("Permissions", "Geolocation permission state differs", 2),

    # ── Performance ───────────────────────────────────────────────
    "performance.memory":            ("Performance", "performance.memory is only available in Chrome; verify it is present", 3),
    "performance.navigation_timing": ("Performance", "Navigation timing values will differ naturally; low CF signal", 1),

    # ── Speech ────────────────────────────────────────────────────
    "speech.count":                  ("Speech", "Playwright has 0 speech synthesis voices. Real Chrome has many.", 3),

    # ── Storage ───────────────────────────────────────────────────
    "storage.localStorage_length":   ("Storage", "Different storage contents — low CF signal", 1),
    "storage.sessionStorage_length": ("Storage", "Different storage contents — low CF signal", 1),

    # ── Battery ───────────────────────────────────────────────────
    "battery.charging":              ("Battery", "Battery API may not be available in headless; low CF signal", 2),

    # ── RTC ───────────────────────────────────────────────────────
    "rtc.RTCPeerConnection":         ("RTC", "RTCPeerConnection should be present", 2),

    # ── Features ──────────────────────────────────────────────────
    "features.SharedArrayBuffer":    ("Features", "SharedArrayBuffer availability differs; medium CF signal", 2),
    "features.notification_permission": ("Features", "Notification permission state differs", 2),
}

# Category display order for summary
_CATEGORY_ORDER = [
    "Navigator", "WebGL", "Canvas", "Audio", "Chrome",
    "Plugins", "Fonts", "Window", "Screen", "Permissions",
    "Speech", "Performance", "Storage", "Battery", "RTC", "Features",
]


# ══════════════════════════════════════════════════════════════════
# FLATTEN
# ══════════════════════════════════════════════════════════════════

def flatten(obj, prefix: str = "") -> dict:
    """Recursively flatten a nested dict/list to dot-notation keys."""
    out: dict = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            out.update(flatten(v, key))
    elif isinstance(obj, list):
        if not obj:
            out[prefix] = "[]"
        elif all(not isinstance(e, (dict, list)) for e in obj):
            out[prefix] = obj          # leaf list — compare as-is
        else:
            for i, item in enumerate(obj):
                out.update(flatten(item, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


# ══════════════════════════════════════════════════════════════════
# COMPARISON HELPERS
# ══════════════════════════════════════════════════════════════════

def vals_equal(a, b) -> bool:
    """Equality check with float tolerance and type coercion."""
    if a == b:
        return True
    # int vs float
    try:
        fa, fb = float(a), float(b)  # type: ignore[arg-type]
        if fa == 0 and fb == 0:
            return True
        return abs(fa - fb) / max(abs(fa), abs(fb), 1e-12) < 1e-9
    except (TypeError, ValueError):
        pass
    return False


def fmt_val(v, max_len: int = 200) -> str:
    """Format a value for display."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, float):
        return f"{v:.8g}"
    if isinstance(v, list):
        s = json.dumps(v, ensure_ascii=False)
        return s if len(s) <= max_len else s[:max_len] + f"  ... ({len(v)} items)"
    s = str(v)
    return s if len(s) <= max_len else s[:max_len] + "..."


# ══════════════════════════════════════════════════════════════════
# LOAD
# ══════════════════════════════════════════════════════════════════

def load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] File not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    return data.get("fingerprint", data)


# ══════════════════════════════════════════════════════════════════
# REPORT ENGINE
# ══════════════════════════════════════════════════════════════════

def compare_all(
    flat1: dict, flat2: dict, label1: str, label2: str,
    show_equal: bool, only_prefixes: list[str],
) -> list[dict]:
    """
    Compare all keys. Return list of result dicts:
        { key, equal, v1, v2, category, recommendation, stars }
    """
    all_keys = sorted(set(flat1) | set(flat2))
    if only_prefixes:
        all_keys = [k for k in all_keys if any(k.startswith(p) for p in only_prefixes)]

    results = []
    for key in all_keys:
        v1    = flat1.get(key, "<missing>")
        v2    = flat2.get(key, "<missing>")
        equal = vals_equal(v1, v2)

        if equal and not show_equal:
            continue

        # Look up knowledge base
        kb = _KNOWN.get(key, None)
        if kb is None:
            # Try partial match on known keys
            for k in _KNOWN:
                if key.startswith(k) or k.startswith(key.split("[")[0]):
                    kb = _KNOWN[k]
                    break

        category     = kb[0] if kb else "Other"
        rec          = kb[1] if kb else ""
        stars        = kb[2] if kb else 1

        results.append(dict(
            key=key, equal=equal, v1=v1, v2=v2,
            category=category, recommendation=rec, stars=stars,
        ))
    return results


def print_summary(results: list[dict], label1: str, label2: str, sink) -> None:
    """Print per-category diff counts."""
    from collections import defaultdict
    by_cat: dict[str, dict] = defaultdict(lambda: {"total": 0, "diff": 0})

    for r in results:
        c = r["category"]
        by_cat[c]["total"] += 1
        if not r["equal"]:
            by_cat[c]["diff"] += 1

    # Unify order
    cats = list(_CATEGORY_ORDER) + sorted(c for c in by_cat if c not in _CATEGORY_ORDER)

    sink("═" * 56)
    sink("  FINGERPRINT COMPARISON REPORT")
    sink(f"  File 1 : {label1}")
    sink(f"  File 2 : {label2}")
    sink("═" * 56)
    sink("")
    sink("  SUMMARY BY CATEGORY")
    sink("  " + "─" * 40)

    for cat in cats:
        if cat not in by_cat:
            continue
        info   = by_cat[cat]
        diff   = info["diff"]
        status = f"✗  {diff} diff(s)" if diff else "✓"
        sink(f"  {cat:<20}  {status}")

    diffs = sum(1 for r in results if not r["equal"])
    same  = len(results) - diffs
    sink("")
    sink(f"  Total compared : {len(results)}")
    sink(f"  ✓ Same         : {same}")
    sink(f"  ✗ Different    : {diffs}")
    sink("═" * 56)
    sink("")


def print_details(results: list[dict], label1: str, label2: str, sink) -> None:
    """Print detailed per-field diff output grouped by category."""
    from collections import defaultdict

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)

    cats = list(_CATEGORY_ORDER) + sorted(c for c in by_cat if c not in _CATEGORY_ORDER)

    for cat in cats:
        if cat not in by_cat:
            continue
        items = by_cat[cat]
        diffs = [r for r in items if not r["equal"]]
        same  = [r for r in items if  r["equal"]]

        if not diffs and not same:
            continue

        sink(f"\n{'─'*56}")
        sink(f"  {cat.upper()}")
        sink(f"{'─'*56}\n")

        for r in diffs:
            sink(f"  ✗  {r['key']}")
            sink("")
            sink(f"     {label1}:")
            sink(f"     {fmt_val(r['v1'])}")
            sink("")
            sink(f"     {label2}:")
            sink(f"     {fmt_val(r['v2'])}")
            if r["recommendation"]:
                sink("")
                sink(f"     ⚑  {r['recommendation']}")
            sink("")
            sink("  " + "·" * 50)
            sink("")

        for r in same:
            sink(f"  ✓  {r['key']}")
            sink(f"     {fmt_val(r['v1'])}")
            sink("")


def print_priority_patches(results: list[dict], sink) -> None:
    """Print PRIORITY PATCHES section ranked by CF likelihood."""
    diffs = [r for r in results if not r["equal"] and r["recommendation"]]
    diffs.sort(key=lambda r: (-r["stars"], r["key"]))

    sink("")
    sink("═" * 56)
    sink("  PRIORITY PATCHES")
    sink("  (ranked by Cloudflare detection likelihood)")
    sink("═" * 56)
    sink("")

    seen = set()
    for r in diffs:
        key = r["key"]
        if key in seen:
            continue
        seen.add(key)

        stars_str = "★" * r["stars"] + "☆" * (5 - r["stars"])
        sink(f"  {stars_str}")
        sink(f"  {key}")
        sink(f"  ↳ {r['recommendation']}")
        sink("")

    if not seen:
        sink("  No diffs with known recommendations found.")
    sink("═" * 56)


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compare two browser fingerprint JSON files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python compare_fingerprint.py fingerprint_real.json fingerprint_playwright.json
  python compare_fingerprint.py A.json B.json --show-equal --output report.txt
  python compare_fingerprint.py A.json B.json --only navigator webgl chrome
""",
    )
    p.add_argument("file1",           help="First fingerprint JSON  (e.g. fingerprint_real.json)")
    p.add_argument("file2",           help="Second fingerprint JSON (e.g. fingerprint_playwright.json)")
    p.add_argument("--label1",        default="", help="Label for file1 (default: filename stem)")
    p.add_argument("--label2",        default="", help="Label for file2 (default: filename stem)")
    p.add_argument("--show-equal",    action="store_true", help="Also show identical fields")
    p.add_argument("--only",          nargs="+", default=[], metavar="PREFIX", help="Only compare fields with these key prefixes")
    p.add_argument("--output", "-o",  default="", help="Save report to this text file")
    p.add_argument("--no-priority",   action="store_true", help="Skip priority patches section")
    return p


def main() -> int:
    args   = build_parser().parse_args()
    label1 = args.label1 or Path(args.file1).stem
    label2 = args.label2 or Path(args.file2).stem

    fp1 = load(args.file1)
    fp2 = load(args.file2)

    flat1 = flatten(fp1)
    flat2 = flatten(fp2)

    results = compare_all(flat1, flat2, label1, label2, args.show_equal, args.only)

    lines: list[str] = []
    def sink(line: str = "") -> None:
        lines.append(line)
        print(line)

    print_summary(results, label1, label2, sink)
    print_details(results, label1, label2, sink)

    if not args.no_priority:
        print_priority_patches(results, sink)

    if args.output:
        Path(args.output).write_text("\n".join(lines), encoding="utf-8")
        print(f"\n[OK] Report saved to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
