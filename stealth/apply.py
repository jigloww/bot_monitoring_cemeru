"""
stealth/apply.py — Apply stealth patches to a Playwright page.

Usage:
    from stealth import apply_stealth
    apply_stealth(page)

    # Or just the auto-generated patches (fast path):
    from stealth.apply import apply_generated
    apply_generated(page)
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page, BrowserContext

log = logging.getLogger("stealth.apply")
_HERE = Path(__file__).parent


def apply_generated(page: "Page") -> None:
    """
    Apply only the auto-generated patches from stealth/generated/patches_init.js.

    This is the fast path — no module loading, just the patch script.
    Suitable for use inside playwright_client.py.
    """
    from stealth.loader import load_patches_js, patch_count
    js = load_patches_js()
    if not js.strip() or js.startswith("// patches_init.js not found"):
        log.warning("No generated patches found — run tools/patch_generator.py first")
        return
    page.add_init_script(js)
    log.info("Applied %d auto-generated stealth patches", patch_count())


def apply_modules(page: "Page", modules: list[str]) -> None:
    """
    Apply specific stealth modules by name.

    Args:
        page:    Playwright Page object
        modules: list of module names (e.g. ['navigator', 'window', 'screen'])
    """
    from stealth.loader import load_module_js
    for name in modules:
        js = load_module_js(name)
        if js:
            page.add_init_script(js)
            log.debug("Applied module: %s", name)
        else:
            log.debug("Module not found or empty: %s", name)


def apply_stealth(page: "Page", *, modules: list[str] | None = None) -> None:
    """
    Apply full stealth stack to a Playwright page.

    Load order:
        1. stealth/runtime/helpers.js + utils.js  (utilities)
        2. stealth/modules/*.js                   (domain-specific patches)
        3. stealth/generated/patches_init.js      (auto-generated patches — highest priority)

    Args:
        page:    Playwright Page object
        modules: Override module list. Default: all active modules.
    """
    from stealth.registry import get_default_registry
    from stealth.loader import assemble_init_script

    registry  = get_default_registry()
    combined  = assemble_init_script(registry)

    if combined.strip():
        page.add_init_script(combined)
        log.info("Stealth stack applied — modules:%d  %s",
                 registry.summary()["active"], registry.summary())
    else:
        log.warning("Stealth: no scripts to apply")


def apply_stealth_context(context: "BrowserContext", **kwargs) -> None:
    """
    Apply stealth patches to every page in a BrowserContext.
    Use this with launch_persistent_context().
    """
    from stealth.registry import get_default_registry
    from stealth.loader import assemble_init_script

    registry = get_default_registry()
    combined = assemble_init_script(registry)
    if combined.strip():
        context.add_init_script(combined)
        log.info("Stealth context patches applied")
