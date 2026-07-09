"""
Command handler untuk Pull Message — Fase 2.

Dipanggil dari telegram.py ketika ada update masuk dari Telegram.

Command yang aktif:
    /status   → Status Bot & Website

Command yang direncanakan (fase berikutnya):
    /start
    /help
    /menu
    /statistik
    /settings
"""
from __future__ import annotations

from datetime import datetime

from bot.constants import LOCAL_TZ
from bot.logger    import logger
from bot.messages  import build_status_message
from bot.state     import load_state
from bot.telegram  import send_message


# ==================================================
# HANDLERS
# ==================================================

def handle_status(token: str, chat_id: str) -> None:
    """
    Balas command /status dengan informasi realtime bot.

    Data diambil dari state JSON yang ditulis oleh monitoring loop,
    sehingga tidak memerlukan HTTP request tambahan ke website.
    """
    state = load_state()
    now   = datetime.now(LOCAL_TZ)

    # --- Website status ---
    website_ok = not state.get("error", {}).get("active", False)

    # --- Kuota ---
    current_slots = state.get("slots", {})

    # --- Bulan yang dimonitor ---
    months = state.get("months", [])

    # --- Startup time ---
    startup_time: datetime | None = None
    startup_raw = state.get("startup_time", "")
    if startup_raw:
        try:
            startup_time = datetime.fromisoformat(startup_raw)
        except ValueError:
            pass

    # --- Last check time ---
    last_check: datetime | None = None
    last_check_raw = state.get("last_check_time", "")
    if last_check_raw:
        try:
            last_check = datetime.fromisoformat(last_check_raw)
        except ValueError:
            pass

    msg = build_status_message(
        months        = months,
        current_slots = current_slots,
        last_check    = last_check,
        website_ok    = website_ok,
        startup_time  = startup_time,
        now           = now,
    )

    send_message(token, chat_id, msg)
    logger.info(f"[PULL] /status sent to chat_id={chat_id}")


# ==================================================
# REGISTRY & DISPATCH
# ==================================================

# Mapping command → handler function.
# Tambahkan entry baru di sini saat mengimplementasi command berikutnya.
COMMAND_HANDLERS: dict[str, object] = {
    "/status": handle_status,
    # "/start":     handle_start,      # TODO: Fase berikutnya
    # "/help":      handle_help,       # TODO: Fase berikutnya
    # "/menu":      handle_menu,       # TODO: Fase berikutnya
    # "/statistik": handle_statistik,  # TODO: Fase berikutnya
    # "/settings":  handle_settings,   # TODO: Fase berikutnya
}


def dispatch(token: str, chat_id: str, command: str) -> bool:
    """
    Routing command ke handler yang sesuai.

    Args:
        token:   Bot token Telegram.
        chat_id: Chat ID tujuan (dari message update, bukan config).
        command: String command dari user, misal "/status".

    Returns:
        True  jika command dikenal dan berhasil diproses.
        False jika command tidak dikenal.
    """
    # Normalisasi: "/status@NamaBotnya" → "/status"
    base_command = command.split("@")[0].lower()

    handler = COMMAND_HANDLERS.get(base_command)

    if handler is None:
        logger.info(f"[PULL] Unknown command: {base_command!r} from chat_id={chat_id}")
        return False

    try:
        handler(token, chat_id)  # type: ignore[call-arg]
        return True
    except Exception as exc:
        logger.error(f"[PULL] Handler error for {base_command!r}: {exc}")
        return False
