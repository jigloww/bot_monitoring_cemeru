"""
Layer komunikasi Telegram untuk Semeru Quota Bot.

Saat ini mendukung:
    Push: send_message()

Fase 2 (Pull Message) — long polling:
    get_updates()  → Ambil update dari Telegram API
    Polling loop   → Jalankan di threading.Thread daemon, dispatch ke handlers.py

Command yang direncanakan:
    /status   → Status Bot & Website
    /quota    → Kuota saat ini
    /month    → Monitoring bulan
    /stats    → Statistik
    /settings → Pengaturan
    /about    → Tentang Bot
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request


# ==================================================
# PUSH: Kirim pesan ke Telegram
# ==================================================

def send_message(
    token:   str,
    chat_id: str,
    text:    str,
) -> None:
    """
    Kirim pesan teks ke chat Telegram.

    Raises:
        RuntimeError: Jika Telegram API mengembalikan ok=false.
        urllib.error.URLError: Jika koneksi gagal.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    data = urllib.parse.urlencode(
        {
            "chat_id":                  chat_id,
            "text":                     text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    request = urllib.request.Request(url, data=data)

    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")


# ==================================================
# PULL: Long polling (Fase 2 — scaffold)
# ==================================================

def get_updates(
    token:   str,
    offset:  int = 0,
    timeout: int = 30,
) -> list[dict]:
    """
    [Fase 2] Ambil update terbaru dari Telegram menggunakan long polling.

    Args:
        token:   Bot token.
        offset:  Update ID berikutnya untuk menghindari duplikat.
                 Isi dengan update_id + 1 dari update terakhir yang diproses.
        timeout: Detik tunggu long poll sebelum server mengembalikan respons kosong.

    Returns:
        List of update objects dari Telegram API.

    Raises:
        RuntimeError: Jika Telegram API mengembalikan ok=false.
        urllib.error.URLError: Jika koneksi gagal.
    """
    url = (
        f"https://api.telegram.org/bot{token}/getUpdates"
        f"?offset={offset}&timeout={timeout}"
    )

    with urllib.request.urlopen(url, timeout=timeout + 5) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")

    return result.get("result", [])


# ==================================================
# PULL: Polling loop — berjalan di daemon thread
# ==================================================

def start_polling(
    token:           str,
    allowed_chat_id: str,
    poll_timeout:    int = 30,
) -> None:
    """
    Jalankan long polling loop di daemon thread terpisah.

    Thread ini membaca command dari Telegram dan mendispatch ke handlers.py.
    Monitoring loop utama TIDAK terblokir oleh polling ini.

    Args:
        token:           Bot token Telegram.
        allowed_chat_id: Hanya memproses pesan dari chat ini (keamanan dasar).
        poll_timeout:    Detik tunggu per request getUpdates.
    """
    import threading
    import time

    from bot.handlers import dispatch
    from bot.logger   import logger

    def _loop() -> None:
        offset = 0
        logger.info("[PULL] Polling thread started")

        while True:
            try:
                updates = get_updates(token, offset=offset, timeout=poll_timeout)

                for update in updates:
                    # Tandai update ini sudah diproses (hindari duplikat)
                    offset = update["update_id"] + 1

                    message     = update.get("message", {})
                    text        = message.get("text", "").strip()
                    msg_chat_id = str(message.get("chat", {}).get("id", ""))

                    if not text.startswith("/"):
                        continue

                    # Keamanan: hanya proses dari chat yang dikonfigurasi
                    if msg_chat_id != allowed_chat_id:
                        logger.info(
                            f"[PULL] Ignored command from unknown chat_id={msg_chat_id}"
                        )
                        continue

                    command = text.split()[0]
                    dispatch(token, msg_chat_id, command)

            except Exception as exc:
                logger.error(f"[PULL] Polling error: {exc}")
                time.sleep(5)   # Tunggu sebelum retry

    thread = threading.Thread(target=_loop, name="polling", daemon=True)
    thread.start()

