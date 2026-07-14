"""
stealth/loader.py — Load stealth scripts from the registry or generated files.

Provides utilities to assemble a single combined JS init script from
all registered modules and generated patches.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stealth.registry import Registry

_HERE = Path(__file__).parent
_GENERATED_DIR = _HERE / "generated"


def load_patches_js() -> str:
    """Load the auto-generated patches_init.js content."""
    p = _GENERATED_DIR / "patches_init.js"
    if not p.exists():
        return "// patches_init.js not found — run tools/patch_generator.py\n"
    return p.read_text(encoding="utf-8")


def load_patches_json() -> dict:
    """Load the auto-generated patches.json manifest."""
    p = _GENERATED_DIR / "patches.json"
    if not p.exists():
        return {"count": 0, "patches": []}
    return json.loads(p.read_text(encoding="utf-8"))


def load_module_js(name: str) -> str | None:
    """Load a named module JS file from stealth/modules/."""
    p = _HERE / "modules" / f"{name}.js"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def load_runtime_js(name: str) -> str | None:
    """Load a named runtime JS file from stealth/runtime/."""
    p = _HERE / "runtime" / f"{name}.js"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def assemble_init_script(registry: "Registry | None" = None) -> str:
    """
    Assemble a single combined JS init script from all sources.
    Load order: runtime helpers → modules → generated patches.
    """
    parts: list[str] = []

    if registry is not None:
        for script in registry.js_scripts():
            parts.append(script)
    else:
        # Fallback: load runtime + patches_init.js directly
        for rt in ("helpers", "utils"):
            js = load_runtime_js(rt)
            if js:
                parts.append(js)
        patches = load_patches_js()
        parts.append(patches)

    return "\n\n".join(parts)


def patch_count() -> int:
    """Return number of auto-generated patches available."""
    return load_patches_json().get("count", 0)
