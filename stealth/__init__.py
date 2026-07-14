"""
stealth/__init__.py — Stealth Playwright Framework for Cloudflare Fingerprint Evasion.

Usage:
    from stealth import apply_stealth
    apply_stealth(page)

    # Or load only generated patches:
    from stealth.apply import apply_generated
    apply_generated(page)
"""
from __future__ import annotations

from stealth.apply import apply_generated, apply_stealth

__all__ = ["apply_stealth", "apply_generated"]
__version__ = "0.1.0"
