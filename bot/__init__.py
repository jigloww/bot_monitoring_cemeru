"""
Package bot — Semeru Quota Bot.

Modul-modul:
    constants       — Konstanta global, timezone, QuotaSlot
    config          — load_dotenv, get_config, Config
    website_status  — WebsiteStatus enum, WebsiteError exception
    clients/        — Website client layer (Playwright + requests)
    monitor         — Parsing website Semeru (tidak bergantung HTTP client)
    state           — State management (JSON)
    logger          — Logging ke stdout (ditangkap systemd/journalctl)
    telegram        — Komunikasi Telegram API (Push + long polling Pull)
    messages        — Message builders (push & pull)
    scheduler       — Logika jadwal morning/night report
    handlers        — Command handler Pull Message (/status, dll)
"""
