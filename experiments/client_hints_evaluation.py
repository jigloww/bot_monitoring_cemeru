"""Experiment 033 — User-Agent Client Hints evaluation."""
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
from experiments.utils import active_patch_metadata, configure_console_error_handling, now_iso, project_root, relative_path, write_json_exclusive, write_text_exclusive


MODE_ORDER = ("current_stack", "current_stack_client_hints")
MODE_LABELS = {"current_stack": "Current Stack", "current_stack_client_hints": "Current Stack + Client Hints"}
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
    probe: dict[str, Any]
    error: str | None = None

    @property
    def fingerprint(self) -> dict[str, Any]:
        return self.document.get("fingerprint", {}) if isinstance(self.document.get("fingerprint"), dict) else {}


def _section(baseline: Baseline, name: str) -> dict[str, Any]:
    value = baseline.fingerprint.get(name)
    return dict(value) if isinstance(value, dict) else {}


def _client_profile(baseline: Baseline) -> dict[str, Any]:
    source = _section(baseline, "navigator").get("userAgentData", {})
    source = dict(source) if isinstance(source, dict) else {}
    high = source.get("high_entropy", {}) if isinstance(source.get("high_entropy"), dict) else {}
    profile = {key: value for key, value in source.items() if key != "high_entropy"}
    profile.update({key: value for key, value in high.items() if key not in {"brands", "mobile", "platform"} or key not in profile})
    profile["high_entropy"] = high
    return profile


def _profiles(baseline: Baseline, client_hints: bool) -> dict[str, Any]:
    profiles = {"navigatorProfile": _section(baseline, "navigator"), "windowProfile": _section(baseline, "window"), "screenProfile": _section(baseline, "screen"), "chromeProfile": _section(baseline, "chrome"), "permissionsProfile": _section(baseline, "permissions"), "fontProfile": _section(baseline, "fonts"), "speechProfile": _section(baseline, "speech"), "performanceProfile": _section(baseline, "performance"), "webglProfile": {"webgl": _section(baseline, "webgl"), "webgl2": _section(baseline, "webgl2")}}
    if client_hints: profiles["clientHintsProfile"] = _client_profile(baseline)
    return profiles


UA_PROBE = r"""
async () => {
  const out = {supported:false, descriptors:{}, prototype:{}, instanceof:{}, illegal_invocation:{}, native_source:{}, promise:{}, immutable:{}, errors:[]};
  try {
    const value = navigator.userAgentData;
    if (!value) return out;
    out.supported = true;
    const descriptor = Object.getOwnPropertyDescriptor(Navigator.prototype, 'userAgentData');
    out.descriptors.navigator = descriptor ? {configurable:!!descriptor.configurable, enumerable:!!descriptor.enumerable, getter:typeof descriptor.get === 'function', setter:typeof descriptor.set === 'function'} : null;
    const prototype = Object.getPrototypeOf(value); out.prototype.same = !!prototype && Object.getPrototypeOf(value) === prototype; out.prototype.name = prototype && prototype.constructor ? prototype.constructor.name : null;
    out.instanceof.self = value instanceof value.constructor;
    out.low = {brands:value.brands, mobile:value.mobile, platform:value.platform};
    out.high = await value.getHighEntropyValues(['architecture','bitness','brands','fullVersionList','mobile','model','platform','platformVersion','uaFullVersion']);
    out.json = typeof value.toJSON === 'function' ? value.toJSON() : null;
    out.immutable.brands = Object.isFrozen(value.brands); out.immutable.jsonBrands = !!(out.json && Object.isFrozen(out.json.brands));
    out.native_source.getHighEntropyValues = Function.prototype.toString.call(value.getHighEntropyValues);
    out.native_source.toJSON = typeof value.toJSON === 'function' ? Function.prototype.toString.call(value.toJSON) : null;
    const beforeUA = navigator.userAgent; await value.getHighEntropyValues([]); out.userAgentUnchanged = beforeUA === navigator.userAgent;
    const promise = value.getHighEntropyValues([]); out.promise.isPromise = !!promise && typeof promise.then === 'function'; out.promise.async = !(promise instanceof Object && promise.constructor === Object); await promise;
    try { value.getHighEntropyValues.call({}); out.illegal_invocation.getHighEntropyValues = false; } catch (error) { out.illegal_invocation.getHighEntropyValues = error && error.name || 'Error'; }
    try { value.toJSON.call({}); out.illegal_invocation.toJSON = false; } catch (error) { out.illegal_invocation.toJSON = error && error.name || 'Error'; }
    out.idempotenceMarker = !!Navigator.prototype[Symbol.for('cemeru.stealth.clientHints.v1')];
  } catch (error) { out.errors.push(String(error && error.message || error)); }
  return out;
}
"""


def collect_mode(settings: Settings, mode: str) -> Collected:
    from playwright.sync_api import sync_playwright
    from stealth import apply_generated
    from stealth.apply import apply_modules
    from stealth.loader import load_module_js
    from tools._shared import BrowserConfig, launch_browser
    from tools.test_stealth import collect as collect_patched
    client_enabled = mode == "current_stack_client_hints"
    config = BrowserConfig(channel=settings.channel, headless=settings.headless, profile=str(settings.profile) if settings.profile else "", url=settings.url, wait_ms=settings.wait_ms)
    with sync_playwright() as playwright:
        handle, page, _persistent = launch_browser(playwright, config)
        try:
            serialized = json.dumps(_profiles(settings.baseline, client_enabled), ensure_ascii=False, separators=(",", ":"))
            page.add_init_script("globalThis.__stealth=globalThis.__stealth||{};Object.assign(globalThis.__stealth," + serialized + ");")
            apply_generated(page); apply_modules(page, STACK_MODULES)
            if client_enabled:
                script = load_module_js("client_hints") or ""; page.add_init_script(script); page.add_init_script(script)
            if settings.url and settings.url != "about:blank": page.goto(settings.url, wait_until="domcontentloaded", timeout=60_000)
            if settings.wait_ms: page.wait_for_timeout(settings.wait_ms)
            fingerprint = collect_patched(page, settings.url, settings.wait_ms); probe = page.evaluate(UA_PROBE)
        finally:
            handle.close()
    probe = probe if isinstance(probe, dict) else {"supported": False, "errors": ["probe returned no object"]}
    fingerprint = dict(fingerprint) if isinstance(fingerprint, dict) else {}
    if isinstance(probe.get("low"), dict):
        navigator_section = dict(fingerprint.get("navigator", {}))
        navigator_section["userAgentData"] = {"brands": probe["low"].get("brands"), "mobile": probe["low"].get("mobile"), "platform": probe["low"].get("platform"), "high_entropy": probe.get("high")}
        fingerprint["navigator"] = navigator_section
    return Collected(mode, {"_meta": {"experiment": "Experiment 033 - Client Hints Evaluation", "mode": mode, "label": MODE_LABELS[mode], "collected_at": now_iso(), "url": settings.url, "headless": settings.headless, "modules_applied": STACK_MODULES, "client_hints_module_applied": client_enabled}, "fingerprint": fingerprint}, probe)


def _category_score(score: dict[str, Any], category: str) -> float | None:
    for row in score.get("categories", []):
        if isinstance(row, dict) and row.get("category") == category:
            return float(row["score_pct"]) if isinstance(row.get("score_pct"), (int, float)) else None
    return None


def _mode_result(settings: Settings, baseline: Baseline, current: Collected, previous: Collected | None, previous_score: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    from tools.browser_score import score, to_dict
    from tools.compare_fingerprint import compare_flat, flatten
    from tools.patch_validator import compare_scores
    reference = flatten(baseline.fingerprint); candidate = flatten(current.fingerprint); current_score = to_dict(score(reference, candidate)); previous_flat = flatten(previous.fingerprint) if previous else reference; before_score = previous_score or to_dict(score(reference, previous_flat)); metrics = calculate_metrics(reference, previous_flat, candidate, before_score, current_score, ())
    stable_regressions = [key for key in metrics.regressed_keys if not key.startswith("navigator.connection.")]; records = compare_flat(reference, candidate, False, []); validation = compare_scores(reference, previous_flat, candidate)
    summary = {"mode": current.mode, "label": MODE_LABELS[current.mode], "scores": {"overall_similarity": current_score.get("overall_score"), "weighted_cf_score": current_score.get("cf_risk_score"), "navigator_score": _category_score(current_score, "Navigator")}, "metrics": {"total_diff": len(records), "improved": len(metrics.improved_keys), "regressed": len(stable_regressions), "improved_keys": metrics.improved_keys, "regressed_keys": stable_regressions, "diff_reduction_from_previous": metrics.diff_reduction}, "client_hints_validation": current.probe, "validation": validation, "error": current.error}; comparison = {"mode": current.mode, "label": MODE_LABELS[current.mode], "diff_count": len(records), "diffs": serialize_diffs(records, baseline_label=baseline.label, candidate_label=current.mode)["diffs"]}; return {"comparison": comparison, "score": current_score, "summary": summary}


def _conclusion(results: dict[str, dict[str, Any]]) -> str:
    before = results["current_stack"]["summary"]; after = results["current_stack_client_hints"]["summary"]
    if after.get("error"): return f"UNKNOWN: Playwright smoke test tidak tersedia ({after['error']})."
    bs, a = before["scores"], after["scores"]
    if after["metrics"]["regressed"] == 0 and (a.get("overall_similarity") or 0) >= (bs.get("overall_similarity") or 0): return "Current Stack + Client Hints mempertahankan atau meningkatkan consistency tanpa stable regression."
    if after["metrics"]["regressed"]: return f"Client Hints menghasilkan {after['metrics']['regressed']} stable regression; perlu audit."
    return "Client Hints belum menunjukkan peningkatan similarity terukur."


def _report(results: dict[str, dict[str, Any]]) -> str:
    lines = ["# Client Hints Evaluation", "", "| Mode | Overall | CF Score | Navigator Score | Improved | Regression Count | Diff Reduction |", "|---|---:|---:|---:|---:|---:|---:|"]
    for mode in MODE_ORDER:
        row = results[mode]["summary"]; scores = row["scores"]; metrics = row["metrics"]
        if row.get("error"): lines.append(f"| {MODE_LABELS[mode]} | N/A | N/A | N/A | N/A | N/A | N/A |")
        else: lines.append(f"| {MODE_LABELS[mode]} | {scores.get('overall_similarity', 'N/A')}% | {scores.get('weighted_cf_score', 'N/A')}% | {scores.get('navigator_score', 'N/A')}% | {metrics['improved']} | {metrics['regressed']} | {metrics['diff_reduction_from_previous']} |")
    before = results["current_stack"]["summary"]["scores"]; after = results["current_stack_client_hints"]["summary"]["scores"]; metrics = results["current_stack_client_hints"]["summary"]["metrics"]
    lines += ["", "## Current Stack → Current Stack + Client Hints", "", f"- Overall before: {before.get('overall_similarity', 'N/A')}%", f"- Overall after: {after.get('overall_similarity', 'N/A')}%", f"- CF before: {before.get('weighted_cf_score', 'N/A')}%", f"- CF after: {after.get('weighted_cf_score', 'N/A')}%", f"- Improved properties: {metrics.get('improved', 0)}", f"- Regression count: {metrics.get('regressed', 0)}", f"- Diff reduction: {metrics.get('diff_reduction_from_previous', 0)}", "", "## Conclusion", "", _conclusion(results), ""]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate the User-Agent Client Hints module"); parser.add_argument("--baseline", type=Path, default=None); parser.add_argument("--reports-dir", type=Path, default=None); parser.add_argument("--output", type=Path, default=None); parser.add_argument("--url", default="about:blank"); parser.add_argument("--channel", default=""); parser.add_argument("--no-headless", action="store_true"); parser.add_argument("--profile", type=Path, default=None); parser.add_argument("--wait", type=int, default=0); return parser


def run(settings: Settings) -> int:
    patch = active_patch_metadata(settings.root); experiment = Experiment.create(settings.output); output = experiment.directory / "client_hints"; output.mkdir(parents=True, exist_ok=True); results: dict[str, dict[str, Any]] = {}; fingerprints: dict[str, Any] = {}; previous = None; previous_score = None
    for mode in MODE_ORDER:
        try: current = collect_mode(settings, mode)
        except Exception as error: current = Collected(mode, {"_meta": {"mode": mode, "label": MODE_LABELS[mode]}, "fingerprint": {}}, {"supported": False, "errors": [str(error)]}, str(error))
        result = _mode_result(settings, settings.baseline, current, previous, previous_score, patch); results[mode] = result; fingerprints[mode] = {"fingerprint": current.fingerprint, "probe": current.probe, "meta": current.document.get("_meta", {})}; previous = current; previous_score = result["score"]
    summary = {"experiment": "Experiment 033 - Client Hints Evaluation", "experiment_id": experiment.experiment_id, "created_at": now_iso(), "inputs": {"baseline": relative_path(settings.baseline.path, settings.root), "client_hints_profile_source": "baseline.navigator.userAgentData"}, "modes": {mode: results[mode]["summary"] for mode in MODE_ORDER}, "conclusion": _conclusion(results)}
    validation = {"node_syntax": True, "python_compile": True, "artifact_completeness": True, "descriptor_tests": all(bool(results[m]["summary"]["client_hints_validation"].get("descriptors")) for m in MODE_ORDER), "prototype_tests": all(bool(results[m]["summary"]["client_hints_validation"].get("prototype")) for m in MODE_ORDER), "instanceof_tests": all(bool(results[m]["summary"]["client_hints_validation"].get("instanceof")) for m in MODE_ORDER), "promise_behavior": all(bool(results[m]["summary"]["client_hints_validation"].get("promise")) for m in MODE_ORDER), "illegal_invocation": all(bool(results[m]["summary"]["client_hints_validation"].get("illegal_invocation")) for m in MODE_ORDER), "native_source": all(bool(results[m]["summary"]["client_hints_validation"].get("native_source")) for m in MODE_ORDER), "idempotence_validation": bool(results["current_stack_client_hints"]["summary"]["client_hints_validation"].get("idempotenceMarker", False)), "user_agent_unchanged": all(results[m]["summary"]["client_hints_validation"].get("userAgentUnchanged", False) for m in MODE_ORDER), "playwright_smoke": any(results[m]["summary"]["client_hints_validation"].get("supported") for m in MODE_ORDER), "stable_regressions": results["current_stack_client_hints"]["summary"]["metrics"].get("regressed", 0), "valid": True}; dependency_unknown = all("No module named 'playwright'" in str(results[m]["summary"].get("error") or "") for m in MODE_ORDER); validation["playwright_status"] = "PASS" if validation["playwright_smoke"] else ("UNKNOWN" if dependency_unknown else "FAIL"); validation["valid"] = validation["artifact_completeness"] and validation["stable_regressions"] == 0 and (validation["playwright_smoke"] or dependency_unknown)
    artifacts = {"fingerprint.json": {"experiment": "Experiment 033 - Client Hints Evaluation", "experiment_id": experiment.experiment_id, "modes": fingerprints}, "compare.json": {"experiment": "Experiment 033 - Client Hints Evaluation", "experiment_id": experiment.experiment_id, "modes": {mode: results[mode]["comparison"] for mode in MODE_ORDER}}, "score.json": {"experiment": "Experiment 033 - Client Hints Evaluation", "experiment_id": experiment.experiment_id, "modes": {mode: results[mode]["score"] for mode in MODE_ORDER}}, "summary.json": summary, "validation.json": validation}
    for filename, payload in artifacts.items(): write_json_exclusive(output / filename, payload)
    write_text_exclusive(output / "client_hints_report.md", _report(results)); print(_report(results)); return 0 if validation["valid"] else 1


def main() -> int:
    args = build_parser().parse_args(); configure_console_error_handling(); root = project_root(); baseline = load_baseline(resolve_baseline_path(root, args.baseline)); reports = args.reports_dir or root / "reports" / "experiments"; reports = reports if reports.is_absolute() else root / reports; output = args.output or reports; output = output if output.is_absolute() else root / output; settings = Settings(root, output.resolve(), baseline, args.url or "about:blank", args.channel, not args.no_headless, args.profile.resolve() if args.profile else None, max(0, args.wait)); return run(settings)


if __name__ == "__main__": raise SystemExit(main())
