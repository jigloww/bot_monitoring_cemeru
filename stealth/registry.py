"""
stealth/registry.py — Patch and module registry.

Tracks which stealth modules and generated patches are available.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class StealthModule:
    name:        str
    js_file:     Path
    description: str
    enabled:     bool = True
    status:      str  = "active"   # active | placeholder | disabled


class Registry:
    """Central registry of all stealth patches and modules."""

    def __init__(self) -> None:
        self._modules:  dict[str, StealthModule] = {}
        self._js_files: list[Path] = []
        self._hooks:    list[Callable] = []

    # ── Module registration ───────────────────────────────────────

    def register_module(self, module: StealthModule) -> None:
        self._modules[module.name] = module
        if module.js_file.exists() and module.enabled:
            self._js_files.append(module.js_file)

    def get_module(self, name: str) -> StealthModule | None:
        return self._modules.get(name)

    @property
    def modules(self) -> list[StealthModule]:
        return list(self._modules.values())

    # ── JS file management ────────────────────────────────────────

    def add_js_file(self, path: Path) -> None:
        if path.exists():
            self._js_files.append(path)

    def js_scripts(self) -> list[str]:
        """Return contents of all registered JS files, in order."""
        scripts = []
        for p in self._js_files:
            try:
                scripts.append(p.read_text(encoding="utf-8"))
            except OSError:
                pass
        return scripts

    # ── Summary ───────────────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "modules":    len(self._modules),
            "js_files":   len(self._js_files),
            "active":     sum(1 for m in self._modules.values() if m.enabled),
            "placeholder": sum(1 for m in self._modules.values() if m.status == "placeholder"),
        }


# ── Default global registry ───────────────────────────────────────

_HERE = Path(__file__).parent

_DEFAULT_REGISTRY = Registry()

# Register all module JS files
_MODULES_DIR = _HERE / "modules"
_RUNTIME_DIR = _HERE / "runtime"

for _name, _desc, _status in [
    ("navigator",   "navigator.* property overrides",   "active"),
    ("window",      "window.* property overrides",      "active"),
    ("screen",      "screen.* property overrides",      "active"),
    ("document",    "document.* property overrides",    "placeholder"),
    ("permissions", "Permissions API spoofing",         "placeholder"),
    ("chrome",      "Chrome runtime spoofing",          "placeholder"),
    ("history",     "history.* overrides",              "placeholder"),
    ("location",    "location.* overrides",             "placeholder"),
    ("performance", "Performance timing spoofing",      "placeholder"),
]:
    _DEFAULT_REGISTRY.register_module(StealthModule(
        name=_name, js_file=_MODULES_DIR / f"{_name}.js",
        description=_desc, status=_status,
        enabled=(_status == "active"),
    ))

# Runtime utilities are always loaded first
for _rt in ("helpers", "utils", "proxy", "hooks"):
    _DEFAULT_REGISTRY.add_js_file(_RUNTIME_DIR / f"{_rt}.js")

# Generated patches (highest priority — loaded last)
_DEFAULT_REGISTRY.add_js_file(_HERE / "generated" / "patches_init.js")


def get_default_registry() -> Registry:
    return _DEFAULT_REGISTRY
