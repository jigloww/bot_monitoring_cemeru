"""
tools/browser_score.py — Score Playwright fingerprint quality vs a real Chrome reference.

Produces per-category similarity scores and highlights most suspicious diffs.

Usage:
    python tools/browser_score.py tools/output/fingerprint_real.json tools/output/fingerprint_playwright.json
    python tools/browser_score.py --ref real.json --test playwright.json --output score.json
"""
from __future__ import annotations
import argparse, json, sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools._shared import ensure_output_dir, load_json, save_json, setup_logging
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
    p = argparse.ArgumentParser(description="Score Playwright fingerprint quality vs real Chrome reference.")
    p.add_argument("ref",  help="Reference (real Chrome) fingerprint JSON")
    p.add_argument("test", help="Test (Playwright) fingerprint JSON")
    p.add_argument("--out-dir", default="")
    p.add_argument("--output",  default="")
    return p


def main() -> int:
    args      = build_parser().parse_args()
    label_ref  = Path(args.ref).stem
    label_test = Path(args.test).stem
    raw_ref    = load_json(Path(args.ref))
    raw_test   = load_json(Path(args.test))
    fp_ref     = raw_ref.get("fingerprint",  raw_ref)
    fp_test    = raw_test.get("fingerprint", raw_test)
    flat_ref   = flatten(fp_ref)
    flat_test  = flatten(fp_test)
    report     = score(flat_ref, flat_test)
    text       = render_report(report, label_ref, label_test)
    print(text)
    out = Path(args.output) if args.output else (Path(args.out_dir) if args.out_dir else ensure_output_dir()) / "browser_score.json"
    save_json(to_dict(report), out)
    log.info("Score saved → %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
