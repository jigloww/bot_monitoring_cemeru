"""Shared filesystem, serialization, hashing, and metadata helpers."""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata
import json
import math
import platform
import subprocess
import sys

from datetime import datetime
from pathlib import Path
from typing import Any


def project_root() -> Path:
    """Return the repository root derived from this package location."""
    root = Path(__file__).resolve().parent.parent
    if not (root / "tools").is_dir() or not (root / "stealth").is_dir():
        raise RuntimeError(f"Cannot locate project root from {__file__}")
    return root


def now_iso() -> str:
    """Return a timezone-aware local ISO-8601 timestamp."""
    return datetime.now().astimezone().isoformat()


def configure_console_error_handling() -> None:
    """Prevent an orchestrated tool's Unicode log message from breaking a pipe."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


def read_json(path: Path) -> Any:
    """Load a JSON document from disk."""
    return json.loads(path.read_text(encoding="utf-8"))


def json_compatible(value: Any) -> Any:
    """Convert values to strict, portable JSON-compatible structures."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return json_compatible(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_compatible(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        label = "nan"
        if math.isinf(value):
            label = "positive_infinity" if value > 0 else "negative_infinity"
        return {"$type": "number", "value": label}
    return value


def write_json_exclusive(path: Path, data: Any, *, indent: int = 2) -> None:
    """Write strict JSON once; fail instead of overwriting an artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        json_compatible(data),
        indent=indent,
        ensure_ascii=False,
        allow_nan=False,
    )
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.write("\n")


def write_text_exclusive(path: Path, text: str) -> None:
    """Write text once; fail instead of overwriting an artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        if text and not text.endswith("\n"):
            stream.write("\n")


def sha256_file(path: Path) -> str:
    """Calculate a file SHA-256 digest without loading the whole file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(path: Path, root: Path) -> str:
    """Return a repository-relative path when possible."""
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def package_version(distribution: str) -> str:
    """Return an installed distribution version or 'unknown'."""
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def git_metadata(root: Path) -> dict[str, Any]:
    """Collect the current Git commit and dirty state without changing Git."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        return {"commit": commit or None, "dirty": bool(status.strip())}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def system_metadata() -> dict[str, Any]:
    """Collect host metadata using the Python standard library."""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
    }


def observed_environment(fingerprint: dict[str, Any]) -> dict[str, Any]:
    """Extract environment facts already observed by the fingerprint tool."""
    window = fingerprint.get("window") or {}
    navigator = fingerprint.get("navigator") or {}
    timezone = fingerprint.get("timezone") or {}
    return {
        "viewport": {
            "width": window.get("innerWidth"),
            "height": window.get("innerHeight"),
            "device_pixel_ratio": window.get("devicePixelRatio"),
        },
        "locale": navigator.get("language") or timezone.get("locale"),
        "languages": navigator.get("languages"),
        "timezone": timezone.get("timeZone"),
        "timezone_offset_minutes": timezone.get("offset_minutes"),
        "user_agent": navigator.get("userAgent"),
        "platform": navigator.get("platform"),
    }


def active_patch_metadata(root: Path) -> dict[str, Any]:
    """Describe the generated patch set currently consumed by apply_generated."""
    from stealth.loader import load_patches_json

    generated_dir = root / "stealth" / "generated"
    manifest_path = generated_dir / "patches.json"
    script_path = generated_dir / "patches_init.js"
    manifest = load_patches_json()
    patches = manifest.get("patches", []) if isinstance(manifest, dict) else []
    patch_keys = sorted(
        {
            item.get("key")
            for item in patches
            if isinstance(item, dict) and isinstance(item.get("key"), str)
        }
    )
    script_hash = sha256_file(script_path) if script_path.exists() else None
    manifest_hash = sha256_file(manifest_path) if manifest_path.exists() else None
    generated_at = manifest.get("generated_at") if isinstance(manifest, dict) else None
    version = generated_at or (script_hash[:12] if script_hash else "none")
    return {
        "version": version,
        "generated_at": generated_at,
        "count": manifest.get("count", len(patch_keys)) if isinstance(manifest, dict) else 0,
        "keys": patch_keys,
        "manifest": relative_path(manifest_path, root),
        "manifest_sha256": manifest_hash,
        "script": relative_path(script_path, root),
        "script_sha256": script_hash,
    }
