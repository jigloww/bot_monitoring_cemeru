"""
tools/patch_generator.py — Generate evidence-based Playwright patches from fingerprint diffs.

Reads a diff JSON (from compare_fingerprint.py) or two fingerprint files.
Generates ONLY patches for confirmed differences — no guessing.

Output files (written to the same directory as --output):
    patches.py        — Python Playwright init_script code
    patches_init.js   — JavaScript to inject via add_init_script
    patches.md        — Markdown explanation
    patches.json      — Machine-readable patch list

Usage:
    python tools/patch_generator.py --diff compare_diff.json --output reports/patches/patches.json
    python tools/patch_generator.py --ref fingerprint_real.json --test fingerprint_playwright.json --output patches.json
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools._shared import ensure_output_dir, load_json, save_json, save_text, setup_logging
from tools.compare_fingerprint import flatten, compare_flat, CATEGORY_ORDER

log = setup_logging("patch_generator")


# ══════════════════════════════════════════════════════════════════
# PATCH KNOWLEDGE BASE
# key → generator function (ref_value, test_value) → (py_code, js_code, description)
# ══════════════════════════════════════════════════════════════════

def _patch_webdriver(ref, test) -> tuple[str, str, str]:
    return (
        "# navigator.webdriver\npage.add_init_script(\"Object.defineProperty(navigator,'webdriver',{get:()=>false})\");",
        "Object.defineProperty(navigator,'webdriver',{get:()=>false,configurable:true});",
        "Override navigator.webdriver to return false.",
    )

def _patch_hardware_concurrency(ref, test) -> tuple[str, str, str]:
    val = ref if isinstance(ref, int) and ref > 0 else 8
    return (
        f"page.add_init_script(\"Object.defineProperty(navigator,'hardwareConcurrency',{{get:()=>{val}}})\");",
        f"Object.defineProperty(navigator,'hardwareConcurrency',{{get:()=>{val},configurable:true}});",
        f"Set navigator.hardwareConcurrency to {val} (matches real machine).",
    )

def _patch_device_memory(ref, test) -> tuple[str, str, str]:
    val = ref if isinstance(ref, (int, float)) and ref > 0 else 8
    return (
        f"page.add_init_script(\"Object.defineProperty(navigator,'deviceMemory',{{get:()=>{val}}})\");",
        f"Object.defineProperty(navigator,'deviceMemory',{{get:()=>{val},configurable:true}});",
        f"Set navigator.deviceMemory to {val}.",
    )

def _patch_pdf_viewer(ref, test) -> tuple[str, str, str]:
    return (
        "page.add_init_script(\"Object.defineProperty(navigator,'pdfViewerEnabled',{get:()=>true})\");",
        "Object.defineProperty(navigator,'pdfViewerEnabled',{get:()=>true,configurable:true});",
        "Set navigator.pdfViewerEnabled to true (false in headless).",
    )

def _patch_outer_width(ref, test) -> tuple[str, str, str]:
    val = ref if isinstance(ref, int) and ref > 0 else 1366
    return (
        f"page.add_init_script(\"Object.defineProperty(window,'outerWidth',{{get:()=>{val}}})\");",
        f"Object.defineProperty(window,'outerWidth',{{get:()=>{val},configurable:true}});",
        f"Set window.outerWidth to {val} (0 in headless).",
    )

def _patch_outer_height(ref, test) -> tuple[str, str, str]:
    val = ref if isinstance(ref, int) and ref > 0 else 768
    return (
        f"page.add_init_script(\"Object.defineProperty(window,'outerHeight',{{get:()=>{val}}})\");",
        f"Object.defineProperty(window,'outerHeight',{{get:()=>{val},configurable:true}});",
        f"Set window.outerHeight to {val} (0 in headless).",
    )

def _patch_languages(ref, test) -> tuple[str, str, str]:
    if isinstance(ref, list):
        val_js = repr(ref).replace("'", '"')
    else:
        val_js = '["id-ID","id","en-US","en"]'
    return (
        f"page.add_init_script(\"Object.defineProperty(navigator,'languages',{{get:()=>{val_js}}})\");",
        f"Object.defineProperty(navigator,'languages',{{get:()=>{val_js},configurable:true}});",
        f"Override navigator.languages to match real browser: {val_js}.",
    )

def _patch_chrome_object(ref, test) -> tuple[str, str, str]:
    js = """if(!window.chrome){window.chrome={runtime:{},loadTimes:function(){return{requestTime:performance.timeOrigin/1000,startLoadTime:performance.timeOrigin/1000,commitLoadTime:performance.timeOrigin/1000,finishDocumentLoadTime:0,finishLoadTime:0,firstPaintTime:0,firstPaintAfterLoadTime:0,navigationType:'Other',wasFetchedViaSpdy:false,wasNpnNegotiated:false,npnNegotiatedProtocol:'',wasAlternateProtocolAvailable:false,connectionInfo:'h2'};},csi:function(){return{startE:performance.timeOrigin,onloadT:performance.timeOrigin+50,pageT:50,tran:15};},app:{isInstalled:false}}}"""
    return (
        f"page.add_init_script(\"\"\"{js}\"\"\");",
        js,
        "Create window.chrome object with runtime, loadTimes(), csi() if missing.",
    )

PATCH_GENERATORS: dict[str, Any] = {
    "navigator.webdriver":           _patch_webdriver,
    "navigator.hardwareConcurrency": _patch_hardware_concurrency,
    "navigator.deviceMemory":        _patch_device_memory,
    "navigator.pdfViewerEnabled":    _patch_pdf_viewer,
    "window.outerWidth":             _patch_outer_width,
    "window.outerHeight":            _patch_outer_height,
    "navigator.languages":           _patch_languages,
    "chrome.present":                _patch_chrome_object,
    "chrome.runtime.present":        _patch_chrome_object,
    "chrome.loadTimes.present":      _patch_chrome_object,
    "chrome.csi.present":            _patch_chrome_object,
}


# ══════════════════════════════════════════════════════════════════
# GENERATE
# ══════════════════════════════════════════════════════════════════

def generate_patches(diffs: list[dict]) -> list[dict]:
    """Generate patch entries from a list of diff records."""
    patches: list[dict] = []
    seen_generators: set[str] = set()

    for diff in sorted(diffs, key=lambda d: -d.get("stars", 1)):
        key = diff["key"]
        gen = PATCH_GENERATORS.get(key)
        if not gen:
            continue
        gen_id = gen.__name__
        if gen_id in seen_generators:
            continue          # Avoid duplicate patches for related keys
        seen_generators.add(gen_id)

        try:
            py_code, js_code, desc = gen(diff.get("v1"), diff.get("v2"))
            patches.append({
                "key":         key,
                "category":    diff.get("category", "?"),
                "stars":       diff.get("stars", 1),
                "description": desc,
                "python_code": py_code,
                "js_code":     js_code,
            })
        except Exception as e:
            log.warning("Patch generation failed for %s: %s", key, e)

    return patches


def render_python(patches: list[dict]) -> str:
    lines = [
        '"""',
        "Auto-generated Playwright patches by patch_generator.py",
        "Apply these BEFORE navigating to the target URL.",
        '"""',
        "from playwright.sync_api import Page",
        "",
        "",
        "def apply_patches(page: Page) -> None:",
        '    """Apply all evidence-based browser fingerprint patches."""',
        "",
    ]
    for p in patches:
        lines.append(f"    # ── {p['category']}: {p['description']}")
        for line in p["python_code"].splitlines():
            lines.append(f"    {line}")
        lines.append("")
    return "\n".join(lines)


def render_js(patches: list[dict]) -> str:
    lines = [
        "// Auto-generated browser fingerprint init script",
        "// Source: patch_generator.py",
        "// Add via: page.add_init_script(script=this_file)",
        "(() => {",
        "  'use strict';",
        "",
    ]
    for p in patches:
        lines.append(f"  // ── {p['category']}: {p['description']}")
        lines.append(f"  try {{")
        for line in p["js_code"].splitlines():
            lines.append(f"    {line}")
        lines.append(f"  }} catch(e) {{ console.warn('patch failed: {p['key']}', e); }}")
        lines.append("")
    lines += ["})();"]
    return "\n".join(lines)


def render_markdown(patches: list[dict], ref_label: str, test_label: str) -> str:
    stars_s = lambda n: "★"*n+"☆"*(5-n)
    md = [
        "# Evidence-Based Playwright Patches",
        "",
        f"Generated from comparison: **{ref_label}** vs **{test_label}**",
        "",
        f"Total patches: **{len(patches)}**",
        "",
        "---",
        "",
    ]
    for p in patches:
        md += [
            f"## {p['category']}: `{p['key']}`",
            "",
            f"**Priority**: {stars_s(p['stars'])}",
            "",
            f"**Description**: {p['description']}",
            "",
            "**Python (Playwright)**:",
            "```python",
            p["python_code"],
            "```",
            "",
            "**JavaScript (init script)**:",
            "```javascript",
            p["js_code"],
            "```",
            "",
            "---",
            "",
        ]
    md += ["## Usage", "",
           "```python", "from patches import apply_patches",
           "", "with sync_playwright() as pw:",
           "    browser = pw.chromium.launch(channel='chrome')",
           "    page = browser.new_page()",
           "    apply_patches(page)   # ← call before goto()",
           "    page.goto('https://target.com')",
           "```"]
    return "\n".join(md)


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate evidence-based Playwright patches from fingerprint diffs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/patch_generator.py --diff compare_diff.json --output reports/patches/patches.json
  python tools/patch_generator.py --ref fingerprint_real.json --test fingerprint_playwright.json --output patches.json
"""
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--diff", help="Diff JSON from compare_fingerprint.py (with .json extension)")
    g.add_argument("--ref",  help="Reference fingerprint JSON (use with --test)")
    p.add_argument("--test", help="Test fingerprint JSON (required when --ref is used)")
    add_output_arg(p, default="")  # e.g. --output reports/patches/patches.json
    return p


def main() -> int:
    args = build_parser().parse_args()
    out  = Path(args.output).parent if args.output else ensure_output_dir()

    if args.diff:
        diff_data  = load_json(Path(args.diff))
        diffs      = diff_data.get("diffs", [])
        ref_label  = diff_data.get("label1", "ref")
        test_label = diff_data.get("label2", "test")
    else:
        if not args.test:
            print("--test required when using --ref", file=sys.stderr); return 1
        raw_ref  = load_json(Path(args.ref))
        raw_test = load_json(Path(args.test))
        fp_ref   = raw_ref.get("fingerprint",  raw_ref)
        fp_test  = raw_test.get("fingerprint", raw_test)
        records  = compare_flat(flatten(fp_ref), flatten(fp_test), show_equal=False, only=[])
        diffs    = [{"key":r.key,"v1":r.v1,"v2":r.v2,"category":r.category,"stars":r.stars}
                    for r in records if not r.equal]
        ref_label  = Path(args.ref).stem
        test_label = Path(args.test).stem

    log.info("Diffs to process: %d", len(diffs))
    patches = generate_patches(diffs)
    log.info("Patches generated: %d", len(patches))

    if not patches:
        log.warning("No patches generated — no known keys matched in diff.")
        return 0

    # Save Python
    py_path = out / "patches.py"
    save_text(render_python(patches), py_path)
    log.info("Python patches → %s", py_path)

    # Save JS init script
    js_path = out / "patches_init.js"
    save_text(render_js(patches), js_path)
    log.info("JS init script → %s", js_path)

    # Save Markdown
    md_path = out / "patches.md"
    save_text(render_markdown(patches, ref_label, test_label), md_path)
    log.info("Markdown       → %s", md_path)

    # Save JSON
    save_json({"patches": patches, "ref": ref_label, "test": test_label}, out / "patches.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
