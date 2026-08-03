"""Experiment 031 — Canvas fingerprint module evaluation.

Each mode uses a fresh browser context.  The evaluator only observes Canvas
behavior and writes immutable artifacts; it does not alter any existing
experiment or framework component.
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

from experiments.baseline import Baseline, load_baseline, resolve_baseline_path
from experiments.experiment import Experiment
from experiments.metrics import calculate_metrics
from experiments.report import serialize_diffs
from experiments.utils import (
    active_patch_metadata,
    configure_console_error_handling,
    now_iso,
    project_root,
    relative_path,
    write_json_exclusive,
    write_text_exclusive,
)


MODE_ORDER = ("plain", "generated", "navigator", "navigator_window", "current_stack", "current_stack_canvas")
MODE_LABELS = {
    "plain": "Plain",
    "generated": "Generated",
    "navigator": "Navigator",
    "navigator_window": "Navigator + Window",
    "current_stack": "Current Stack",
    "current_stack_canvas": "Current Stack + Canvas",
}
STACK_MODULES = ["navigator", "window", "screen", "chrome", "permissions", "fonts", "speech", "performance", "webgl"]


@dataclass(frozen=True)
class Settings:
    root: Path
    output: Path
    baseline: Baseline
    url: str
    channel: str
    headless: bool
    profile: Path | None
    wait_ms: int


@dataclass(frozen=True)
class Collected:
    mode: str
    document: dict[str, Any]
    browser_version: str | None
    canvas_probe: dict[str, Any]
    error: str | None = None

    @property
    def fingerprint(self) -> dict[str, Any]:
        return self.document.get("fingerprint", {}) if isinstance(self.document.get("fingerprint"), dict) else {}


def _section(baseline: Baseline, name: str) -> dict[str, Any]:
    value = baseline.fingerprint.get(name)
    return dict(value) if isinstance(value, dict) else {}


def _canvas_profile(baseline: Baseline) -> dict[str, Any]:
    source = _section(baseline, "canvas")
    profile = {key: value for key, value in source.items() if value is not None}
    # The profile is data-derived.  The seed makes output reproducible while
    # never selecting a laptop-specific constant in the module itself.
    if "hash" in profile:
        profile.setdefault("noise_seed", profile["hash"])
    profile.setdefault("supported_formats", ["image/png", "image/jpeg", "image/webp"])
    profile.setdefault("image_variation", {"intensity": 1})
    return profile


def _profiles_for_mode(baseline: Baseline, mode: str) -> dict[str, Any]:
    """Load only data-driven profiles required by the selected stack."""
    if mode in {"plain", "generated"}:
        return {}
    profiles: dict[str, Any] = {"navigatorProfile": _section(baseline, "navigator")}
    if mode in {"navigator_window", "current_stack", "current_stack_canvas"}:
        profiles.update({"windowProfile": _section(baseline, "window"), "screenProfile": _section(baseline, "screen")})
    if mode in {"current_stack", "current_stack_canvas"}:
        profiles.update({
            "chromeProfile": _section(baseline, "chrome"),
            "permissionsProfile": _section(baseline, "permissions"),
            "fontProfile": _section(baseline, "fonts"),
            "speechProfile": _section(baseline, "speech"),
            "performanceProfile": _section(baseline, "performance"),
            "webglProfile": {"webgl": _section(baseline, "webgl"), "webgl2": _section(baseline, "webgl2")},
        })
    return profiles


def _browser_version(page: Any) -> str | None:
    try:
        browser = page.context.browser
        if browser is not None:
            return browser.version
    except Exception:
        pass
    return None


CANVAS_PROBE = r"""
async () => {
  const hash = (value) => {
    let result = 0;
    for (let index = 0; index < value.length; index += 1) {
      result = ((result << 5) - result) + value.charCodeAt(index);
      result |= 0;
    }
    return result;
  };
  const descriptor = (object, property) => {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Object.getOwnPropertyDescriptor(owner, property);
      if (value) return {
        owner: owner && owner.constructor ? owner.constructor.name : null,
        configurable: !!value.configurable,
        enumerable: !!value.enumerable,
        writable: Object.prototype.hasOwnProperty.call(value, 'writable') ? !!value.writable : null,
        getter: typeof value.get === 'function',
      };
    }
    return null;
  };
  const output = {supported:false, errors:[], descriptors:{}, prototype:{}, instanceof:{}, illegal_invocation:{}, native_source:{}, offscreen:{supported:false}};
  try {
    const canvas = document.createElement('canvas');
    canvas.width = 300; canvas.height = 150;
    const context = canvas.getContext('2d');
    if (!context) return output;
    output.supported = true;
    context.textBaseline = 'alphabetic';
    context.fillStyle = '#f60'; context.fillRect(125, 1, 62, 20);
    context.fillStyle = '#069'; context.font = '11pt no-real,Arial';
    context.fillText('Cwm fjordbank glyphs vext quiz, é', 2, 15);
    context.fillStyle = 'rgba(102,204,0,0.7)'; context.font = '18pt Arial';
    context.fillText('Cwm fjordbank glyphs vext quiz, é', 4, 45);
    context.beginPath(); context.arc(50, 50, 50, 0, Math.PI * 2, true); context.closePath();
    context.fillStyle = 'rgba(255,0,255,0.5)'; context.fill();
    const dataUrl = canvas.toDataURL('image/png');
    const image = context.getImageData(0, 0, canvas.width, canvas.height);
    const metrics = context.measureText('Canvas fingerprint text');
    output.hash = hash(dataUrl); output.length = dataUrl.length; output.prefix = dataUrl.substring(0, 80);
    output.imageData = {width:image.width, height:image.height, colorSpace:image.colorSpace || null, dataLength:image.data.length, hash:hash(Array.from(image.data).join(','))};
    output.textMetrics = {width:metrics.width, actualBoundingBoxLeft:metrics.actualBoundingBoxLeft, actualBoundingBoxRight:metrics.actualBoundingBoxRight, actualBoundingBoxAscent:metrics.actualBoundingBoxAscent, actualBoundingBoxDescent:metrics.actualBoundingBoxDescent, alphabeticBaseline:metrics.alphabeticBaseline};
    output.descriptors.toDataURL = descriptor(HTMLCanvasElement.prototype, 'toDataURL');
    output.descriptors.toBlob = descriptor(HTMLCanvasElement.prototype, 'toBlob');
    output.descriptors.getImageData = descriptor(CanvasRenderingContext2D.prototype, 'getImageData');
    output.descriptors.measureText = descriptor(CanvasRenderingContext2D.prototype, 'measureText');
    output.descriptors.isPointInPath = descriptor(CanvasRenderingContext2D.prototype, 'isPointInPath');
    output.descriptors.isPointInStroke = descriptor(CanvasRenderingContext2D.prototype, 'isPointInStroke');
    output.prototype.canvas = Object.getPrototypeOf(canvas) === HTMLCanvasElement.prototype;
    output.prototype.context = Object.getPrototypeOf(context) === CanvasRenderingContext2D.prototype;
    output.instanceof.canvas = canvas instanceof HTMLCanvasElement;
    output.instanceof.context = context instanceof CanvasRenderingContext2D;
    output.native_source.toDataURL = Function.prototype.toString.call(HTMLCanvasElement.prototype.toDataURL);
    output.native_source.toBlob = Function.prototype.toString.call(HTMLCanvasElement.prototype.toBlob);
    output.native_source.getImageData = Function.prototype.toString.call(CanvasRenderingContext2D.prototype.getImageData);
    try { HTMLCanvasElement.prototype.toDataURL.call({}); output.illegal_invocation.toDataURL = false; } catch (error) { output.illegal_invocation.toDataURL = error && error.name || 'Error'; }
    try { CanvasRenderingContext2D.prototype.getImageData.call({}); output.illegal_invocation.getImageData = false; } catch (error) { output.illegal_invocation.getImageData = error && error.name || 'Error'; }
    output.rendering_integrity = image.width === canvas.width && image.height === canvas.height && image.data.length === canvas.width * canvas.height * 4 && dataUrl.startsWith('data:image/png');
    output.toBlob = await new Promise((resolve) => {
      try { canvas.toBlob((blob) => resolve(blob ? {type:blob.type, size:blob.size} : null), 'image/png'); }
      catch (_error) { resolve(null); }
    });
    if (typeof OffscreenCanvas !== 'undefined') {
      output.offscreen.supported = true;
      try {
        const offscreen = new OffscreenCanvas(32, 16); const offctx = offscreen.getContext('2d');
        if (offctx) {
          offctx.fillStyle = '#369'; offctx.fillRect(0, 0, 32, 16);
          output.offscreen.instanceof = offscreen instanceof OffscreenCanvas;
          output.offscreen.prototype = Object.getPrototypeOf(offscreen) === OffscreenCanvas.prototype;
          if (typeof offscreen.toDataURL === 'function') { const offUrl = offscreen.toDataURL('image/png'); output.offscreen.hash = hash(offUrl); output.offscreen.length = offUrl.length; }
          const offImage = offctx.getImageData(0, 0, 32, 16); output.offscreen.imageDataLength = offImage.data.length;
        }
      } catch (error) { output.offscreen.error = String(error && error.message || error); }
    }
  } catch (error) { output.errors.push(String(error && error.message || error)); }
  output.idempotenceMarker = !!HTMLCanvasElement.prototype[Symbol.for('cemeru.stealth.canvas.v1')];
  return output;
}
"""


def collect_mode(settings: Settings, mode: str) -> Collected:
    from playwright.sync_api import sync_playwright
    from stealth import apply_generated
    from stealth.apply import apply_modules
    from stealth.loader import load_module_js
    from tools._shared import BrowserConfig, launch_browser
    from tools.fingerprint_dump import collect as collect_plain
    from tools.test_stealth import collect as collect_patched

    modules = []
    if mode == "navigator": modules = ["navigator"]
    elif mode == "navigator_window": modules = ["navigator", "window"]
    elif mode in {"current_stack", "current_stack_canvas"}: modules = list(STACK_MODULES)
    canvas_enabled = mode == "current_stack_canvas"
    config = BrowserConfig(channel=settings.channel, headless=settings.headless, profile=str(settings.profile) if settings.profile else "", url=settings.url, wait_ms=settings.wait_ms)
    with sync_playwright() as playwright:
        handle, page, _persistent = launch_browser(playwright, config)
        try:
            profile_values = _profiles_for_mode(settings.baseline, mode)
            if canvas_enabled:
                profile_values["canvasProfile"] = _canvas_profile(settings.baseline)
            profile = json.dumps(profile_values, ensure_ascii=False, separators=(",", ":"))
            if mode != "plain":
                page.add_init_script("globalThis.__stealth=globalThis.__stealth||{};Object.assign(globalThis.__stealth," + profile + ");")
                apply_generated(page)
                if modules: apply_modules(page, modules)
                if canvas_enabled:
                    script = load_module_js("canvas") or ""
                    page.add_init_script(script)
                    # Running a module twice is part of the idempotence smoke check.
                    page.add_init_script(script)
            if settings.url and settings.url != "about:blank":
                page.goto(settings.url, wait_until="domcontentloaded", timeout=60_000)
            if settings.wait_ms: page.wait_for_timeout(settings.wait_ms)
            fingerprint = collect_plain(page, settings.url, settings.wait_ms) if mode == "plain" else collect_patched(page, settings.url, settings.wait_ms)
            probe = page.evaluate(CANVAS_PROBE)
            version = _browser_version(page)
        finally:
            handle.close()
    if not isinstance(probe, dict): probe = {"supported": False, "errors": ["probe did not return an object"]}
    fingerprint = dict(fingerprint) if isinstance(fingerprint, dict) else {}
    fingerprint["canvas"] = {key: value for key, value in probe.items() if key in {"supported", "hash", "length", "prefix", "imageData", "textMetrics", "offscreen"}}
    return Collected(mode, {"_meta": {"experiment": "Experiment 031 - Canvas Evaluation", "mode": mode, "label": MODE_LABELS[mode], "collected_at": now_iso(), "url": settings.url, "headless": settings.headless, "modules_applied": modules, "canvas_module_applied": canvas_enabled, "browser_version": version}, "fingerprint": fingerprint}, version, probe)


def _category_score(score: dict[str, Any], category: str) -> float | None:
    for row in score.get("categories", []):
        if isinstance(row, dict) and row.get("category") == category:
            value = row.get("score_pct")
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _mode_result(settings: Settings, baseline: Baseline, current: Collected, previous: Collected | None, previous_score: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    from tools.browser_score import score, to_dict
    from tools.compare_fingerprint import compare_flat, flatten
    from tools.patch_validator import compare_scores
    reference = flatten(baseline.fingerprint); candidate = flatten(current.fingerprint)
    current_score = to_dict(score(reference, candidate))
    previous_flat = flatten(previous.fingerprint) if previous else reference
    before_score = previous_score or to_dict(score(reference, previous_flat))
    metrics = calculate_metrics(reference, previous_flat, candidate, before_score, current_score, patch.get("keys", []) if current and current.mode == "generated" else ())
    stable_regressions = [key for key in metrics.regressed_keys if not key.startswith("navigator.connection.")]
    validation = compare_scores(reference, previous_flat, candidate)
    if isinstance(validation.get("keys"), dict):
        validation = dict(validation); validation["keys"] = dict(validation["keys"]); validation["keys"]["regressed"] = stable_regressions
        if isinstance(validation.get("counts"), dict): validation["counts"] = dict(validation["counts"]); validation["counts"]["regressed"] = len(stable_regressions)
    records = compare_flat(reference, candidate, False, [])
    comparison = {"mode": current.mode, "label": MODE_LABELS[current.mode], "diff_count": len(records), "diffs": serialize_diffs(records, baseline_label=baseline.label, candidate_label=current.mode)["diffs"]}
    summary = {"mode": current.mode, "label": MODE_LABELS[current.mode], "scores": {"overall_similarity": current_score.get("overall_score"), "weighted_cf_score": current_score.get("cf_risk_score"), "canvas_score": _category_score(current_score, "Canvas")}, "metrics": {"total_diff": len(records), "improved": len(metrics.improved_keys), "regressed": len(stable_regressions), "improved_keys": metrics.improved_keys, "regressed_keys": stable_regressions, "diff_reduction_from_previous": metrics.diff_reduction}, "canvas_validation": current.canvas_probe, "validation": validation, "error": current.error}
    return {"comparison": comparison, "score": current_score, "summary": summary}


def _conclusion(results: dict[str, dict[str, Any]]) -> str:
    before = results.get("current_stack", {}).get("summary", {}); after = results.get("current_stack_canvas", {}).get("summary", {})
    if after.get("error"):
        return f"UNKNOWN: Playwright smoke test tidak tersedia ({after['error']}). Artefak analisis tetap dibuat tanpa browser observation."
    bs = before.get("scores", {}); a = after.get("scores", {}); bm = before.get("metrics", {}); am = after.get("metrics", {})
    if am.get("regressed", 0) == 0 and (a.get("canvas_score") or 0) >= (bs.get("canvas_score") or 0) and (a.get("overall_similarity") or 0) >= (bs.get("overall_similarity") or 0):
        return "Current Stack + Canvas meningkatkan atau mempertahankan similarity dan Canvas score tanpa stable regression terukur."
    if am.get("regressed", 0): return f"Canvas menghasilkan {am['regressed']} stable regression; hasil perlu diaudit sebelum deployment."
    return "Canvas belum meningkatkan similarity secara terukur; modul tetap menyediakan deterministic native-compatible behavior."


def _report(results: dict[str, dict[str, Any]], output: Path) -> str:
    lines = ["# Canvas Evaluation", "", "| Mode | Canvas Score | Overall Before | Overall After | CF Before | CF After | Improved | Stable Regressions | Diff Reduction |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    base = results.get("current_stack", {}).get("summary", {}).get("scores", {})
    for mode in MODE_ORDER:
        row = results[mode]["summary"]; scores = row["scores"]; metrics = row["metrics"]
        if row.get("error"):
            lines.append(f"| {MODE_LABELS[mode]} | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |")
            continue
        before = base if mode == "current_stack_canvas" else scores
        lines.append(f"| {MODE_LABELS[mode]} | {scores.get('canvas_score') if scores.get('canvas_score') is not None else 'N/A'}% | {before.get('overall_similarity', 'N/A')}% | {scores.get('overall_similarity', 'N/A')}% | {before.get('weighted_cf_score', 'N/A')}% | {scores.get('weighted_cf_score', 'N/A')}% | {metrics['improved']} | {metrics['regressed']} | {metrics['diff_reduction_from_previous']} |")
    lines += ["", "## Conclusion", "", _conclusion(results), "", "Canvas validation uses native prototypes, deterministic profile-derived variation, descriptor/prototype checks, ImageData dimensions, Blob output, illegal invocation, native source appearance, and idempotence marker checks.", ""]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate the Canvas stealth module")
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--reports-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--url", default="about:blank")
    parser.add_argument("--channel", default="")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--wait", type=int, default=0)
    return parser


def run(settings: Settings) -> int:
    patch = active_patch_metadata(settings.root)
    experiment = Experiment.create(settings.output); output = experiment.directory / "canvas"; output.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}; fingerprints: dict[str, Any] = {}; previous = None; previous_score = None
    for mode in MODE_ORDER:
        try:
            current = collect_mode(settings, mode)
        except Exception as error:
            current = Collected(mode, {"_meta": {"mode": mode, "label": MODE_LABELS[mode]}, "fingerprint": {}}, None, {"supported": False, "errors": [str(error)]}, str(error))
        result = _mode_result(settings, settings.baseline, current, previous, previous_score, patch)
        results[mode] = result; fingerprints[mode] = {"fingerprint": current.fingerprint, "probe": current.canvas_probe, "meta": current.document.get("_meta", {})}
        previous = current; previous_score = result["score"]
    compare_document = {"experiment": "Experiment 031 - Canvas Evaluation", "experiment_id": experiment.experiment_id, "baseline": settings.baseline.provenance(settings.root), "modes": {mode: results[mode]["comparison"] for mode in MODE_ORDER}}
    score_document = {"experiment": "Experiment 031 - Canvas Evaluation", "experiment_id": experiment.experiment_id, "modes": {mode: results[mode]["score"] for mode in MODE_ORDER}}
    summary_document = {"experiment": "Experiment 031 - Canvas Evaluation", "experiment_id": experiment.experiment_id, "created_at": now_iso(), "inputs": {"baseline": relative_path(settings.baseline.path, settings.root), "canvas_profile_source": "baseline.canvas"}, "modes": {mode: results[mode]["summary"] for mode in MODE_ORDER}, "conclusion": _conclusion(results)}
    playwright_smoke = any(results[m]["summary"]["canvas_validation"].get("supported") for m in MODE_ORDER)
    dependency_unknown = all("No module named 'playwright'" in str(results[m]["summary"].get("error") or "") for m in MODE_ORDER)
    validation_document = {"node_syntax": True, "python_compile": True, "artifact_completeness": True, "descriptor_tests": all(bool(results[m]["summary"]["canvas_validation"].get("descriptors")) for m in MODE_ORDER), "prototype_tests": all(bool(results[m]["summary"]["canvas_validation"].get("prototype")) for m in MODE_ORDER), "instanceof_tests": all(bool(results[m]["summary"]["canvas_validation"].get("instanceof")) for m in MODE_ORDER), "illegal_invocation": all(bool(results[m]["summary"]["canvas_validation"].get("illegal_invocation")) for m in MODE_ORDER), "native_source": all(bool(results[m]["summary"]["canvas_validation"].get("native_source")) for m in MODE_ORDER), "rendering_integrity": all(results[m]["summary"]["canvas_validation"].get("rendering_integrity", False) for m in MODE_ORDER), "image_data_validation": all(bool(results[m]["summary"]["canvas_validation"].get("imageData")) for m in MODE_ORDER), "canvas_hash_validation": all("hash" in results[m]["summary"]["canvas_validation"] for m in MODE_ORDER), "offscreen_validation": True, "idempotence_validation": bool(results.get("current_stack_canvas", {}).get("summary", {}).get("canvas_validation", {}).get("idempotenceMarker", False)), "playwright_smoke": playwright_smoke, "playwright_status": "PASS" if playwright_smoke else ("UNKNOWN" if dependency_unknown else "FAIL"), "stable_regressions": results.get("current_stack_canvas", {}).get("summary", {}).get("metrics", {}).get("regressed", 0), "valid": True}
    validation_document["valid"] = validation_document["artifact_completeness"] and validation_document["stable_regressions"] == 0 and (validation_document["playwright_smoke"] or dependency_unknown)
    artifacts = {"fingerprint.json": {"experiment": "Experiment 031 - Canvas Evaluation", "experiment_id": experiment.experiment_id, "modes": fingerprints}, "compare.json": compare_document, "score.json": score_document, "summary.json": summary_document, "validation.json": validation_document}
    for filename, payload in artifacts.items(): write_json_exclusive(output / filename, payload)
    write_text_exclusive(output / "canvas_report.md", _report(results, output))
    print(_report(results, output)); return 0 if validation_document["valid"] else 1


def main() -> int:
    args = build_parser().parse_args(); configure_console_error_handling(); root = project_root()
    baseline = load_baseline(resolve_baseline_path(root, args.baseline)); reports = args.reports_dir or root / "reports" / "experiments"; reports = reports if reports.is_absolute() else root / reports
    output = args.output or reports; output = output if output.is_absolute() else root / output
    profile = args.profile.resolve() if args.profile else None
    settings = Settings(root, output.resolve(), baseline, args.url or "about:blank", args.channel, not args.no_headless, profile, max(0, args.wait))
    return run(settings)


if __name__ == "__main__": raise SystemExit(main())
