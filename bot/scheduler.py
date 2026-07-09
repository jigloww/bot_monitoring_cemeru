"""
Scheduler untuk push message otomatis Semeru Quota Bot.

Hanya menentukan KAPAN sebuah pesan harus dikirim,
bukan mengirimnya sendiri.

Catatan:
    should_send_heartbeat() disimpan di sini untuk kemungkinan
    dipakai kembali di Pull Message fase berikutnya, tetapi
    TIDAK dipanggil di main loop saat ini.
"""
from __future__ import annotations

from datetime import datetime


def should_send_morning_report(state: dict, now: datetime) -> bool:
    """
    Kembalikan True jika morning report belum dikirim hari ini
    dan jam sekarang adalah 08:xx.
    """
    if now.hour != 8:
        return False

    today     = now.strftime("%Y-%m-%d")
    last_sent = state.get("reports", {}).get("morning")
    return last_sent != today


def should_send_night_report(state: dict, now: datetime) -> bool:
    """
    Kembalikan True jika night report belum dikirim hari ini
    dan jam sekarang adalah 22:xx.
    """
    if now.hour != 22:
        return False

    today     = now.strftime("%Y-%m-%d")
    last_sent = state.get("reports", {}).get("night")
    return last_sent != today


# --------------------------------------------------
# Disimpan — tidak aktif di main loop saat ini.
# Akan digunakan di Pull Message fase berikutnya
# sebagai bagian dari command /status.
# --------------------------------------------------

def should_send_heartbeat(state: dict, now: datetime) -> bool:
    """
    [TIDAK AKTIF] Kembalikan True jika heartbeat harian
    belum dikirim hari ini dan jam sekarang adalah 00:01.
    """
    today     = now.strftime("%Y-%m-%d")
    last_sent = state.get("reports", {}).get("heartbeat")
    return (
        now.hour == 0
        and now.minute == 1
        and last_sent != today
    )
