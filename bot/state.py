"""
State management untuk Semeru Quota Bot.

State disimpan di file JSON lokal agar persistens
ketika bot restart.
"""
from __future__ import annotations

import json

from pathlib import Path


STATE_FILE = Path("data/semeru_quota_state.json")


def load_state() -> dict:
    """
    Muat state dari disk.
    Kembalikan state default jika file belum ada atau rusak.
    """
    if not STATE_FILE.exists():
        return _default_state()

    try:
        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return _default_state()


def save_state(state: dict) -> None:
    """Tulis state ke disk secara atomic-ish (overwrite)."""
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# --------------------------------------------------
# Internal helpers
# --------------------------------------------------

def _default_state() -> dict:
    return {
        "slots":           {},
        "reports":         {},
        "error": {
            "active":     False,
            "last_error": "",
        },
        # Diisi oleh monitoring loop, dibaca oleh /status handler
        "startup_time":    "",   # ISO 8601, diisi sekali saat bot start
        "last_check_time": "",   # ISO 8601, diperbarui setiap siklus sukses
        "months":          [],   # Daftar bulan yang sedang dimonitor
    }
