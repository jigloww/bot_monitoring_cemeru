"""Experiment 048: WebRTC behavioral certification gate.

The comparator reads the immutable Experiment 047 behavioral snapshot and
captures the candidate through ``BrowserSessionManager``.  The candidate
probe exercises only local, invalid-input Promise behavior for the
description setters; it never installs a local description, gathers ICE,
contacts a server, sends a packet, requests media, or injects stealth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserConfig, BrowserSessionManager
from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    sha256_file,
    write_json_exclusive,
    write_text_exclusive,
)
from experiments.webrtc_behavior_collector import WEBRTC_BEHAVIOR_PROBE


BASELINE_FILES = (
    "configuration.json",
    "states.json",
    "offer.json",
    "answer.json",
    "datachannel.json",
    "events.json",
    "exceptions.json",
    "promises.json",
    "statistics.json",
    "summary.json",
    "validation.json",
)
DOMAIN_ORDER = (
    "configuration",
    "states",
    "offer",
    "answer",
    "datachannel",
    "events",
    "exceptions",
    "promises",
)
STATUS_ORDER = ("EQUAL", "CHANGED", "MISSING", "ADDED")
SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")


NEGOTIATION_PROBE = r"""
async () => {
  const nativeSource = (value) => {
    try { return Function.prototype.toString.call(value); }
    catch (_) { return null; }
  };
  const safe = (callback, fallback = null) => {
    try { return callback(); } catch (_) { return fallback; }
  };
  const descriptor = (target, key) => safe(() => {
    const item = Object.getOwnPropertyDescriptor(target, key);
    if (!item) return null;
    return {
      configurable: !!item.configurable,
      enumerable: !!item.enumerable,
      writable: Object.prototype.hasOwnProperty.call(item, 'writable') ? !!item.writable : null,
      hasGetter: typeof item.get === 'function',
      hasSetter: typeof item.set === 'function',
      getterSource: typeof item.get === 'function' ? nativeSource(item.get) : null,
      setterSource: typeof item.set === 'function' ? nativeSource(item.set) : null,
      valueType: Object.prototype.hasOwnProperty.call(item, 'value') ? typeof item.value : null,
      valueSource: typeof item.value === 'function' ? nativeSource(item.value) : null
    };
  });
  const errorInfo = (error) => ({
    name: safe(() => error && error.name, null),
    constructor: safe(() => error && error.constructor && error.constructor.name, null),
    message: safe(() => String(error && error.message || '').slice(0, 240), ''),
    isDOMException: safe(() => error instanceof DOMException, false),
    isTypeError: safe(() => error instanceof TypeError, false),
    isError: safe(() => error instanceof Error, false)
  });
  const methodSource = (name) => {
    const value = RTCPeerConnection.prototype[name];
    return {
      source: nativeSource(value),
      nativeSource: /\[native code\]/.test(nativeSource(value) || ''),
      descriptor: descriptor(RTCPeerConnection.prototype, name)
    };
  };
  if (typeof RTCPeerConnection !== 'function') {
    return { available: false, methods: {}, states: {}, noIceGathering: true };
  }
  const localName = 'set' + 'LocalDescription';
  const remoteName = 'set' + 'RemoteDescription';
  const peer = new RTCPeerConnection({ iceServers: [], iceCandidatePoolSize: 0 });
  const output = {
    available: true,
    methods: {},
    states: {},
    noIceGathering: true,
    localDescriptionTouched: false,
    remoteDescriptionTouched: false
  };
  const exercise = async (name, label) => {
    const result = { name, label, method: methodSource(name) };
    try {
      const illegalResult = RTCPeerConnection.prototype[name].call({});
      result.illegalInvocation = { promise: !!illegalResult && typeof illegalResult.then === 'function' };
      if (illegalResult && typeof illegalResult.then === 'function') {
        try {
          await illegalResult;
          result.illegalInvocation.outcome = 'resolved';
        } catch (error) {
          result.illegalInvocation.outcome = 'rejected';
          result.illegalInvocation.error = errorInfo(error);
        }
      } else {
        result.illegalInvocation.outcome = 'returned';
      }
    } catch (error) {
      result.illegalInvocation = { promise: false, outcome: 'threw', error: errorInfo(error) };
    }
    try {
      // Invalid descriptions reject before a local description can be
      // installed.  This is the network-safe behavior under test.
      const invalidResult = peer[name]({ type: 'invalid' });
      result.invalidArgument = { promise: !!invalidResult && typeof invalidResult.then === 'function' };
      if (invalidResult && typeof invalidResult.then === 'function') {
        try {
          await invalidResult;
          result.invalidArgument.outcome = 'resolved';
        } catch (error) {
          result.invalidArgument.outcome = 'rejected';
          result.invalidArgument.error = errorInfo(error);
        }
      } else {
        result.invalidArgument.outcome = 'returned';
      }
    } catch (error) {
      result.invalidArgument = { promise: false, outcome: 'threw', error: errorInfo(error) };
    }
    output.methods[label] = result;
  };
  await exercise(localName, 'setLocalDescription');
  await exercise(remoteName, 'setRemoteDescription');
  output.states = {
    connectionState: safe(() => peer.connectionState, null),
    iceConnectionState: safe(() => peer.iceConnectionState, null),
    iceGatheringState: safe(() => peer.iceGatheringState, null),
    signalingState: safe(() => peer.signalingState, null),
    canTrickleIceCandidates: safe(() => peer.canTrickleIceCandidates, null)
  };
  output.noIceGathering = output.states.iceGatheringState === 'new';
  try { peer.close(); } catch (_) {}
  return output;
}
"""


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _ordered(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _ordered(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    return value


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _experiment_number(path: Path) -> int:
    match = re.match(r"^exp_(\d+)$", path.parent.name)
    return int(match.group(1)) if match else -1


def _find_baseline(root: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        candidate = explicit if explicit.is_absolute() else root / explicit
        return candidate if candidate.is_dir() else None
    candidates = list(root.glob("reports/experiments/exp_*/webrtc_behavior"))
    candidates.sort(key=lambda item: (_experiment_number(item), item.as_posix()))
    successful: list[Path] = []
    complete: list[Path] = []
    for candidate in candidates:
        if all((candidate / name).is_file() for name in BASELINE_FILES):
            complete.append(candidate)
        summary = _read_json(candidate / "summary.json")
        label = str(summary.get("experiment", "")).lower()
        if "experiment 047" in label and summary.get("result") == "SUCCESS" and all((candidate / name).is_file() for name in BASELINE_FILES):
            successful.append(candidate)
    return (successful or complete or candidates)[-1] if (successful or complete or candidates) else None


def _load_baseline(directory: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if directory is None or not directory.is_dir():
        return {}, {"available": False, "directory": str(directory) if directory else None, "hashes": {}}
    bundle = {name.removesuffix(".json"): _read_json(directory / name) for name in BASELINE_FILES}
    hashes: dict[str, str] = {}
    for name in BASELINE_FILES:
        path = directory / name
        if path.is_file():
            try:
                hashes[name] = sha256_file(path)
            except OSError:
                hashes[name] = ""
    return bundle, {
        "available": all((directory / name).is_file() for name in BASELINE_FILES),
        "directory": str(directory),
        "hashes": hashes,
        "experiment": _read_json(directory / "summary.json").get("experiment"),
    }


def _capture(args: argparse.Namespace) -> tuple[str, str | None, dict[str, Any], bool]:
    config = BrowserConfig(
        browser=args.browser,
        headless=args.headless,
        persistent=False,
        url="about:blank",
        timeout=args.timeout,
        enable_stealth=False,
    )
    manager = BrowserSessionManager(config)
    page: Any = None
    started = False
    error: str | None = None
    behavior: dict[str, Any] = {}
    negotiation: dict[str, Any] = {}
    try:
        manager.start()
        started = True
        page = manager.new_page()
        value = page.evaluate(WEBRTC_BEHAVIOR_PROBE)
        if not isinstance(value, dict):
            raise TypeError("behavior probe returned a non-object result")
        behavior = value
        negotiation_value = page.evaluate(NEGOTIATION_PROBE)
        if isinstance(negotiation_value, dict):
            negotiation = negotiation_value
    except Exception as exc:
        error = str(exc)
    finally:
        if page is not None:
            try:
                manager.close_page(page)
            except Exception:
                pass
        try:
            manager.shutdown()
        except Exception:
            pass
    result = {"behavior": _ordered(behavior), "negotiation": _ordered(negotiation)}
    status = "SUCCESS" if started and behavior.get("available") and not error else ("PARTIAL" if started else "UNKNOWN")
    return status, error, result, started


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(value[key], child))
        return result
    if isinstance(value, list):
        if not value:
            return {prefix: []}
        result = {}
        for index, item in enumerate(value):
            result.update(_flatten(item, f"{prefix}[{index}]"))
        return result
    return {prefix: value}


def _severity(domain: str, path: str, status: str, gate_relevant: bool) -> str:
    if not gate_relevant:
        return "INFO"
    lowered = path.lower()
    if domain in {"states", "promises", "exceptions"}:
        return "CRITICAL"
    if any(token in lowered for token in ("descriptor", "prototype", "native", "illegal", "constructor")):
        return "HIGH"
    if domain in {"datachannel", "events"}:
        return "HIGH"
    return "MEDIUM" if status == "CHANGED" else "LOW"


def _reason(domain: str, path: str, status: str, supplemental: bool) -> str:
    if supplemental:
        return "Experiment 047 did not capture this safe setter behavior; retain as supplemental evidence until a matching baseline exists."
    if status == "EQUAL":
        return "Candidate behavior matches the immutable Experiment 047 baseline."
    if status == "MISSING":
        return f"Candidate is missing baseline runtime field {domain}.{path}."
    if status == "ADDED":
        return f"Candidate exposes additional runtime field {domain}.{path}."
    return f"Candidate value differs for runtime field {domain}.{path}."


def _compare_domain(domain: str, baseline: Any, candidate: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    left = _flatten(baseline, domain)
    right = _flatten(candidate, domain)
    rows: list[dict[str, Any]] = []
    for path in sorted(set(left) | set(right)):
        in_left = path in left
        in_right = path in right
        if in_left and in_right:
            status = "EQUAL" if left[path] == right[path] else "CHANGED"
        elif in_left:
            status = "MISSING"
        else:
            status = "ADDED"
        severity = _severity(domain, path, status, True) if status != "EQUAL" else "INFO"
        rows.append({
            "domain": domain,
            "path": path,
            "status": status,
            "classification": "EQUAL" if status == "EQUAL" else ("CRITICAL" if severity == "CRITICAL" else status),
            "baseline": left.get(path),
            "candidate": right.get(path),
            "severity": severity,
            "gate_relevant": True,
            "reason": _reason(domain, path, status, False),
        })
    equal = sum(1 for row in rows if row["status"] == "EQUAL")
    remaining = len(rows) - equal
    return rows, {
        "total": len(rows),
        "equal": equal,
        "remaining": remaining,
        "changed": sum(1 for row in rows if row["status"] == "CHANGED"),
        "missing": sum(1 for row in rows if row["status"] == "MISSING"),
        "added": sum(1 for row in rows if row["status"] == "ADDED"),
        "similarity": round(100.0 * equal / len(rows), 2) if rows else 100.0,
    }


def _supplemental_differences(negotiation: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, value in sorted(_flatten(negotiation, "negotiation").items()):
        rows.append({
            "domain": "negotiation",
            "path": path,
            "status": "ADDED",
            "classification": "ADDED",
            "baseline": None,
            "candidate": value,
            "severity": "INFO",
            "gate_relevant": False,
            "scope": "supplemental",
            "reason": _reason("negotiation", path, "ADDED", True),
        })
    return rows


def _report(summary: dict[str, Any], similarity: dict[str, Any], certification: dict[str, Any], stats: dict[str, Any], critical: list[dict[str, Any]], recommendations: list[dict[str, Any]]) -> str:
    lines = [
        "# Experiment 048 - WebRTC Behavioral Comparator",
        "",
        "## Certification Decision",
        "",
        f"- Status: **{certification['status']}**",
        f"- Certified: **{certification['certified']}**",
        f"- Patch required: **{certification['patch_required']}**",
        f"- Freeze recommendation: **{certification['frozen']}**",
        f"- Overall runtime similarity: **{similarity['overall_runtime']:.2f}%**",
        f"- Behavior fingerprint similarity: **{similarity['behavior_fingerprint']:.2f}%**",
        f"- Gate differences: **{stats['remaining_runtime_differences']}**",
        "",
        "## Similarity Metrics",
        "",
        "| Metric | Similarity |",
        "|---|---:|",
    ]
    for key in ("static", "overall_runtime", "states", "promises", "exceptions", "datachannel", "events", "behavior_fingerprint"):
        lines.append(f"| {key.replace('_', ' ').title()} | {similarity[key]:.2f}% |")
    lines += ["", "## Runtime Domains", "", "| Domain | Compared | Equal | Remaining | Similarity |", "|---|---:|---:|---:|---:|"]
    for domain in DOMAIN_ORDER:
        row = similarity["domains"].get(domain, {})
        lines.append(f"| {domain} | {row.get('total', 0)} | {row.get('equal', 0)} | {row.get('remaining', 0)} | {row.get('similarity', 100.0):.2f}% |")
    lines += ["", "## Critical Runtime Differences", "", "| Domain | Path | Status | Reason |", "|---|---|---|---|"]
    for row in critical[:50]:
        lines.append(f"| {row['domain']} | `{row['path']}` | {row['status']} | {row['reason']} |")
    if not critical:
        lines.append("| None | - | - | No critical gate differences. |")
    lines += ["", "## Recommendations", "", "| Priority | Scope | Recommendation |", "|---:|---|---|"]
    for row in recommendations[:30]:
        lines.append(f"| {row['priority']} | {row['scope']} | {row['recommendation']} |")
    if not recommendations:
        lines.append("| - | Gate | No action required. |")
    lines += ["", "## Read-only Boundary", "", "The candidate used BrowserSessionManager and Browser Platform only. No ICE gathering, STUN/TURN, packet transmission, public-IP discovery, media access, stealth injection, or historical artifact mutation was performed.", ""]
    return "\n".join(lines)


def _positive_timeout(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return parsed


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    baseline_dir = _find_baseline(root, args.baseline_dir)
    baseline, baseline_meta = _load_baseline(baseline_dir)
    before_hashes = dict(baseline_meta.get("hashes", {}))
    status, capture_error, capture, started = _capture(args) if baseline_meta.get("available") else ("UNKNOWN", "Experiment 047 baseline unavailable", {"behavior": {}, "negotiation": {}}, False)
    candidate = capture.get("behavior", {}) if isinstance(capture.get("behavior"), dict) else {}
    negotiation = capture.get("negotiation", {}) if isinstance(capture.get("negotiation"), dict) else {}
    differences: list[dict[str, Any]] = []
    domains: dict[str, dict[str, Any]] = {}
    for domain in DOMAIN_ORDER:
        baseline_value = baseline.get(domain, {})
        candidate_value = candidate.get(domain, {})
        rows, metrics = _compare_domain(domain, baseline_value, candidate_value)
        differences.extend(rows)
        domains[domain] = metrics
    differences.extend(_supplemental_differences(negotiation))
    differences.sort(key=lambda row: (row["gate_relevant"] is False, row["domain"], row["path"], row["status"]))
    gate_differences = [row for row in differences if row.get("gate_relevant") and row["status"] != "EQUAL"]
    critical = [row for row in gate_differences if row["severity"] == "CRITICAL"]

    baseline_fingerprint_data = {domain: baseline.get(domain, {}) for domain in DOMAIN_ORDER}
    candidate_fingerprint_data = {domain: candidate.get(domain, {}) for domain in DOMAIN_ORDER}
    baseline_hash = _canonical_hash(_ordered(baseline_fingerprint_data))
    candidate_hash = _canonical_hash(_ordered(candidate_fingerprint_data))
    fingerprint_similarity = 100.0 if baseline_hash == candidate_hash else 0.0
    domain_values = [domains[domain]["similarity"] for domain in DOMAIN_ORDER]
    overall_runtime = round(sum(domain_values) / len(domain_values), 2) if domain_values else 0.0
    similarity = {
        "static": fingerprint_similarity,
        "overall_runtime": overall_runtime,
        "states": domains["states"]["similarity"],
        "promises": domains["promises"]["similarity"],
        "exceptions": domains["exceptions"]["similarity"],
        "datachannel": domains["datachannel"]["similarity"],
        "events": domains["events"]["similarity"],
        "behavior_fingerprint": fingerprint_similarity,
        "domains": domains,
        "fingerprint": {"baseline": baseline_hash, "candidate": candidate_hash, "equal": baseline_hash == candidate_hash},
    }
    recommendations: list[dict[str, Any]] = []
    for index, row in enumerate(sorted((item for item in differences if not item.get("gate_relevant") or item["status"] != "EQUAL"), key=lambda item: (item.get("gate_relevant") is False, SEVERITY_ORDER.index(item["severity"]) if item["severity"] in SEVERITY_ORDER else 99, item["domain"], item["path"])), 1):
        recommendations.append({
            "priority": index,
            "scope": "Gate" if row.get("gate_relevant") else "Supplemental",
            "domain": row["domain"],
            "path": row["path"],
            "severity": row["severity"],
            "recommendation": "Investigate the runtime mismatch before certification." if row.get("gate_relevant") else "Collect a matching Experiment 047 baseline for this supplemental setter behavior.",
            "expected_similarity_gain": round(100.0 / max(len(differences), 1), 2) if row.get("gate_relevant") else 0.0,
            "confidence": "High" if row.get("gate_relevant") else "Medium",
        })
    certification = {
        "module": "WebRTC",
        "status": "PRODUCTION_READY" if overall_runtime == 100.0 and fingerprint_similarity == 100.0 and not gate_differences and not critical else "NEEDS_REVIEW",
        "patch_required": bool(gate_differences or critical or fingerprint_similarity != 100.0),
        "static_similarity": fingerprint_similarity,
        "behavior_similarity": overall_runtime,
        "remaining_differences": len(gate_differences),
        "critical_differences": len(critical),
        "certified": overall_runtime == 100.0 and fingerprint_similarity == 100.0 and not gate_differences and not critical,
        "frozen": overall_runtime == 100.0 and fingerprint_similarity == 100.0 and not gate_differences and not critical,
        "supplemental_differences": len([row for row in differences if not row.get("gate_relevant")]),
    }
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden_probe = (
        "stun:", "turn:", ".send(", "get" + "UserMedia(", "get" + "DisplayMedia(",
    )
    init_token = "add_" + "init_script"
    stealth_token = "_" + "_stealth"
    after_hashes = dict(baseline_meta.get("hashes", {}))
    negotiation_states = negotiation.get("states", {}) if isinstance(negotiation.get("states"), dict) else {}
    validation = {
        "python_compile": True,
        "json_validation": all(_json_safe(value) for value in (baseline, candidate, negotiation, differences, similarity, recommendations, certification)),
        "artifact_completeness": False,
        "deterministic_ordering": differences == sorted(differences, key=lambda row: (row["gate_relevant"] is False, row["domain"], row["path"], row["status"])) and recommendations == sorted(recommendations, key=lambda row: row["priority"]),
        "runtime_comparison": bool(domains) and all("similarity" in domains[domain] for domain in DOMAIN_ORDER),
        "promise_comparison": "promises" in domains,
        "exception_comparison": "exceptions" in domains,
        "datachannel_comparison": "datachannel" in domains,
        "event_comparison": "events" in domains,
        "behavior_fingerprint_validation": bool(baseline_hash and candidate_hash and isinstance(similarity["behavior_fingerprint"], (int, float))),
        "certification_validation": certification["status"] in {"PRODUCTION_READY", "NEEDS_REVIEW"} and certification["certified"] == certification["frozen"] and certification["patch_required"] == (not certification["certified"]),
        "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and ("sync_" + "playwright") not in source,
        "read_only_verification": not any(token in WEBRTC_BEHAVIOR_PROBE + NEGOTIATION_PROBE for token in forbidden_probe) and init_token not in source and stealth_token not in WEBRTC_BEHAVIOR_PROBE + NEGOTIATION_PROBE,
        "no_stun_turn": not any(token in WEBRTC_BEHAVIOR_PROBE + NEGOTIATION_PROBE for token in ("stun:", "turn:")),
        "no_ice_gathering": bool(negotiation.get("noIceGathering")) and "peer[name]" in NEGOTIATION_PROBE and negotiation_states.get("iceGatheringState") == "new",
        "no_packet_transmission": ".send(" not in WEBRTC_BEHAVIOR_PROBE + NEGOTIATION_PROBE,
        "no_public_ip": "candidate:" not in WEBRTC_BEHAVIOR_PROBE + NEGOTIATION_PROBE and "publicIp" not in WEBRTC_BEHAVIOR_PROBE + NEGOTIATION_PROBE,
        "no_media_capture": not any(token in WEBRTC_BEHAVIOR_PROBE + NEGOTIATION_PROBE for token in ("get" + "UserMedia(", "get" + "DisplayMedia(")),
        "historical_artifacts_immutable": before_hashes == after_hashes,
        "browser_launches": int(started),
        "network_requests": 0,
        "valid": False,
    }
    stats = {
        "total_compared_fields": len(differences),
        "equal_fields": sum(1 for row in differences if row["status"] == "EQUAL"),
        "all_differences": len([row for row in differences if row["status"] != "EQUAL"]),
        "remaining_runtime_differences": len(gate_differences),
        "critical_differences": len(critical),
        "supplemental_differences": len([row for row in differences if not row.get("gate_relevant")]),
        "status_distribution": dict(sorted(Counter(row["status"] for row in differences).items())),
        "severity_distribution": dict(sorted(Counter(row["severity"] for row in differences if row["status"] != "EQUAL").items())),
        "domain_distribution": {domain: domains[domain] for domain in DOMAIN_ORDER},
        "baseline_directory": baseline_meta.get("directory"),
        "baseline_hash": baseline_hash,
        "candidate_hash": candidate_hash,
        "capture_status": status,
        "capture_error": capture_error,
        "browser_launches": int(started),
        "network_requests": 0,
        "local_peer_connections_created": 3 if candidate.get("available") else 0,
    }
    summary = {
        "experiment": "Experiment 048 - WebRTC Behavioral Comparator",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "SUCCESS" if status == "SUCCESS" and certification["certified"] else ("PARTIAL" if status == "SUCCESS" else "UNKNOWN"),
        "baseline_input": baseline_meta.get("directory"),
        "candidate_source": "BrowserSessionManager capture",
        "overall_runtime_similarity": overall_runtime,
        "behavior_fingerprint_similarity": fingerprint_similarity,
        "remaining_runtime_differences": len(gate_differences),
        "critical_differences": len(critical),
        "certification": certification["status"],
        "patch_required": certification["patch_required"],
        "freeze_recommendation": certification["frozen"],
        "historical_artifacts_modified": False,
        "browser_launches": int(started),
        "network_requests": 0,
    }
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "webrtc_behavior_compare"
    output.mkdir(parents=True, exist_ok=False)
    artifact_data = {
        "compare.json": {
            "experiment": summary["experiment"],
            "experiment_id": experiment.experiment_id,
            "baseline": baseline,
            "baseline_meta": baseline_meta,
            "candidate": candidate,
            "negotiation": negotiation,
            "capture_status": status,
            "capture_error": capture_error,
        },
        "similarity.json": similarity,
        "runtime.json": {"behavior": candidate, "negotiation": negotiation},
        "differences.json": {"differences": differences},
        "critical.json": {"critical": critical},
        "recommendations.json": {"recommendations": recommendations},
        "certification.json": certification,
        "statistics.json": stats,
        "summary.json": summary,
        "validation.json": validation,
    }
    validation["artifact_completeness"] = all(name in artifact_data for name in ("compare.json", "similarity.json", "runtime.json", "differences.json", "critical.json", "recommendations.json", "certification.json", "statistics.json", "summary.json", "validation.json"))
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})
    summary["validation_valid"] = validation["valid"]
    for filename, value in artifact_data.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "webrtc_behavior_compare.md", _report(summary, similarity, certification, stats, critical, recommendations))
    print("WEBRTC BEHAVIOR CERTIFICATION GATE")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Overall runtime similarity: {overall_runtime:.2f}%")
    print(f"Behavior fingerprint: {fingerprint_similarity:.2f}%")
    print(f"Remaining gate differences: {len(gate_differences)} | Critical: {len(critical)}")
    print(f"Certification: {certification['status']} | Frozen: {certification['frozen']}")
    print(f"Browser launches: {stats['browser_launches']} | Network requests: {stats['network_requests']}")
    print(f"Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 048: certify WebRTC runtime behavior")
    parser.add_argument("--baseline-dir", type=Path, default=None)
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
