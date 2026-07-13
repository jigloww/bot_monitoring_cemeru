"""
tools/environment_report.py — Collect host system + browser environment information.

No browser launch required for most data. Browser is launched to get version info.

Usage:
    python tools/environment_report.py
    python tools/environment_report.py --channel chrome --output tools/output/environment.json
"""
from __future__ import annotations
import argparse, os, platform, subprocess, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools._shared import ensure_output_dir, save_json, setup_logging, add_output_arg

log = setup_logging("environment_report")


# ══════════════════════════════════════════════════════════════════
# SYSTEM INFO (no browser needed)
# ══════════════════════════════════════════════════════════════════

def collect_system() -> dict:
    """Collect OS, CPU, RAM, Python info using standard library."""
    info: dict = {
        "collected_at":     datetime.now().isoformat(),
        "python_version":   sys.version,
        "python_executable": sys.executable,
        "platform":         platform.platform(),
        "os":               platform.system(),
        "os_release":       platform.release(),
        "os_version":       platform.version(),
        "machine":          platform.machine(),
        "processor":        platform.processor(),
        "architecture":     platform.architecture(),
        "hostname":         platform.node(),
        "cpu_count":        os.cpu_count(),
    }
    # RAM (Linux)
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    kb = int(line.split()[1])
                    info["ram_gb"] = round(kb / 1024 / 1024, 1)
                    break
    except Exception:
        info["ram_gb"] = None

    # Uptime (Linux)
    try:
        with open("/proc/uptime") as f:
            info["uptime_seconds"] = float(f.read().split()[0])
    except Exception:
        info["uptime_seconds"] = None

    return info


def collect_display() -> dict:
    """Try to collect display/GPU info from system."""
    result: dict = {}

    # GPU via lspci (Linux)
    try:
        out = subprocess.check_output(["lspci", "-v"], stderr=subprocess.DEVNULL, text=True, timeout=5)
        gpu_lines = [l.strip() for l in out.splitlines() if "VGA" in l or "3D" in l or "Display" in l]
        result["lspci_gpu"] = gpu_lines[:5]
    except Exception:
        result["lspci_gpu"] = None

    # glxinfo (Linux)
    try:
        out = subprocess.check_output(["glxinfo", "-B"], stderr=subprocess.DEVNULL, text=True, timeout=5)
        result["glxinfo"] = out[:500]
    except Exception:
        result["glxinfo"] = None

    # DISPLAY env
    result["DISPLAY"] = os.environ.get("DISPLAY")
    result["WAYLAND_DISPLAY"] = os.environ.get("WAYLAND_DISPLAY")
    result["XDG_SESSION_TYPE"] = os.environ.get("XDG_SESSION_TYPE")

    return result


def collect_chrome_path(channel: str) -> dict:
    """Find Google Chrome / Chromium executable path."""
    candidates = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
        "/opt/google/chrome/google-chrome",
    ]
    if channel == "chrome":
        candidates = [c for c in candidates if "google-chrome" in c] + candidates

    found: list[str] = []
    for c in candidates:
        if Path(c).exists():
            found.append(c)

    result: dict = {"candidates_found": found, "primary": found[0] if found else None}

    # Get version
    if found:
        try:
            ver = subprocess.check_output([found[0], "--version"], stderr=subprocess.DEVNULL, text=True, timeout=5)
            result["version"] = ver.strip()
        except Exception:
            result["version"] = None

    return result


def collect_playwright_info() -> dict:
    """Collect Playwright and playwright-stealth version info."""
    info: dict = {}
    try:
        import playwright
        info["playwright_version"] = playwright.__version__
    except Exception:
        info["playwright_version"] = None

    try:
        import playwright_stealth
        info["playwright_stealth_version"] = getattr(playwright_stealth, "__version__", "installed")
    except Exception:
        info["playwright_stealth_version"] = "not installed"

    # Playwright browsers dir
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            info["chromium_executable"] = pw.chromium.executable_path
    except Exception:
        info["chromium_executable"] = None

    return info


def collect_launch_env(channel: str, headless: bool, profile: str) -> dict:
    """Document the browser launch configuration."""
    return {
        "channel":    channel or "chromium (bundled)",
        "headless":   headless,
        "profile":    profile or None,
        "no_sandbox": True,
        "disable_dev_shm": True,
        "env_vars": {
            "DISPLAY":          os.environ.get("DISPLAY"),
            "HOME":             os.environ.get("HOME"),
            "USER":             os.environ.get("USER"),
            "LANG":             os.environ.get("LANG"),
            "TZ":               os.environ.get("TZ"),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Collect host system + browser environment info.")
    p.add_argument("--channel",     default="",    help="'chrome' or empty for bundled Chromium")
    p.add_argument("--no-headless", action="store_true")
    p.add_argument("--profile",     default="",    help="Profile path")
    add_output_arg(p, default="")
    return p


def main() -> int:
    args     = build_parser().parse_args()
    out_path = Path(args.output) if args.output else ensure_output_dir() / "environment.json"

    log.info("Collecting system environment…")
    report = {
        "system":     collect_system(),
        "display_gpu": collect_display(),
        "chrome":     collect_chrome_path(args.channel),
        "playwright": collect_playwright_info(),
        "launch_config": collect_launch_env(args.channel, not args.no_headless, args.profile),
    }

    save_json(report, out_path)
    log.info("Saved → %s", out_path)

    # Print key info
    sys_info = report["system"]
    log.info("OS         : %s %s", sys_info["os"], sys_info["os_release"])
    log.info("CPU cores  : %s", sys_info["cpu_count"])
    log.info("RAM        : %sGB", sys_info.get("ram_gb", "?"))
    log.info("Python     : %s", sys_info["python_version"].split()[0])
    log.info("Playwright : %s", report["playwright"]["playwright_version"])
    log.info("Chrome     : %s", report["chrome"].get("version","not found"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
