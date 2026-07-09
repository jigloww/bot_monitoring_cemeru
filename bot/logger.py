"""
Logger untuk Semeru Quota Bot.

Output ke stdout — ditangkap systemd/journalctl di VPS.
Tidak menyimpan log ke file agar lebih sederhana dan sesuai
dengan model deployment systemd.
"""
from __future__ import annotations

import logging
import sys


def _setup_logger(name: str = "semeru_bot") -> logging.Logger:
    log = logging.getLogger(name)

    if log.handlers:
        return log

    log.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    log.addHandler(handler)
    return log


# Singleton — di-import oleh modul lain:
#   from bot.logger import logger
logger = _setup_logger()
