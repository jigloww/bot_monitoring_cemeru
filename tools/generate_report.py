"""
tools/generate_report.py — Aggregate all tool outputs into one complete report.

Reads: environment.json, fingerprint.json, timeline.json, cookies_timeline.json,
       turnstile.json, response_headers.json, browser_score.json, patches.json,
       validation_report.json

Exports: full_report.html, full_report.md, full_report.txt, full_report.json

Usage:
    python tools/generate_report.py --out-dir tools/output/
    python tools/generate_report.py --out-dir tools/output/ --html --markdown
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools._shared import ensure_output_dir, save_json, save_text, setup_logging

log = setup_logging("generate_report")


def try_load(path: Path) -> Any:
    """Load JSON file; return None if missing."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def section(title: str, content: str, W: int = 58) -> str:
    border = "═" * W
    return f"\n{border}\n  {title.upper()}\n{border}\n{content}"


def fmt_dict(d: dict | None, indent: int = 2, max_keys: int = 20) -> str:
    if not d:
        return "  (no data)"
    lines = []
    for i, (k, v) in enumerate(list(d.items())[:max_keys]):
        if isinstance(v, dict):
            lines.append(f"  {k}:")
            for k2, v2 in list(v.items())[:5]:
                lines.append(f"    {k2}: {str(v2)[:80]}")
        else:
            lines.append(f"  {k}: {str(v)[:80]}")
    if len(d) > max_keys:
        lines.append(f"  … ({len(d) - max_keys} more keys)")
    return "\n".join(lines)


def build_text_report(data: dict, out_dir: Path) -> str:
    W     = 58
    now   = datetime.now().isoformat()
    lines: list[str] = []

    lines += ["=" * W,
              "  SEMERU BOT — BROWSER ANALYSIS FRAMEWORK",
              f"  Generated : {now}",
              "=" * W]

    # ── 1. Environment ──────────────────────────────────────────
    env = data.get("environment")
    if env:
        sys_info = env.get("system", {})
        chrome   = env.get("chrome", {})
        pw       = env.get("playwright", {})
        lc       = env.get("launch_config", {})
        content  = (
            f"  OS          : {sys_info.get('os','')} {sys_info.get('os_release','')}\n"
            f"  CPU cores   : {sys_info.get('cpu_count','?')}\n"
            f"  RAM         : {sys_info.get('ram_gb','?')} GB\n"
            f"  Python      : {sys_info.get('python_version','?').split()[0]}\n"
            f"  Playwright  : {pw.get('playwright_version','?')}\n"
            f"  Chrome      : {chrome.get('version','?')}\n"
            f"  Channel     : {lc.get('channel','?')}\n"
            f"  Headless    : {lc.get('headless','?')}\n"
            f"  Profile     : {lc.get('profile','?')}"
        )
        lines.append(section("1. Environment", content))
    else:
        lines.append(section("1. Environment", "  (environment.json not found — run environment_report.py)"))

    # ── 2. Fingerprint summary ──────────────────────────────────
    fp = data.get("fingerprint")
    if fp:
        f_data = fp.get("fingerprint", fp)
        nav = f_data.get("navigator", {})
        meta = fp.get("_meta", {})
        content = (
            f"  Collected   : {meta.get('collected_at','?')}\n"
            f"  URL         : {meta.get('url','?')}\n"
            f"  Channel     : {meta.get('channel','?')}\n"
            f"  Headless    : {meta.get('headless','?')}\n"
            f"  UA          : {str(nav.get('userAgent','?'))[:80]}\n"
            f"  webdriver   : {nav.get('webdriver','?')}\n"
            f"  platform    : {nav.get('platform','?')}\n"
            f"  Plugins     : {f_data.get('plugins',{}).get('plugin_count','?')}\n"
            f"  WebGL GPU   : {f_data.get('webgl',{}).get('unmasked_renderer','?')}\n"
            f"  Canvas hash : {f_data.get('canvas',{}).get('hash','?')}\n"
            f"  Audio sum   : {str(f_data.get('audio',{}).get('sample_sum','?'))[:20]}\n"
            f"  Fonts found : {f_data.get('fonts',{}).get('count','?')}\n"
            f"  chrome obj  : {f_data.get('chrome',{}).get('present','?')}"
        )
        lines.append(section("2. Fingerprint Summary", content))
    else:
        lines.append(section("2. Fingerprint Summary", "  (fingerprint.json not found — run fingerprint_dump.py)"))

    # ── 3. Browser Score ────────────────────────────────────────
    sc = data.get("score")
    if sc:
        cats = sc.get("categories", [])
        score_lines = [f"  Overall Score : {sc.get('overall_score','?')}%",
                       f"  CF Risk Score : {sc.get('cf_risk_score','?')}%",
                       ""]
        for c in cats:
            bar = "█" * int(c.get("score_pct",0)//5) + "░" * (20 - int(c.get("score_pct",0)//5))
            score_lines.append(f"  {c['category']:<20} {bar} {c.get('score_pct',0):5.1f}%")
        lines.append(section("3. Browser Score", "\n".join(score_lines)))
    else:
        lines.append(section("3. Browser Score", "  (browser_score.json not found — run browser_score.py)"))

    # ── 4. Challenge Timeline ───────────────────────────────────
    tl = data.get("timeline")
    if tl and isinstance(tl, list):
        cf_frames = [f for f in tl if f.get("cf_challenge")]
        solved    = [f for f in tl if f.get("challenge_solved")]
        content = (
            f"  Total frames  : {len(tl)}\n"
            f"  CF frames     : {len(cf_frames)}\n"
            f"  Solved        : {'YES at ' + str(solved[0].get('elapsed_ms','?')) + 'ms' if solved else 'NO'}\n"
            f"  First title   : {tl[0].get('title','?')[:60] if tl else '?'}\n"
            f"  Last title    : {tl[-1].get('title','?')[:60] if tl else '?'}"
        )
        lines.append(section("4. Challenge Timeline", content))
    else:
        lines.append(section("4. Challenge Timeline", "  (timeline.json not found — run challenge_timeline.py)"))

    # ── 5. Cookie Timeline ──────────────────────────────────────
    ck = data.get("cookies")
    if ck and isinstance(ck, list):
        cf_events = [e for e in ck if e.get("is_cf")]
        clearance = [e for e in ck if e.get("name") == "cf_clearance" and e.get("event") == "added"]
        content = (
            f"  Total events  : {len(ck)}\n"
            f"  CF events     : {len(cf_events)}\n"
            f"  cf_clearance  : {'ACQUIRED ✓' if clearance else 'NOT acquired ✗'}\n"
        )
        for e in cf_events[:5]:
            content += f"  [{e.get('elapsed_ms','?')}ms] {e.get('event','?')}: {e.get('name','?')}\n"
        lines.append(section("5. Cookie Timeline", content))
    else:
        lines.append(section("5. Cookie Timeline", "  (cookies_timeline.json not found — run cookie_timeline.py)"))

    # ── 6. Turnstile ────────────────────────────────────────────
    ts = data.get("turnstile")
    if ts:
        iframes    = ts.get("iframes", [])
        containers = ts.get("containers", [])
        cf_iframes = [f for f in iframes if f.get("is_cf")]
        content = (
            f"  Turnstile script  : {ts.get('ts_script') or 'NOT FOUND'}\n"
            f"  CF iframes        : {len(cf_iframes)}\n"
            f"  Widget containers : {len(containers)}\n"
            f"  Hidden inputs     : {len(ts.get('hidden_inputs',[]))}\n"
            f"  window.turnstile  : {'PRESENT' if ts.get('ts_obj') else 'absent'}\n"
        )
        for c in containers:
            content += f"  sitekey={c.get('sitekey','?')}  theme={c.get('theme','?')}  execution={c.get('execution','?')}\n"
        lines.append(section("6. Turnstile Analysis", content))
    else:
        lines.append(section("6. Turnstile Analysis", "  (turnstile.json not found — run turnstile_analyzer.py)"))

    # ── 7. Response Headers ─────────────────────────────────────
    rh = data.get("response_headers")
    if rh and isinstance(rh, list):
        cf_count = sum(1 for r in rh if r.get("cf_ray"))
        challenge_count = sum(1 for r in rh if r.get("is_cf_challenge"))
        statuses: dict = {}
        for r in rh:
            s = r.get("status", 0)
            statuses[s] = statuses.get(s, 0) + 1
        content = (
            f"  Total responses    : {len(rh)}\n"
            f"  With CF-Ray        : {cf_count}\n"
            f"  CF challenge URLs  : {challenge_count}\n"
            f"  Status codes       : {statuses}"
        )
        lines.append(section("7. Response Headers", content))
    else:
        lines.append(section("7. Response Headers", "  (response_headers.json not found — run response_logger.py)"))

    # ── 8. Patches ──────────────────────────────────────────────
    pt = data.get("patches")
    if pt and isinstance(pt, dict):
        patch_list = pt.get("patches", [])
        stars_s = lambda n: "★"*n+"☆"*(5-n)
        content = f"  Patches generated: {len(patch_list)}\n\n"
        for p in patch_list:
            content += f"  {stars_s(p.get('stars',1))}  [{p.get('category','?')}]  {p.get('key','?')}\n"
            content += f"  ↳ {p.get('description','?')}\n\n"
        lines.append(section("8. Patch Recommendations", content))
    else:
        lines.append(section("8. Patch Recommendations", "  (patches.json not found — run patch_generator.py)"))

    # ── 9. Validation ───────────────────────────────────────────
    vr = data.get("validation")
    if vr:
        b = vr.get("before", {}); a = vr.get("after", {})
        d_overall = a.get("overall_score", 0) - b.get("overall_score", 0)
        d_cf      = a.get("cf_risk_score", 0) - b.get("cf_risk_score", 0)
        counts    = vr.get("counts", {})
        content = (
            f"  Before overall : {b.get('overall_score','?')}%\n"
            f"  After overall  : {a.get('overall_score','?')}%\n"
            f"  Delta          : {'+' if d_overall>=0 else ''}{d_overall:.1f}%\n"
            f"  CF risk before : {b.get('cf_risk_score','?')}%\n"
            f"  CF risk after  : {a.get('cf_risk_score','?')}%\n"
            f"  CF delta       : {'+' if d_cf>=0 else ''}{d_cf:.1f}%\n"
            f"  Improved keys  : {counts.get('improved','?')}\n"
            f"  Regressed keys : {counts.get('regressed','?')}\n"
            f"  Still wrong    : {counts.get('still_wrong','?')}"
        )
        lines.append(section("9. Patch Validation", content))
    else:
        lines.append(section("9. Patch Validation", "  (validation_report.json not found — run patch_validator.py)"))

    lines += ["", "═"*W, "  END OF REPORT", "═"*W]
    return "\n".join(lines)


def build_html(text: str) -> str:
    body = text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<title>Browser Analysis Report</title>'
        '<style>body{font-family:monospace;background:#0d1117;color:#c9d1d9;padding:2rem;line-height:1.6}'
        'pre{white-space:pre-wrap;word-break:break-all;font-size:0.9rem}'
        '.star{color:#f9c513}'
        '</style></head><body><pre>' + body + '</pre></body></html>'
    )


def build_markdown(data: dict) -> str:
    sc = data.get("score") or {}
    fp_meta = (data.get("fingerprint") or {}).get("_meta", {})
    md = [
        "# Browser Analysis Report",
        "",
        f"Generated: `{datetime.now().isoformat()}`",
        "",
        "## Environment",
        "",
        f"- Channel: `{fp_meta.get('channel','?')}`",
        f"- URL: `{fp_meta.get('url','?')}`",
        f"- Headless: `{fp_meta.get('headless','?')}`",
        "",
        "## Score",
        "",
        f"| Metric | Score |",
        "| --- | --- |",
        f"| Overall Similarity | {sc.get('overall_score','?')}% |",
        f"| CF Risk Score | {sc.get('cf_risk_score','?')}% |",
        "",
    ]
    cats = sc.get("categories", [])
    if cats:
        md += ["## Category Scores", "", "| Category | Score |", "| --- | --- |"]
        for c in cats:
            md.append(f"| {c['category']} | {c.get('score_pct','?')}% |")
    md += ["", "## Patches"]
    pt = data.get("patches") or {}
    for p in pt.get("patches", []):
        stars_s = "★"*p.get("stars",1)+"☆"*(5-p.get("stars",1))
        md += [f"### {p.get('key','?')} {stars_s}", f"{p.get('description','?')}", ""]
    return "\n".join(md)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Aggregate all tool outputs into a complete report.")
    p.add_argument("--out-dir", default="", help="Directory containing all tool outputs (default: tools/output/)")
    p.add_argument("--html",     action="store_true")
    p.add_argument("--markdown", action="store_true")
    p.add_argument("--json-out", action="store_true")
    return p


def main() -> int:
    args  = build_parser().parse_args()
    d     = Path(args.out_dir) if args.out_dir else ensure_output_dir()

    # Load all available outputs
    data = {
        "environment":     try_load(d / "environment.json"),
        "fingerprint":     try_load(d / "fingerprint.json"),
        "score":           try_load(d / "browser_score.json"),
        "timeline":        try_load(d / "timeline.json"),
        "cookies":         try_load(d / "cookies_timeline.json"),
        "turnstile":       try_load(d / "turnstile.json"),
        "response_headers":try_load(d / "response_headers.json"),
        "patches":         try_load(d / "patches.json"),
        "validation":      try_load(d / "validation_report.json"),
    }

    found = [k for k, v in data.items() if v is not None]
    missing = [k for k, v in data.items() if v is None]
    log.info("Loaded: %s", found)
    if missing:
        log.warning("Missing (will show placeholder): %s", missing)

    text = build_text_report(data, d)
    print(text)

    # Always save txt
    txt_path = d / "full_report.txt"
    save_text(text, txt_path)
    log.info("TXT   → %s", txt_path)

    if args.html:
        html_path = d / "full_report.html"
        save_text(build_html(text), html_path)
        log.info("HTML  → %s", html_path)

    if args.markdown:
        md_path = d / "full_report.md"
        save_text(build_markdown(data), md_path)
        log.info("MD    → %s", md_path)

    if args.json_out:
        save_json({"generated_at": datetime.now().isoformat(), "sections": list(data.keys()),
                   "available": found, "missing": missing}, d / "full_report.json")
        log.info("JSON  → %s", d / "full_report.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
