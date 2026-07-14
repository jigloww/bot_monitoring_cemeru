"""
tools/browser_score.py — Score Playwright fingerprint quality vs a real Chrome reference.

Produces per-category similarity scores and highlights most suspicious diffs.

Usage:
    python tools/browser_score.py --ref fingerprint_real.json --test fingerprint_playwright.json --output reports/browser/browser_score.json

    # Positional form (backward compatible):
    python tools/browser_score.py fingerprint_real.json fingerprint_playwright.json --output score.json
"""
from __future__ import annotations
import argparse, json, sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools._shared import (
    ensure_output_dir,
    save_json,
    setup_logging,
    add_output_arg
)
from tools.compare_fingerprint import flatten, vals_equal, KB, CATEGORY_ORDER

log = setup_logging("browser_score")

# ── CF likelihood weight per category ──────────────────────────────
CATEGORY_WEIGHT = {
    "Navigator":   1.8,
    "WebGL":       2.0,
    "Canvas":      1.6,
    "Audio":       1.5,
    "Chrome":      2.0,
    "Plugins":     1.4,
    "Fonts":       1.3,
    "Window":      1.4,
    "Screen":      1.0,
    "Permissions": 0.9,
    "Speech":      0.8,
    "Performance": 0.7,
    "Storage":     0.5,
    "Battery":     0.6,
    "RTC":         0.7,
    "Features":    0.8,
    "Other":       0.4,
}


@dataclass
class CategoryScore:
    category:    str
    total:       int  = 0
    matched:     int  = 0
    score_pct:   float = 0.0
    weight:      float = 1.0
    worst_keys:  list[str] = field(default_factory=list)


@dataclass
class BrowserScoreReport:
    overall_score:    float
    cf_risk_score:    float           # weighted risk (lower = riskier)
    categories:       list[CategoryScore]
    suspicious_diffs: list[dict]


# ══════════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════════

def score(flat_ref: dict[str, Any], flat_test: dict[str, Any]) -> BrowserScoreReport:
    """Compare two flat fingerprint dicts and produce scores."""
    all_keys = sorted(set(flat_ref) | set(flat_test))

    # Group by category
    cat_data: dict[str, dict] = {}

    for key in all_keys:
        v_ref  = flat_ref.get(key,  "<missing>")
        v_test = flat_test.get(key, "<missing>")
        eq     = (key in flat_ref) and (key in flat_test) and vals_equal(v_ref, v_test)

        # Determine category
        cat = "Other"
        if key in KB:
            cat = KB[key][0]
        else:
            for k, v in KB.items():
                if key.startswith(k + ".") or key.startswith(k + "["):
                    cat = v[0]; break
            else:
                # Guess from key prefix
                prefix = key.split(".")[0].split("[")[0].lower()
                cat_map = {
                    "navigator": "Navigator", "webgl": "WebGL", "webgl2": "WebGL",
                    "canvas": "Canvas", "audio": "Audio", "chrome": "Chrome",
                    "plugins": "Plugins", "fonts": "Fonts", "window": "Window",
                    "screen": "Screen", "permissions": "Permissions", "speech": "Speech",
                    "performance": "Performance", "storage": "Storage",
                    "battery": "Battery", "rtc": "RTC", "features": "Features",
                }
                cat = cat_map.get(prefix, "Other")

        if cat not in cat_data:
            cat_data[cat] = {"total": 0, "matched": 0, "diffs": []}
        cat_data[cat]["total"] += 1
        if eq:
            cat_data[cat]["matched"] += 1
        else:
            stars = KB.get(key, (None, None, 1))[2]
            cat_data[cat]["diffs"].append({"key": key, "ref": v_ref, "test": v_test, "stars": stars})

    # Build category scores
    categories: list[CategoryScore] = []
    for cat in CATEGORY_ORDER + sorted(c for c in cat_data if c not in CATEGORY_ORDER):
        if cat not in cat_data:
            continue
        d = cat_data[cat]
        total   = d["total"]
        matched = d["matched"]
        pct     = (matched / total * 100) if total else 100.0
        worst   = sorted(d["diffs"], key=lambda x: -x["stars"])[:3]
        categories.append(CategoryScore(
            category  = cat,
            total     = total,
            matched   = matched,
            score_pct = round(pct, 1),
            weight    = CATEGORY_WEIGHT.get(cat, 1.0),
            worst_keys= [x["key"] for x in worst],
        ))

    # Overall score (simple average)
    if categories:
        overall = round(sum(c.score_pct for c in categories) / len(categories), 1)
    else:
        overall = 100.0

    # CF risk score (weighted — lower score = riskier)
    total_weight = sum(c.weight for c in categories)
    if total_weight > 0:
        cf_risk = round(sum(c.score_pct * c.weight for c in categories) / total_weight, 1)
    else:
        cf_risk = 100.0

    # Top suspicious diffs ranked by CF stars
    all_diffs = []
    for cat, d in cat_data.items():
        for diff in d["diffs"]:
            diff["category"] = cat
            all_diffs.append(diff)
    all_diffs.sort(key=lambda x: -x["stars"])
    suspicious = all_diffs[:20]

    return BrowserScoreReport(
        overall_score  = overall,
        cf_risk_score  = cf_risk,
        categories     = categories,
        suspicious_diffs= suspicious,
    )


# ══════════════════════════════════════════════════════════════════
# RENDER
# ══════════════════════════════════════════════════════════════════

def render_report(report: BrowserScoreReport, label_ref: str, label_test: str) -> str:
    W = 52
    lines = ["═"*W, "  BROWSER FINGERPRINT SCORE REPORT",
             f"  Reference : {label_ref}", f"  Test      : {label_test}", "═"*W, ""]

    # Category scores
    lines.append("  CATEGORY SCORES")
    lines.append("  " + "─"*40)
    for cs in report.categories:
        bar_filled = int(cs.score_pct / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        lines.append(f"  {cs.category:<20} {bar} {cs.score_pct:5.1f}%")

    lines += ["", "─"*W]
    lines.append(f"  Overall Similarity : {report.overall_score:.1f}%")
    lines.append(f"  CF Risk Score      : {report.cf_risk_score:.1f}%  (weighted by CF relevance)")

    # Risk interpretation
    if report.cf_risk_score >= 90:
        risk_label = "🟢 LOW — fingerprint looks similar to real Chrome"
    elif report.cf_risk_score >= 75:
        risk_label = "🟡 MEDIUM — some suspicious differences detected"
    elif report.cf_risk_score >= 60:
        risk_label = "🟠 HIGH — several CF-relevant differences"
    else:
        risk_label = "🔴 CRITICAL — fingerprint significantly differs from real Chrome"

    lines += [f"  Risk Level         : {risk_label}", "", "═"*W, ""]

    # Most suspicious diffs
    lines += ["  MOST SUSPICIOUS DIFFERENCES (by CF likelihood)", "  " + "─"*40, ""]
    stars_s = lambda n: "★"*n+"☆"*(5-n)
    for d in report.suspicious_diffs[:15]:
        lines.append(f"  {stars_s(d['stars'])}  [{d['category']}]  {d['key']}")
        ref_s  = str(d["ref"])[:60]
        test_s = str(d["test"])[:60]
        lines += [f"    ref : {ref_s}", f"    test: {test_s}", ""]

    lines.append("═"*W)
    return "\n".join(lines)


def to_dict(report: BrowserScoreReport) -> dict:
    import dataclasses
    return {
        "overall_score":   report.overall_score,
        "cf_risk_score":   report.cf_risk_score,
        "categories": [dataclasses.asdict(c) for c in report.categories],
        "suspicious_diffs": report.suspicious_diffs,
    }


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Score Playwright fingerprint quality vs real Chrome reference.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/browser_score.py --ref fingerprint_real.json --test fingerprint_playwright.json --output score.json
  python tools/browser_score.py fingerprint_real.json fingerprint_playwright.json  # positional (backward compat)
"""
    )
    # Named args (preferred)
    p.add_argument("--ref",  default=None, help="Reference (real Chrome) fingerprint JSON")
    p.add_argument("--test", default=None, help="Test (Playwright) fingerprint JSON")
    # Positional args (backward compatible)
    p.add_argument("ref_pos",  nargs="?", default=None, help=argparse.SUPPRESS)
    p.add_argument("test_pos", nargs="?", default=None, help=argparse.SUPPRESS)
    add_output_arg(p, default="")  # e.g. --output reports/browser/browser_score.json
    return p


def main() -> int:
    args       = build_parser().parse_args()
    # Resolve ref/test from named args (preferred) or positional (backward compat)
    ref_file   = args.ref  or args.ref_pos
    test_file  = args.test or args.test_pos
    if not ref_file or not test_file:
        build_parser().error("Provide --ref and --test, or two positional file arguments.")
    label_ref  = Path(ref_file).stem
    label_test = Path(test_file).stem
    raw_ref    = load_json(Path(ref_file))
    raw_test   = load_json(Path(test_file))
    fp_ref     = raw_ref.get("fingerprint",  raw_ref)
    fp_test    = raw_test.get("fingerprint", raw_test)
    flat_ref   = flatten(fp_ref)
    flat_test  = flatten(fp_test)
    report     = score(flat_ref, flat_test)
    text       = render_report(report, label_ref, label_test)
    print(text)
    out = Path(args.output) if args.output else ensure_output_dir() / "browser_score.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    save_json(to_dict(report), out)
    log.info("Score saved → %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
