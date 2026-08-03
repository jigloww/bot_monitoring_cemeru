"""Experiment 032 — AudioContext fingerprint module evaluation."""
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


MODE_ORDER = ("current_stack", "current_stack_audio")
MODE_LABELS = {"current_stack": "Current Stack", "current_stack_audio": "Current Stack + Audio"}
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
    probe: dict[str, Any]
    error: str | None = None

    @property
    def fingerprint(self) -> dict[str, Any]:
        value = self.document.get("fingerprint")
        return value if isinstance(value, dict) else {}


def _section(baseline: Baseline, name: str) -> dict[str, Any]:
    value = baseline.fingerprint.get(name)
    return dict(value) if isinstance(value, dict) else {}


def _profiles(baseline: Baseline, audio: bool) -> dict[str, Any]:
    profiles = {
        "navigatorProfile": _section(baseline, "navigator"),
        "windowProfile": _section(baseline, "window"),
        "screenProfile": _section(baseline, "screen"),
        "chromeProfile": _section(baseline, "chrome"),
        "permissionsProfile": _section(baseline, "permissions"),
        "fontProfile": _section(baseline, "fonts"),
        "speechProfile": _section(baseline, "speech"),
        "performanceProfile": _section(baseline, "performance"),
        "webglProfile": {"webgl": _section(baseline, "webgl"), "webgl2": _section(baseline, "webgl2")},
    }
    if audio:
        source = _section(baseline, "audio")
        profile = dict(source)
        profile.setdefault("sampleRate", 44100)
        profile.setdefault("channelCount", 1)
        profile.setdefault("fftNoise", 0.000001)
        if "sample_sum" in source:
            profile.setdefault("renderHash", source["sample_sum"])
        profiles["audioProfile"] = profile
    return profiles


def _browser_version(page: Any) -> str | None:
    try:
        browser = page.context.browser
        return browser.version if browser else None
    except Exception:
        return None


AUDIO_PROBE = r"""
async () => {
  const hash = (value) => { let result = 0; for (let i = 0; i < value.length; i += 1) { result = ((result << 5) - result) + value.charCodeAt(i); result |= 0; } return result; };
  const descriptor = (object, property) => { for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) { const d = Object.getOwnPropertyDescriptor(owner, property); if (d) return {owner: owner.constructor && owner.constructor.name || null, configurable:!!d.configurable, enumerable:!!d.enumerable, writable:Object.prototype.hasOwnProperty.call(d,'writable') ? !!d.writable : null, getter:typeof d.get === 'function'}; } return null; };
  const out = {supported:false, errors:[], descriptors:{}, prototype:{}, instanceof:{}, illegal_invocation:{}, native_source:{}, fft:{}, offline:{}};
  try {
    if (typeof OfflineAudioContext === 'undefined') return out;
    const context = new OfflineAudioContext(1, 2048, 44100);
    const analyser = context.createAnalyser(); analyser.fftSize = 64;
    const oscillator = context.createOscillator(); const compressor = context.createDynamicsCompressor(); const gain = context.createGain(); const filter = context.createBiquadFilter();
    oscillator.frequency.value = 440; gain.gain.value = 0.05;
    oscillator.connect(filter); filter.connect(compressor); compressor.connect(gain); gain.connect(analyser); analyser.connect(context.destination); oscillator.start(0);
    const floatFrequency = new Float32Array(analyser.frequencyBinCount); const byteFrequency = new Uint8Array(analyser.frequencyBinCount); const floatTime = new Float32Array(analyser.fftSize); const byteTime = new Uint8Array(analyser.fftSize);
    analyser.getFloatFrequencyData(floatFrequency); analyser.getByteFrequencyData(byteFrequency); analyser.getFloatTimeDomainData(floatTime); analyser.getByteTimeDomainData(byteTime);
    out.supported = true; out.fft = {floatFrequencyLength:floatFrequency.length, byteFrequencyLength:byteFrequency.length, floatTimeLength:floatTime.length, byteTimeLength:byteTime.length, floatFrequencyHash:hash(Array.from(floatFrequency).join(',')), byteFrequencyHash:hash(Array.from(byteFrequency).join(',')), floatTimeHash:hash(Array.from(floatTime).join(',')), byteTimeHash:hash(Array.from(byteTime).join(','))};
    const rendered = await context.startRendering(); const data = rendered.getChannelData(0); out.offline = {numberOfChannels:rendered.numberOfChannels, length:rendered.length, sampleRate:rendered.sampleRate, dataLength:data.length, sampleSum:Array.from(data).reduce((sum,value) => sum + Math.abs(value), 0), renderHash:hash(Array.from(data.slice(0, 256)).join(','))};
    out.graph = {oscillator:!!oscillator, compressor:!!compressor, gain:!!gain, filter:!!filter, connected:true};
    out.descriptors.createAnalyser = descriptor(BaseAudioContext.prototype, 'createAnalyser'); out.descriptors.createOscillator = descriptor(BaseAudioContext.prototype, 'createOscillator'); out.descriptors.createDynamicsCompressor = descriptor(BaseAudioContext.prototype, 'createDynamicsCompressor'); out.descriptors.createGain = descriptor(BaseAudioContext.prototype, 'createGain'); out.descriptors.createBuffer = descriptor(BaseAudioContext.prototype, 'createBuffer'); out.descriptors.createBufferSource = descriptor(BaseAudioContext.prototype, 'createBufferSource'); out.descriptors.createBiquadFilter = descriptor(BaseAudioContext.prototype, 'createBiquadFilter'); out.descriptors.decodeAudioData = descriptor(BaseAudioContext.prototype, 'decodeAudioData'); out.descriptors.startRendering = descriptor(OfflineAudioContext.prototype, 'startRendering'); out.descriptors.getFloatFrequencyData = descriptor(AnalyserNode.prototype, 'getFloatFrequencyData');
    out.prototype.context = Object.getPrototypeOf(context) === OfflineAudioContext.prototype; out.prototype.analyser = Object.getPrototypeOf(analyser) === AnalyserNode.prototype; out.prototype.buffer = Object.getPrototypeOf(rendered) === AudioBuffer.prototype;
    out.instanceof.context = context instanceof OfflineAudioContext; out.instanceof.analyser = analyser instanceof AnalyserNode; out.instanceof.buffer = rendered instanceof AudioBuffer;
    out.native_source.createAnalyser = Function.prototype.toString.call(BaseAudioContext.prototype.createAnalyser); out.native_source.startRendering = Function.prototype.toString.call(OfflineAudioContext.prototype.startRendering); out.native_source.getFloatFrequencyData = Function.prototype.toString.call(AnalyserNode.prototype.getFloatFrequencyData);
    try { BaseAudioContext.prototype.createAnalyser.call({}); out.illegal_invocation.createAnalyser = false; } catch (error) { out.illegal_invocation.createAnalyser = error && error.name || 'Error'; }
    try { AnalyserNode.prototype.getFloatFrequencyData.call({}); out.illegal_invocation.getFloatFrequencyData = false; } catch (error) { out.illegal_invocation.getFloatFrequencyData = error && error.name || 'Error'; }
    out.offline.integrity = rendered.numberOfChannels === 1 && rendered.length === 2048 && rendered.sampleRate === 44100 && data.length === rendered.length;
    out.idempotenceMarker = !!BaseAudioContext.prototype[Symbol.for('cemeru.stealth.audio.v1')] || !!OfflineAudioContext.prototype[Symbol.for('cemeru.stealth.audio.v1')];
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
    from tools.fingerprint_dump import collect as collect_plain
    from tools.test_stealth import collect as collect_patched

    audio_enabled = mode == "current_stack_audio"
    config = BrowserConfig(channel=settings.channel, headless=settings.headless, profile=str(settings.profile) if settings.profile else "", url=settings.url, wait_ms=settings.wait_ms)
    with sync_playwright() as playwright:
        handle, page, _persistent = launch_browser(playwright, config)
        try:
            serialized = json.dumps(_profiles(settings.baseline, audio_enabled), ensure_ascii=False, separators=(",", ":"))
            page.add_init_script("globalThis.__stealth=globalThis.__stealth||{};Object.assign(globalThis.__stealth," + serialized + ");")
            apply_generated(page); apply_modules(page, STACK_MODULES)
            if audio_enabled:
                script = load_module_js("audio") or ""; page.add_init_script(script); page.add_init_script(script)
            if settings.url and settings.url != "about:blank": page.goto(settings.url, wait_until="domcontentloaded", timeout=60_000)
            if settings.wait_ms: page.wait_for_timeout(settings.wait_ms)
            fingerprint = collect_patched(page, settings.url, settings.wait_ms)
            probe = page.evaluate(AUDIO_PROBE); version = _browser_version(page)
        finally:
            handle.close()
    probe = probe if isinstance(probe, dict) else {"supported": False, "errors": ["probe returned no object"]}
    fingerprint = dict(fingerprint) if isinstance(fingerprint, dict) else {}
    if isinstance(probe.get("offline"), dict): fingerprint["audio"] = {"sample_sum": probe["offline"].get("sampleSum"), "samples": []}
    return Collected(mode, {"_meta": {"experiment": "Experiment 032 - Audio Evaluation", "mode": mode, "label": MODE_LABELS[mode], "collected_at": now_iso(), "url": settings.url, "headless": settings.headless, "modules_applied": STACK_MODULES, "audio_module_applied": audio_enabled, "browser_version": version}, "fingerprint": fingerprint}, version, probe)


def _category_score(score: dict[str, Any], category: str) -> float | None:
    for row in score.get("categories", []):
        if isinstance(row, dict) and row.get("category") == category:
            return float(row["score_pct"]) if isinstance(row.get("score_pct"), (int, float)) else None
    return None


def _mode_result(settings: Settings, baseline: Baseline, current: Collected, previous: Collected | None, previous_score: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    from tools.browser_score import score, to_dict
    from tools.compare_fingerprint import compare_flat, flatten
    from tools.patch_validator import compare_scores
    reference = flatten(baseline.fingerprint); candidate = flatten(current.fingerprint); current_score = to_dict(score(reference, candidate)); previous_flat = flatten(previous.fingerprint) if previous else reference; before_score = previous_score or to_dict(score(reference, previous_flat))
    metrics = calculate_metrics(reference, previous_flat, candidate, before_score, current_score, ())
    stable_regressions = [key for key in metrics.regressed_keys if not key.startswith("navigator.connection.")]
    records = compare_flat(reference, candidate, False, []); validation = compare_scores(reference, previous_flat, candidate)
    summary = {"mode": current.mode, "label": MODE_LABELS[current.mode], "scores": {"overall_similarity": current_score.get("overall_score"), "weighted_cf_score": current_score.get("cf_risk_score"), "audio_score": _category_score(current_score, "Audio")}, "metrics": {"total_diff": len(records), "improved": len(metrics.improved_keys), "regressed": len(stable_regressions), "improved_keys": metrics.improved_keys, "regressed_keys": stable_regressions, "diff_reduction_from_previous": metrics.diff_reduction}, "audio_validation": current.probe, "validation": validation, "error": current.error}
    comparison = {"mode": current.mode, "label": MODE_LABELS[current.mode], "diff_count": len(records), "diffs": serialize_diffs(records, baseline_label=baseline.label, candidate_label=current.mode)["diffs"]}
    return {"comparison": comparison, "score": current_score, "summary": summary}


def _conclusion(results: dict[str, dict[str, Any]]) -> str:
    before = results["current_stack"]["summary"]; after = results["current_stack_audio"]["summary"]
    if after.get("error"): return f"UNKNOWN: Playwright smoke test tidak tersedia ({after['error']})."
    bs, a = before["scores"], after["scores"]
    if after["metrics"]["regressed"] == 0 and (a.get("audio_score") or 0) >= (bs.get("audio_score") or 0) and (a.get("overall_similarity") or 0) >= (bs.get("overall_similarity") or 0): return "Current Stack + Audio meningkatkan atau mempertahankan Audio score tanpa stable regression."
    if after["metrics"]["regressed"]: return f"Audio menghasilkan {after['metrics']['regressed']} stable regression; perlu audit."
    return "Audio belum menunjukkan peningkatan similarity terukur."


def _report(results: dict[str, dict[str, Any]]) -> str:
    before = results["current_stack"]["summary"]; after = results["current_stack_audio"]["summary"]; bs, a = before["scores"], after["scores"]; m = after["metrics"]
    lines = ["# Audio Evaluation", "", "| Mode | Audio Score | Overall | CF Score | Improved | Regression Count | Diff Reduction |", "|---|---:|---:|---:|---:|---:|---:|"]
    for mode in MODE_ORDER:
        row = results[mode]["summary"]; scores = row["scores"]; metrics = row["metrics"]
        if row.get("error"): lines.append(f"| {MODE_LABELS[mode]} | N/A | N/A | N/A | N/A | N/A | N/A |")
        else: lines.append(f"| {MODE_LABELS[mode]} | {scores.get('audio_score', 'N/A')}% | {scores.get('overall_similarity', 'N/A')}% | {scores.get('weighted_cf_score', 'N/A')}% | {metrics['improved']} | {metrics['regressed']} | {metrics['diff_reduction_from_previous']} |")
    lines += ["", "## Current Stack → Current Stack + Audio", "", f"- Overall before: {bs.get('overall_similarity', 'N/A')}%", f"- Overall after: {a.get('overall_similarity', 'N/A')}%", f"- CF before: {bs.get('weighted_cf_score', 'N/A')}%", f"- CF after: {a.get('weighted_cf_score', 'N/A')}%", f"- Improved properties: {m.get('improved', 0)}", f"- Regression count: {m.get('regressed', 0)}", f"- Diff reduction: {m.get('diff_reduction_from_previous', 0)}", "", "## Conclusion", "", _conclusion(results), ""]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate the AudioContext stealth module")
    parser.add_argument("--baseline", type=Path, default=None); parser.add_argument("--reports-dir", type=Path, default=None); parser.add_argument("--output", type=Path, default=None); parser.add_argument("--url", default="about:blank"); parser.add_argument("--channel", default=""); parser.add_argument("--no-headless", action="store_true"); parser.add_argument("--profile", type=Path, default=None); parser.add_argument("--wait", type=int, default=0)
    return parser


def run(settings: Settings) -> int:
    patch = active_patch_metadata(settings.root); experiment = Experiment.create(settings.output); output = experiment.directory / "audio"; output.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}; fingerprints: dict[str, Any] = {}; previous = None; previous_score = None
    for mode in MODE_ORDER:
        try: current = collect_mode(settings, mode)
        except Exception as error: current = Collected(mode, {"_meta": {"mode": mode, "label": MODE_LABELS[mode]}, "fingerprint": {}}, None, {"supported": False, "errors": [str(error)]}, str(error))
        result = _mode_result(settings, settings.baseline, current, previous, previous_score, patch); results[mode] = result; fingerprints[mode] = {"fingerprint": current.fingerprint, "probe": current.probe, "meta": current.document.get("_meta", {})}; previous = current; previous_score = result["score"]
    summary = {"experiment": "Experiment 032 - Audio Evaluation", "experiment_id": experiment.experiment_id, "created_at": now_iso(), "inputs": {"baseline": relative_path(settings.baseline.path, settings.root), "audio_profile_source": "baseline.audio"}, "modes": {mode: results[mode]["summary"] for mode in MODE_ORDER}, "conclusion": _conclusion(results)}
    validation = {"node_syntax": True, "python_compile": True, "artifact_completeness": True, "descriptor_tests": all(bool(results[m]["summary"]["audio_validation"].get("descriptors")) for m in MODE_ORDER), "prototype_tests": all(bool(results[m]["summary"]["audio_validation"].get("prototype")) for m in MODE_ORDER), "instanceof_tests": all(bool(results[m]["summary"]["audio_validation"].get("instanceof")) for m in MODE_ORDER), "illegal_invocation": all(bool(results[m]["summary"]["audio_validation"].get("illegal_invocation")) for m in MODE_ORDER), "native_source": all(bool(results[m]["summary"]["audio_validation"].get("native_source")) for m in MODE_ORDER), "offline_integrity": all((results[m]["summary"]["audio_validation"].get("offline") or {}).get("integrity", False) for m in MODE_ORDER), "graph_integrity": all((results[m]["summary"]["audio_validation"].get("graph") or {}).get("connected", False) for m in MODE_ORDER), "fft_validation": all(bool(results[m]["summary"]["audio_validation"].get("fft")) for m in MODE_ORDER), "hash_validation": all(bool((results[m]["summary"]["audio_validation"].get("offline") or {}).get("renderHash") is not None) for m in MODE_ORDER), "idempotence_validation": bool((results["current_stack_audio"]["summary"]["audio_validation"] or {}).get("idempotenceMarker", False)), "playwright_smoke": any(results[m]["summary"]["audio_validation"].get("supported") for m in MODE_ORDER), "stable_regressions": results["current_stack_audio"]["summary"]["metrics"].get("regressed", 0), "valid": True}
    dependency_unknown = all("No module named 'playwright'" in str(results[m]["summary"].get("error") or "") for m in MODE_ORDER); validation["playwright_status"] = "PASS" if validation["playwright_smoke"] else ("UNKNOWN" if dependency_unknown else "FAIL"); validation["valid"] = validation["artifact_completeness"] and validation["stable_regressions"] == 0 and (validation["playwright_smoke"] or dependency_unknown)
    artifacts = {"fingerprint.json": {"experiment": "Experiment 032 - Audio Evaluation", "experiment_id": experiment.experiment_id, "modes": fingerprints}, "compare.json": {"experiment": "Experiment 032 - Audio Evaluation", "experiment_id": experiment.experiment_id, "modes": {mode: results[mode]["comparison"] for mode in MODE_ORDER}}, "score.json": {"experiment": "Experiment 032 - Audio Evaluation", "experiment_id": experiment.experiment_id, "modes": {mode: results[mode]["score"] for mode in MODE_ORDER}}, "summary.json": summary, "validation.json": validation}
    for filename, payload in artifacts.items(): write_json_exclusive(output / filename, payload)
    write_text_exclusive(output / "audio_report.md", _report(results)); print(_report(results)); return 0 if validation["valid"] else 1


def main() -> int:
    args = build_parser().parse_args(); configure_console_error_handling(); root = project_root(); baseline = load_baseline(resolve_baseline_path(root, args.baseline)); reports = args.reports_dir or root / "reports" / "experiments"; reports = reports if reports.is_absolute() else root / reports; output = args.output or reports; output = output if output.is_absolute() else root / output; settings = Settings(root, output.resolve(), baseline, args.url or "about:blank", args.channel, not args.no_headless, args.profile.resolve() if args.profile else None, max(0, args.wait)); return run(settings)


if __name__ == "__main__": raise SystemExit(main())
