"""
tools/patch_validator.py — Compare fingerprint before and after applying patches.

Shows: what improved, what regressed, overall score delta.

Usage:
    python tools/patch_validator.py \
        --before tools/output/fingerprint_playwright.json \
        --after  tools/output/fingerprint_patched.json \
        --ref    tools/output/fingerprint_real.json
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools._shared import ensure_output_dir, load_json, save_json, setup_logging
from tools.compare_fingerprint import flatten, vals_equal, KB
from tools.browser_score import score, render_report, to_dict

log = setup_logging("patch_validator")


def compare_scores(
    flat_ref:    dict,
    flat_before: dict,
    flat_after:  dict,
) -> dict:
    """Compare before-patch and after-patch scores against ref."""
    score_before = score(flat_ref, flat_before)
    score_after  = score(flat_ref, flat_after)

    # Key-level analysis
    all_keys = sorted(set(flat_ref) | set(flat_before) | set(flat_after))
    improved:   list[str] = []
    regressed:  list[str] = []
    unchanged:  list[str] = []

    for key in all_keys:
        ref_v    = flat_ref.get(key,    "<missing>")
        before_v = flat_before.get(key, "<missing>")
        after_v  = flat_after.get(key,  "<missing>")

        was_correct = vals_equal(ref_v, before_v)
        is_correct  = vals_equal(ref_v, after_v)

        if not was_correct and is_correct:
            improved.append(key)
        elif was_correct and not is_correct:
            regressed.append(key)
        elif not was_correct and not is_correct:
            unchanged.append(key)

    return {
        "before": {
            "overall_score": score_before.overall_score,
            "cf_risk_score": score_before.cf_risk_score,
        },
        "after": {
            "overall_score": score_after.overall_score,
            "cf_risk_score": score_after.cf_risk_score,
        },
        "delta": {
            "overall": round(score_after.overall_score - score_before.overall_score, 1),
            "cf_risk": round(score_after.cf_risk_score - score_before.cf_risk_score, 1),
        },
        "keys": {
            "improved":   improved,
            "regressed":  regressed,
            "still_wrong": unchanged[:20],
        },
        "counts": {
            "improved":   len(improved),
            "regressed":  len(regressed),
            "still_wrong": len(unchanged),
        },
    }


def render_validation(result: dict, label_before: str, label_after: str, label_ref: str) -> str:
    W = 56
    lines = ["═"*W, "  PATCH VALIDATION REPORT",
             f"  Reference : {label_ref}",
             f"  Before    : {label_before}",
             f"  After     : {label_after}",
             "═"*W, ""]

    b = result["before"]
    a = result["after"]
    d = result["delta"]

    def delta_str(v: float) -> str:
        return f"+{v:.1f}" if v >= 0 else f"{v:.1f}"

    lines += [
        f"  OVERALL SCORE",
        f"  Before : {b['overall_score']:.1f}%",
        f"  After  : {a['overall_score']:.1f}%",
        f"  Delta  : {delta_str(d['overall'])}%",
        "",
        f"  CF RISK SCORE (weighted)",
        f"  Before : {b['cf_risk_score']:.1f}%",
        f"  After  : {a['cf_risk_score']:.1f}%",
        f"  Delta  : {delta_str(d['cf_risk'])}%",
        "",
        "─"*W,
        f"  ✓ Improved   : {result['counts']['improved']} fields",
        f"  ✗ Regressed  : {result['counts']['regressed']} fields",
        f"  ~ Still wrong: {result['counts']['still_wrong']} fields",
        "",
    ]

    if result["keys"]["improved"]:
        lines.append("  IMPROVED FIELDS")
        for k in result["keys"]["improved"]:
            lines.append(f"    ✓ {k}")
        lines.append("")

    if result["keys"]["regressed"]:
        lines.append("  ⚠ REGRESSED FIELDS (patches caused new differences!)")
        for k in result["keys"]["regressed"]:
            lines.append(f"    ✗ {k}")
        lines.append("")

    if result["keys"]["still_wrong"]:
        lines.append(f"  STILL WRONG (first 20 of {result['counts']['still_wrong']})")
        for k in result["keys"]["still_wrong"]:
            stars = KB.get(k, (None, None, 1))[2]
            lines.append(f"    {'★'*stars}  {k}")
        lines.append("")

    lines.append("═"*W)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Validate patches by comparing before/after fingerprints against reference.")
    p.add_argument("--before", required=True, help="Pre-patch fingerprint JSON")
    p.add_argument("--after",  required=True, help="Post-patch fingerprint JSON")
    p.add_argument("--ref",    required=True, help="Reference (real Chrome) fingerprint JSON")
    p.add_argument("--out-dir", default="")
    return p


def main() -> int:
    from tools._shared import save_text
    args       = build_parser().parse_args()
    label_ref    = Path(args.ref).stem
    label_before = Path(args.before).stem
    label_after  = Path(args.after).stem

    raw_ref    = load_json(Path(args.ref))
    raw_before = load_json(Path(args.before))
    raw_after  = load_json(Path(args.after))

    fp_ref    = raw_ref.get("fingerprint",    raw_ref)
    fp_before = raw_before.get("fingerprint", raw_before)
    fp_after  = raw_after.get("fingerprint",  raw_after)

    flat_ref    = flatten(fp_ref)
    flat_before = flatten(fp_before)
    flat_after  = flatten(fp_after)

    result = compare_scores(flat_ref, flat_before, flat_after)
    text   = render_validation(result, label_before, label_after, label_ref)
    print(text)

    out = Path(args.out_dir) if args.out_dir else ensure_output_dir()
    save_json(result, out / "validation_report.json")
    save_text(text,   out / "validation_report.txt")
    log.info("Saved → %s", out / "validation_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
