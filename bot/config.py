from __future__ import annotations

import os

from dataclasses import dataclass
from pathlib    import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(
        encoding="utf-8"
    ).splitlines():

        line = raw_line.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        key, value = line.split("=", 1)

        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'")
        )


# ==================================================
# CONFIG
# ==================================================

@dataclass(frozen=True)
class Config:
    """Seluruh konfigurasi bot dari environment variables."""
    token:            str
    chat_id:          str
    check_months:     str
    interval_seconds: int
    max_months:       int


def get_config() -> Config:
    """
    Baca seluruh konfigurasi dari environment.
    Panggil setelah load_dotenv().

    Raises:
        SystemExit: Jika TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID tidak diisi.
    """
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        raise SystemExit(
            "Isi TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID di file .env"
        )

    return Config(
        token            = token,
        chat_id          = chat_id,
        check_months     = os.environ.get("CHECK_MONTHS", ""),
        interval_seconds = int(os.environ.get("CHECK_INTERVAL_SECONDS", "60")),
        max_months       = int(os.environ.get("MAX_MONTHS", "2")),
    )
