"""
Package bot — Semeru Quota Bot.

Modul-modul:
    constants  — Konstanta global, timezone, QuotaSlot
    config     — load_dotenv, get_config, Config
    monitor    — Scraping & parsing website Semeru
    state      — State management (JSON)
    logger     — Logging ke stdout (ditangkap systemd/journalctl)
    telegram   — Komunikasi Telegram API (Push + scaffold long polling)
    messages   — Message builders (push & future pull)
    scheduler  — Logika jadwal push message otomatis
    handlers   — Command handler scaffold untuk Pull Message Fase 2
"""
