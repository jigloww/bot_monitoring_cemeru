"""Experiment 013: cross-domain fingerprint consistency validation.

This experiment is deliberately analysis-only.  It reads the real-browser
baseline and the latest completed fingerprint artifact, evaluates explicit
relationships between domains, and writes a read-only audit report.  No
browser is launched and no stealth code is changed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.baseline import load_baseline, resolve_baseline_path
from experiments.experiment import Experiment
from experiments.utils import (
    now_iso,
    project_root,
    relative_path,
    write_json_exclusive,
    write_text_exclusive,
)


STATUS_SCORE = {"PASS": 100.0, "WARNING": 60.0, "FAIL": 0.0}
CATEGORIES = (
    "Navigator", "Window", "Screen", "Chrome", "Permissions", "Fonts",
    "Speech", "Performance", "Cross-Domain",
)
EXP_PATTERN = re.compile(r"^exp_(\d+)$")


@dataclass(frozen=True)
class Source:
    path: Path
    fingerprint: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    domains: tuple[str, ...]
    check: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _get(data: dict[str, Any], *path: str, default: Any = None) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _status(status: str, severity: str, reason: str, fix: str, confidence: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "status": status,
        "severity": severity,
        "reason": reason,
        "recommended_fix": fix,
        "confidence": confidence,
        "observed": observed,
        "expected": expected,
    }


def _browser_from_ua(ua: str) -> tuple[str | None, str | None]:
    if not isinstance(ua, str):
        return None, None
    # Edge embeds a Chrome token, so identify it before the generic Chromium
    # branch.  This keeps browser-specific consistency rules from mislabeling
    # Edge as Chrome.
    edge = re.search(r"Edg/([\d.]+)", ua)
    if edge:
        return "Edge", edge.group(1)
    match = re.search(r"(?:HeadlessChrome|Chrome|Chromium)/([\d.]+)", ua)
    if match:
        return "Chrome", match.group(1)
    if "Firefox/" in ua:
        return "Firefox", re.search(r"Firefox/([\d.]+)", ua).group(1)
    if "Safari/" in ua and "Chrome/" not in ua:
        return "Safari", None
    return None, None


def _ua_ch_brands(ua_data: Any) -> list[dict[str, Any]]:
    brands = _get(ua_data if isinstance(ua_data, dict) else {}, "brands", default=[])
    return [item for item in brands if isinstance(item, dict)] if isinstance(brands, list) else []


def _rule_ua_ua_ch(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    nav = candidate.get("navigator", {})
    ua = nav.get("userAgent")
    ua_data = nav.get("userAgentData")
    browser, version = _browser_from_ua(ua)
    brands = _ua_ch_brands(ua_data)
    chrome_brands = [b for b in brands if "Chrome" in str(b.get("brand", "")) or "Chromium" in str(b.get("brand", ""))]
    edge_brands = [b for b in brands if "edge" in str(b.get("brand", "")).lower()]
    if not browser or not isinstance(ua_data, dict) or not brands:
        return _status("WARNING", "Medium", "UA or UA-CH browser identity is missing.", "Expose a coherent userAgentData.brands set for the reported browser.", "Medium", {"userAgent": ua, "brands": brands})
    major = version.split(".")[0] if version else None
    identity_brands = chrome_brands if browser == "Chrome" else edge_brands if browser == "Edge" else []
    brand_versions = {str(item.get("version", "")).split(".")[0] for item in identity_brands}
    platform_match = _get(ua_data, "platform") in {"Windows", "macOS", "Linux", "Android", "iOS"}
    if identity_brands and major in brand_versions and platform_match:
        return _status("PASS", "Low", "UA browser family/version agree with UA-CH brands.", "No change required.", "High", {"browser": browser, "major": major, "brands": identity_brands})
    return _status("FAIL", "High", "UA and UA-CH report different browser identity or version.", "Align UA, UA-CH brands, versions, platform, and mobile flag.", "High", {"browser": browser, "version": version, "brands": chrome_brands, "platform": _get(ua_data, "platform")})


def _rule_platform_ua(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    nav = candidate.get("navigator", {})
    platform = nav.get("platform")
    platform_text = platform if isinstance(platform, str) else ""
    ua = str(nav.get("userAgent") or "")
    expected = "Windows" if platform in {"Win32", "Win64", "Windows"} else "Mac" if platform_text.startswith("Mac") else "Linux" if platform_text.startswith("Linux") else "Android" if platform_text.startswith("Android") else "iPhone" if platform_text.startswith("iPhone") else None
    if expected is None:
        return _status("WARNING", "Medium", "Navigator platform is unavailable or non-standard.", "Use a platform value that matches the operating system token in the UA.", "Medium", platform)
    ok = ((expected == "Windows" and "Windows NT" in ua) or
          (expected == "Mac" and "Macintosh" in ua) or
          (expected == "Linux" and "Linux" in ua) or
          (expected in {"Android", "iPhone"} and expected in ua))
    return _status("PASS" if ok else "FAIL", "Low" if ok else "High", "Platform agrees with the operating-system token in userAgent." if ok else "Platform conflicts with the operating-system token in userAgent.", "Keep navigator.platform and the UA operating-system token aligned.", "High", {"platform": platform, "userAgent": ua})


def _rule_screen_window(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    screen, window = candidate.get("screen", {}), candidate.get("window", {})
    sw, sh = _number(screen.get("width")), _number(screen.get("height"))
    iw, ih = _number(window.get("innerWidth")), _number(window.get("innerHeight"))
    ow, oh = _number(window.get("outerWidth")), _number(window.get("outerHeight"))
    if None in {sw, sh, iw, ih}:
        return _status("WARNING", "Medium", "Screen or viewport dimensions are incomplete.", "Expose width/height and inner viewport dimensions consistently.", "Medium", {"screen": screen, "window": window})
    ok = sw >= iw and sh >= ih and (ow is None or ow >= iw) and (oh is None or oh >= ih)
    return _status("PASS" if ok else "FAIL", "Low" if ok else "High", "Window viewport fits inside the reported screen." if ok else "Window viewport exceeds the reported screen or outer bounds.", "Ensure outer/inner viewport and screen dimensions form a physically possible layout.", "High", {"screen": [sw, sh], "inner": [iw, ih], "outer": [ow, oh]})


def _rule_chrome_runtime(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    nav = candidate.get("navigator", {})
    chrome = candidate.get("chrome", {})
    browser, _ = _browser_from_ua(str(nav.get("userAgent") or ""))
    present = bool(chrome.get("present"))
    runtime = chrome.get("runtime") if isinstance(chrome.get("runtime"), dict) else {}
    runtime_present = bool(runtime.get("present"))
    if browser != "Chrome":
        return _status("PASS", "Low", "Runtime check is not applicable to a non-Chrome UA.", "No change required.", "High", {"browser": browser, "chrome": present})
    if not present:
        return _status("FAIL", "High", "Chrome UA does not expose window.chrome.", "Expose a coherent Chrome surface for a Chrome UA.", "High", {"chromePresent": present})
    if not runtime_present:
        return _status("WARNING", "Low", "window.chrome is present but chrome.runtime is absent; this can be valid on extension-free pages.", "Only expose chrome.runtime when the target browser context requires it.", "Medium", {"chromePresent": present, "runtimePresent": runtime_present})
    return _status("PASS", "Low", "Chrome runtime surface agrees with the Chrome UA.", "No change required.", "High", {"runtimePresent": runtime_present})


def _rule_languages(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    nav = candidate.get("navigator", {})
    language, languages = nav.get("language"), nav.get("languages")
    if not isinstance(language, str) or not isinstance(languages, list) or not languages:
        return _status("FAIL", "High", "Language or languages is missing.", "Expose navigator.language and a non-empty navigator.languages list.", "High", {"language": language, "languages": languages})
    ok = languages[0] == language and language in languages
    return _status("PASS" if ok else "FAIL", "Low" if ok else "High", "Primary language is the first languages entry." if ok else "navigator.language does not match the primary languages entry.", "Set navigator.language equal to languages[0] and keep locale ordering coherent.", "High", {"language": language, "languages": languages})


def _rule_hardware_memory(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    nav = candidate.get("navigator", {})
    cores, memory = _number(nav.get("hardwareConcurrency")), _number(nav.get("deviceMemory"))
    if cores is None or memory is None or cores <= 0 or memory <= 0:
        return _status("WARNING", "Medium", "Hardware concurrency or device memory is unavailable.", "Expose positive, mutually plausible hardware values.", "Medium", {"hardwareConcurrency": cores, "deviceMemory": memory})
    ok = not ((memory <= 1 and cores > 8) or (memory <= 2 and cores > 16) or (memory >= 16 and cores < 2))
    return _status("PASS" if ok else "WARNING", "Low" if ok else "Medium", "Hardware concurrency and memory are plausible together." if ok else "Hardware concurrency and memory form an unusual combination.", "Use a profile with a realistic CPU/memory pairing.", "Medium", {"hardwareConcurrency": cores, "deviceMemory": memory})


def _rule_performance_memory(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    browser, _ = _browser_from_ua(str(_get(candidate, "navigator", "userAgent", default="") or ""))
    memory = _get(candidate, "performance", "memory")
    if browser == "Chrome" and isinstance(memory, dict):
        return _status("PASS", "Low", "Chrome exposes a coherent performance.memory object.", "No change required.", "High", {"browser": browser, "memoryPresent": True})
    if browser == "Chrome":
        return _status("WARNING", "Medium", "Chrome UA does not expose performance.memory.", "Expose memory only when the target Chromium surface provides it.", "Medium", {"browser": browser, "memoryPresent": False})
    if isinstance(memory, dict):
        return _status("WARNING", "Medium", "performance.memory is present for a non-Chrome UA.", "Keep browser-specific performance surfaces aligned with the UA.", "Medium", {"browser": browser, "memoryPresent": True})
    return _status("PASS", "Low", "No browser-specific performance.memory contradiction detected.", "No change required.", "Medium", {"browser": browser, "memoryPresent": False})


def _rule_fonts_platform(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    platform = str(_get(candidate, "navigator", "platform", default="") or "")
    fonts = candidate.get("fonts") if isinstance(candidate.get("fonts"), dict) else {}
    detected = [str(value).lower() for value in fonts.get("detected", [])] if isinstance(fonts.get("detected"), list) else []
    count = _number(fonts.get("count"))
    if count is None:
        return _status("WARNING", "Medium", "Font inventory is missing.", "Expose a font count consistent with the target platform.", "Medium", {"platform": platform, "count": count})
    expected = {"Win32": {"segoe ui", "calibri", "tahoma", "arial"}, "MacIntel": {"helvetica", "times new roman"}, "Linux x86_64": {"dejavu sans", "liberation sans"}}.get(platform)
    if count == 0:
        return _status("WARNING", "Medium", "No detectable fonts were reported for a desktop platform.", "Use the native platform font inventory or a realistic profile.", "Medium", {"platform": platform, "count": count})
    if expected and not expected.intersection(detected):
        return _status("WARNING", "Medium", "Font inventory has no common family expected for the reported platform.", "Keep font families consistent with the operating-system profile.", "Low", {"platform": platform, "sample": detected[:8]})
    return _status("PASS", "Low", "Font inventory is plausible for the reported platform.", "No change required.", "Medium", {"platform": platform, "count": count})


def _rule_speech_platform(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    platform = str(_get(candidate, "navigator", "platform", default="") or "")
    speech = candidate.get("speech") if isinstance(candidate.get("speech"), dict) else {}
    count = _number(speech.get("count"))
    voices = speech.get("voices") if isinstance(speech.get("voices"), list) else []
    if count is None:
        return _status("WARNING", "Medium", "Speech voice inventory is missing.", "Expose a native or profile-backed speech voice list.", "Medium", {"platform": platform, "count": count})
    if count == 0 and platform in {"Win32", "MacIntel", "Linux x86_64"}:
        return _status("WARNING", "Medium", "Desktop platform reports no speech voices.", "Use the native voice inventory or a platform-consistent speech profile.", "Medium", {"platform": platform, "count": count})
    valid = all(isinstance(voice, dict) and isinstance(voice.get("lang"), str) for voice in voices)
    return _status("PASS" if valid else "WARNING", "Low" if valid else "Medium", "Speech voices contain platform-neutral, valid locale records." if valid else "Some speech voice records lack valid locale data.", "Keep voice locale records complete and aligned with the platform/browser profile.", "Medium", {"platform": platform, "count": count})


def _rule_viewport_screen(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    screen, window = candidate.get("screen", {}), candidate.get("window", {})
    values = [_number(screen.get("availWidth")), _number(screen.get("availHeight")), _number(window.get("innerWidth")), _number(window.get("innerHeight"))]
    if any(value is None for value in values):
        return _status("WARNING", "Medium", "Viewport or available screen dimensions are incomplete.", "Expose coherent screen availability and viewport dimensions.", "Medium", {"screen": screen, "window": window})
    ok = window["innerWidth"] <= screen["availWidth"] and window["innerHeight"] <= screen["availHeight"]
    return _status("PASS" if ok else "FAIL", "Low" if ok else "High", "Viewport fits inside the available screen area." if ok else "Viewport exceeds available screen dimensions.", "Keep inner viewport dimensions within screen.availWidth/availHeight.", "High", {"inner": [window["innerWidth"], window["innerHeight"]], "available": [screen["availWidth"], screen["availHeight"]]})


def _rule_dpr_viewport(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    window, screen = candidate.get("window", {}), candidate.get("screen", {})
    dpr, iw, ih, sw, sh = (_number(window.get("devicePixelRatio")), _number(window.get("innerWidth")), _number(window.get("innerHeight")), _number(screen.get("width")), _number(screen.get("height")))
    if any(value is None for value in (dpr, iw, ih, sw, sh)) or dpr <= 0:
        return _status("WARNING", "Medium", "DPR or viewport dimensions are unavailable.", "Expose a positive devicePixelRatio with coherent viewport dimensions.", "Medium", {"dpr": dpr, "inner": [iw, ih], "screen": [sw, sh]})
    ok = dpr > 0 and iw <= sw and ih <= sh
    return _status("PASS" if ok else "FAIL", "Low" if ok else "High", "DPR and viewport dimensions form a plausible display relationship." if ok else "DPR/viewport dimensions are physically inconsistent.", "Keep devicePixelRatio, viewport, and screen dimensions from contradictory profiles.", "Medium", {"dpr": dpr, "inner": [iw, ih], "screen": [sw, sh]})


def _rule_vendor_browser(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    nav = candidate.get("navigator", {})
    browser, _ = _browser_from_ua(str(nav.get("userAgent") or ""))
    vendor = nav.get("vendor")
    if browser == "Chrome" and vendor == "Google Inc.":
        return _status("PASS", "Low", "Chrome UA and navigator.vendor agree.", "No change required.", "High", {"browser": browser, "vendor": vendor})
    if browser == "Chrome":
        return _status("FAIL", "High", "Chrome UA reports a non-Chrome vendor.", "Set navigator.vendor to the vendor expected by the browser family.", "High", {"browser": browser, "vendor": vendor})
    return _status("WARNING", "Low", "Vendor/browser relationship is not classifiable from the available UA.", "Keep vendor aligned with the chosen browser family.", "Low", {"browser": browser, "vendor": vendor})


def _rule_webdriver_automation(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    webdriver = _get(candidate, "navigator", "webdriver")
    metadata = candidate.get("_meta", {}) if isinstance(candidate.get("_meta"), dict) else {}
    automated = bool(metadata.get("headless") or metadata.get("generated_patches_applied") or metadata.get("modules_applied"))
    if automated and webdriver is False:
        return _status("WARNING", "Medium", "Automation metadata is present while navigator.webdriver is hidden.", "Treat webdriver spoofing as an intentional, documented stealth decision and keep other automation signals aligned.", "High", {"automated": automated, "webdriver": webdriver})
    if automated and webdriver is True:
        return _status("PASS", "Low", "Automation metadata agrees with navigator.webdriver.", "No change required.", "High", {"automated": automated, "webdriver": webdriver})
    if not automated and webdriver is False:
        return _status("PASS", "Low", "Non-automated metadata and webdriver=false are consistent.", "No change required.", "Medium", {"automated": automated, "webdriver": webdriver})
    return _status("WARNING", "Medium", "webdriver is true without explicit automation metadata.", "Keep automation metadata and navigator.webdriver behavior consistent.", "Medium", {"automated": automated, "webdriver": webdriver})


def _rule_plugins_mimes(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    plugins = candidate.get("plugins") if isinstance(candidate.get("plugins"), dict) else {}
    plugin_count, mime_count = _number(plugins.get("plugin_count")), _number(plugins.get("mime_count"))
    if plugin_count is None or mime_count is None:
        return _status("WARNING", "Medium", "Plugin or MIME type counts are missing.", "Expose plugin and MIME type counts from the same browser surface.", "Medium", {"pluginCount": plugin_count, "mimeCount": mime_count})
    ok = plugin_count == 0 and mime_count == 0 or plugin_count > 0 and mime_count > 0 and mime_count <= plugin_count * 2
    return _status("PASS" if ok else "FAIL", "Low" if ok else "High", "Plugin and MIME type counts are mutually plausible." if ok else "Plugin and MIME type counts contradict each other.", "Keep navigator.plugins and navigator.mimeTypes generated from one coherent profile.", "High", {"pluginCount": plugin_count, "mimeCount": mime_count})


def _rule_permissions_secure(candidate: dict[str, Any], _reference: dict[str, Any]) -> dict[str, Any]:
    permissions = candidate.get("permissions") if isinstance(candidate.get("permissions"), dict) else {}
    metadata = candidate.get("_meta", {}) if isinstance(candidate.get("_meta"), dict) else {}
    url = str(metadata.get("url") or "")
    secure = True if url.startswith("https:") else False if url.startswith("http:") else None
    granted_sensitive = any(permissions.get(key) == "granted" for key in ("camera", "microphone", "geolocation"))
    if secure is None:
        return _status("WARNING", "Low", "Secure-context status cannot be inferred from the recorded URL.", "Record a secure-context signal or evaluate permissions on the target origin.", "Low", {"url": url, "secureContext": secure, "grantedSensitive": granted_sensitive})
    if not secure and granted_sensitive:
        return _status("FAIL", "High", "A sensitive permission is granted in an insecure context.", "Do not grant camera, microphone, or geolocation permissions on insecure origins.", "High", {"url": url, "secureContext": secure, "grantedSensitive": granted_sensitive})
    return _status("PASS", "Low", "Permission states are compatible with the inferred secure context.", "No change required.", "Medium", {"url": url, "secureContext": secure, "grantedSensitive": granted_sensitive})


RULES = (
    Rule("ua_ua_ch", "UA ↔ UA-CH consistency", ("Navigator", "Cross-Domain"), _rule_ua_ua_ch),
    Rule("platform_ua", "Platform ↔ UA consistency", ("Navigator",), _rule_platform_ua),
    Rule("screen_window", "Screen ↔ Window consistency", ("Screen", "Window", "Cross-Domain"), _rule_screen_window),
    Rule("chrome_runtime_browser", "chrome.runtime ↔ browser consistency", ("Chrome", "Cross-Domain"), _rule_chrome_runtime),
    Rule("languages_language", "Languages ↔ language consistency", ("Navigator",), _rule_languages),
    Rule("hardware_memory", "hardwareConcurrency ↔ deviceMemory consistency", ("Navigator", "Cross-Domain"), _rule_hardware_memory),
    Rule("performance_memory_browser", "performance.memory ↔ browser consistency", ("Performance", "Cross-Domain"), _rule_performance_memory),
    Rule("fonts_platform", "Fonts ↔ platform consistency", ("Fonts", "Cross-Domain"), _rule_fonts_platform),
    Rule("speech_platform", "Speech voices ↔ platform consistency", ("Speech", "Cross-Domain"), _rule_speech_platform),
    Rule("viewport_screen", "Viewport ↔ screen consistency", ("Window", "Screen"), _rule_viewport_screen),
    Rule("dpr_viewport", "DPR ↔ viewport consistency", ("Window", "Screen"), _rule_dpr_viewport),
    Rule("vendor_browser", "navigator.vendor ↔ browser consistency", ("Navigator", "Chrome"), _rule_vendor_browser),
    Rule("webdriver_automation", "navigator.webdriver ↔ automation consistency", ("Navigator", "Cross-Domain"), _rule_webdriver_automation),
    Rule("plugins_mimetypes", "Plugin count ↔ MIME type consistency", ("Navigator", "Cross-Domain"), _rule_plugins_mimes),
    Rule("permissions_secure_context", "Permissions ↔ secure context consistency", ("Permissions", "Cross-Domain"), _rule_permissions_secure),
)


def _load_source(path: Path) -> Source:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Fingerprint root must be an object: {path}")
    fingerprint = raw.get("fingerprint", raw)
    if isinstance(fingerprint, dict) and isinstance(fingerprint.get("modes"), dict):
        modes = fingerprint["modes"]
        selected = modes.get("performance") or modes.get("fonts_speech") or next(iter(modes.values()), {})
        fingerprint = selected.get("fingerprint", selected) if isinstance(selected, dict) else {}
    metadata = raw.get("_meta", {}) if isinstance(raw.get("_meta"), dict) else {}
    if not isinstance(fingerprint, dict):
        raise ValueError(f"Fingerprint payload must be an object: {path}")
    return Source(path=path.resolve(), fingerprint=fingerprint, metadata=metadata)


def _candidate_path(reports_dir: Path) -> Path:
    experiments = []
    for path in reports_dir.iterdir() if reports_dir.is_dir() else []:
        match = EXP_PATTERN.match(path.name) if path.is_dir() else None
        if match:
            experiments.append((int(match.group(1)), path))
    for _, experiment in sorted(experiments, reverse=True):
        preferred = [
            experiment / "performance" / "performance" / "fingerprint.json",
            experiment / "speech" / "fonts_speech" / "fingerprint.json",
            experiment / "fonts" / "navigator_window_screen_chrome_permissions_fonts" / "fingerprint.json",
        ]
        for path in preferred:
            if path.is_file(): return path
        candidates = sorted(experiment.rglob("fingerprint.json"))
        if candidates:
            return candidates[-1]
    raise FileNotFoundError(f"No completed experiment fingerprint found under {reports_dir}")


def _evaluate(candidate: Source, reference: Source) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # Experiment metadata is intentionally kept outside the browser payload,
    # but it is still useful context for rules such as webdriver ↔ automation.
    # Keep the fingerprint immutable and expose metadata through a private,
    # read-only view consumed only by validators that need it.
    candidate_view = dict(candidate.fingerprint)
    if candidate.metadata:
        candidate_view.setdefault("_meta", candidate.metadata)
    issues = []
    for rule in RULES:
        result = rule.check(candidate_view, reference.fingerprint)
        issues.append({"rule": rule.rule_id, "name": rule.name, "domains": list(rule.domains), **result})
    category_scores = {}
    for category in CATEGORIES:
        relevant = [issue for issue in issues if category in issue["domains"]]
        category_scores[category] = {
            "score": round(sum(STATUS_SCORE[issue["status"]] for issue in relevant) / len(relevant), 1) if relevant else 100.0,
            "rules": len(relevant),
            "pass": sum(issue["status"] == "PASS" for issue in relevant),
            "warning": sum(issue["status"] == "WARNING" for issue in relevant),
            "fail": sum(issue["status"] == "FAIL" for issue in relevant),
        }
    overall = round(sum(STATUS_SCORE[issue["status"]] for issue in issues) / len(issues), 1)
    summary = {
        "overall_consistency_score": overall,
        "category_scores": category_scores,
        "rule_count": len(issues),
        "pass_count": sum(issue["status"] == "PASS" for issue in issues),
        "warning_count": sum(issue["status"] == "WARNING" for issue in issues),
        "fail_count": sum(issue["status"] == "FAIL" for issue in issues),
        "status": "FAIL" if any(issue["status"] == "FAIL" for issue in issues) else "WARNING" if any(issue["status"] == "WARNING" for issue in issues) else "PASS",
    }
    return issues, summary


def _render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Experiment 013 - Fingerprint Consistency Validator",
        "",
        "Analysis-only validation; no browser or stealth code was modified.",
        "",
        f"Overall Consistency Score: **{summary['overall_consistency_score']:.1f}%** ({summary['status']})",
        "",
        "## Category Scores",
        "",
        "| Domain | Score | Rules | PASS | WARNING | FAIL |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for category in CATEGORIES:
        row = summary["category_scores"][category]
        lines.append(f"| {category} | {row['score']:.1f}% | {row['rules']} | {row['pass']} | {row['warning']} | {row['fail']} |")
    lines.extend([
        "",
        "## Rule Results",
        "",
        "| Rule | Status | Severity | Reason | Recommended Fix | Confidence |",
        "|---|---|---|---|---|---|",
    ])
    for issue in report["issues"]:
        def cell(value: Any) -> str:
            return str(value if value is not None else "-").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {cell(issue['name'])} | {issue['status']} | {issue['severity']} | {cell(issue['reason'])} | {cell(issue['recommended_fix'])} | {issue['confidence']} |")
    lines.extend([
        "",
        "## Data Sources",
        "",
        f"- Reference: `{report['sources']['reference']['path']}`",
        f"- Candidate: `{report['sources']['candidate']['path']}`",
        "- Candidate selection: latest completed Performance experiment artifact",
        "",
        "## Counts",
        "",
        f"PASS: {summary['pass_count']}  |  WARNING: {summary['warning_count']}  |  FAIL: {summary['fail_count']}",
        "",
    ])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Experiment 013: cross-domain consistency validation.")
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--candidate", type=Path, default=None)
    parser.add_argument("--reports-dir", type=Path, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root()
    reports_dir = args.reports_dir or root / "reports/experiments"
    reports_dir = (root / reports_dir if not reports_dir.is_absolute() else reports_dir).resolve()
    reference = _load_source(resolve_baseline_path(root, args.baseline))
    candidate_path = args.candidate
    if candidate_path is None:
        candidate_path = _candidate_path(reports_dir)
    elif not candidate_path.is_absolute():
        candidate_path = root / candidate_path
    candidate = _load_source(candidate_path.resolve())
    issues, summary = _evaluate(candidate, reference)

    experiment = Experiment.create(reports_dir)
    output = experiment.directory
    report = {
        "experiment": "Experiment 013 - Fingerprint Consistency Validator",
        "experiment_id": experiment.experiment_id,
        "created_at": now_iso(),
        "analysis_only": True,
        "sources": {
            "reference": {"path": relative_path(reference.path, root)},
            "candidate": {"path": relative_path(candidate.path, root), "metadata": candidate.metadata},
        },
        "summary": summary,
        "issues": issues,
    }
    write_json_exclusive(output / "consistency_report.json", report)
    write_json_exclusive(output / "consistency_summary.json", {
        "experiment": report["experiment"],
        "experiment_id": experiment.experiment_id,
        "created_at": report["created_at"],
        "overall_consistency_score": summary["overall_consistency_score"],
        "category_scores": summary["category_scores"],
        "counts": {key: summary[key] for key in ("rule_count", "pass_count", "warning_count", "fail_count")},
        "status": summary["status"],
        "sources": report["sources"],
    })
    write_text_exclusive(output / "consistency_report.md", _render_markdown(report))
    rendered = _render_markdown(report)
    try:
        print(rendered)
    except UnicodeEncodeError:
        # Windows console code pages may not represent the report's arrows;
        # preserve the full UTF-8 report on disk and use escaped output only
        # for the console fallback.
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(rendered.encode(encoding, "backslashreplace").decode(encoding, "replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
