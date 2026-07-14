"""
Auto-generated Playwright patches by patch_generator.py
Apply these BEFORE navigating to the target URL.
"""
from playwright.sync_api import Page


def apply_patches(page: Page) -> None:
    """Apply all evidence-based browser fingerprint patches."""

    # ── Navigator: Override navigator.webdriver to return false.
    # navigator.webdriver
    page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>false})");

    # ── Navigator: Set navigator.deviceMemory to 8.
    page.add_init_script("Object.defineProperty(navigator,'deviceMemory',{get:()=>8})");

    # ── Window: Set window.outerHeight to 798 (0 in headless).
    page.add_init_script("Object.defineProperty(window,'outerHeight',{get:()=>798})");

    # ── Window: Set window.outerWidth to 1051 (0 in headless).
    page.add_init_script("Object.defineProperty(window,'outerWidth',{get:()=>1051})");

    # ── Navigator: Override navigator.languages to match real browser: ["en-US", "en", "id"].
    page.add_init_script("Object.defineProperty(navigator,'languages',{get:()=>["en-US", "en", "id"]})");
