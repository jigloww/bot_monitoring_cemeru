"""
Message builders untuk Semeru Quota Bot.

Semua fungsi di sini hanya membangun string pesan —
tidak ada side-effect (tidak mengirim ke Telegram).

Kategorisasi:
    AKTIF (dipanggil di main loop):
        build_daily_report()
        build_change_messages()
        build_error_message()
        build_recovery_message()

    DISIMPAN — tidak aktif di main loop saat ini:
        build_startup_message()     → dipakai saat Pull Message /status fase 2
        build_heartbeat_message()   → dipakai saat Pull Message /status fase 2
        format_uptime()             → helper untuk heartbeat message
"""
from __future__ import annotations

from datetime import datetime

from bot.constants import LOCAL_TZ
from bot.monitor import format_month


# ==================================================
# AKTIF: Push Message
# ==================================================

def build_daily_report(
    title:         str,
    months:        list[str],
    current_slots: dict[str, int],
) -> str:
    """Bangun pesan laporan harian (morning/night report)."""
    lines: list[str] = [title, ""]

    grouped: dict[str, list[tuple[str, int]]] = {}

    for date_str, quota in current_slots.items():
        month = date_str[:7]
        grouped.setdefault(month, []).append((date_str, quota))

    for month in months:
        lines.append(f"📅 {format_month(month)}")
        entries = grouped.get(month, [])

        if not entries:
            lines.append("❌ Tidak ada kuota tersedia")
        else:
            for date_str, quota in sorted(entries):
                lines.append(f"✅ {date_str} - {quota} kuota")

        lines.append("")

    lines.append(
        datetime.now(LOCAL_TZ).strftime("🕒 %d %b %Y %H:%M WIB")
    )

    return "\n".join(lines)


def build_change_messages(
    previous: dict[str, int],
    current:  dict[str, int],
) -> list[str]:
    """
    Bandingkan kuota sebelumnya vs sekarang.
    Kembalikan list pesan untuk setiap perubahan yang terdeteksi.
    """
    messages: list[str] = []
    all_dates = set(previous.keys()) | set(current.keys())

    for iso_date in sorted(all_dates):
        old_quota = previous.get(iso_date, 0)
        new_quota = current.get(iso_date, 0)

        if old_quota == new_quota:
            continue

        if old_quota == 0 and new_quota > 0:
            messages.append("\n".join([
                "🚨 CEMERU ALERT",
                "",
                f"📅 {iso_date}",
                f"🎟️ Kuota tersedia: {new_quota}",
                "",
                "Segera lakukan pemesanan.",
            ]))

        elif old_quota > 0 and new_quota == 0:
            messages.append("\n".join([
                "❌ KUOTA HABIS",
                "",
                f"📅 {iso_date}",
            ]))

        elif new_quota > old_quota:
            messages.append("\n".join([
                "📈 KUOTA BERTAMBAH",
                "",
                f"📅 {iso_date}",
                f"🎟️ {old_quota} → {new_quota}",
            ]))

        elif new_quota < old_quota:
            messages.append("\n".join([
                "📉 KUOTA BERKURANG",
                "",
                f"📅 {iso_date}",
                f"🎟️ {old_quota} → {new_quota}",
            ]))

    return messages


def build_error_message(error_text: str, now: datetime) -> str:
    """Bangun pesan notifikasi website error (dikirim sekali)."""
    return (
        "🚨 BOT ERROR\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Website Semeru tidak dapat diakses.\n\n"
        f"🕒 Error Time\n"
        f"{now.strftime('%d-%m-%Y %H:%M:%S')} WIB\n\n"
        f"📄 Detail\n"
        f"{error_text}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ Bot akan mencoba kembali secara otomatis."
    )


def build_recovery_message(now: datetime) -> str:
    """Bangun pesan notifikasi website recovery (dikirim sekali)."""
    return (
        "✅ RECOVERY\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Website Semeru kembali normal.\n\n"
        f"🕒 Recovery Time\n"
        f"{now.strftime('%d-%m-%Y %H:%M:%S')} WIB\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🟢 Monitoring dilanjutkan."
    )


# ==================================================
# DISIMPAN — tidak dipanggil di main loop saat ini.
# Direncanakan untuk Pull Message fase berikutnya.
# Contoh penggunaan: command /status di Telegram.
# ==================================================

def format_uptime(seconds: int) -> str:
    """Format detik menjadi string uptime yang mudah dibaca."""
    days,    seconds  = divmod(seconds, 86400)
    hours,   seconds  = divmod(seconds, 3600)
    minutes, _        = divmod(seconds, 60)

    parts: list[str] = []

    if days:
        parts.append(f"{days} hari")
    if hours:
        parts.append(f"{hours} jam")
    if minutes:
        parts.append(f"{minutes} menit")

    return " ".join(parts) if parts else "Kurang dari 1 menit"


def build_startup_message(months: list[str], now: datetime) -> str:
    """
    [DISIMPAN] Pesan saat bot pertama kali dijalankan.
    Tidak lagi dikirim secara otomatis.
    Dapat dipakai untuk Pull Message /status fase berikutnya.
    """
    month_lines = "\n".join(f"• {month}" for month in months)
    time_text   = now.strftime("%d-%m-%Y %H:%M:%S")

    return (
        "🤖 Semeru Quota Bot\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🟢 Bot berhasil dijalankan.\n\n"
        f"🕒 Waktu : {time_text}\n\n"
        "📅 Monitoring:\n"
        f"{month_lines}\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "✅ Siap melakukan monitoring."
    )


def build_heartbeat_message(
    months:       list[str],
    startup_time: datetime,
    last_check:   datetime,
    slot_count:   int,
) -> str:
    """
    [DISIMPAN] Pesan heartbeat harian.
    Tidak lagi dikirim secara otomatis.
    Dapat dipakai untuk Pull Message /status fase berikutnya.
    """
    uptime      = format_uptime(int((last_check - startup_time).total_seconds()))
    month_lines = "\n".join(f"• {month}" for month in months)

    return (
        "❤️ Daily Heartbeat\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🤖 Semeru Quota Bot\n\n"
        "🟢 Status : Running\n"
        f"⏱ Uptime : {uptime}\n\n"
        f"🕒 Last Check : "
        f"{last_check.strftime('%d-%m-%Y %H:%M:%S')} WIB\n\n"
        "📅 Monitoring\n"
        f"{month_lines}\n\n"
        f"🎯 Available Slot : {slot_count}\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "✅ Bot berjalan normal."
    )


def build_status_message(
    months:        list[str],
    current_slots: dict[str, int],
    last_check:    datetime | None,
    website_ok:    bool,
    startup_time:  datetime | None,
    now:           datetime,
) -> str:
    """
    Pesan status lengkap untuk command /status.

    Respons mencakup:
        - Status Bot   (selalu Running, karena bot sedang aktif)
        - Status Website (Normal / Error)
        - Bulan yang di-monitor
        - Last Check
        - Uptime
        - Available Slot
    """
    website_label = "Normal" if website_ok else "Error"
    website_icon  = "🟢" if website_ok else "🔴"
    slot_count    = len(current_slots)

    month_lines = (
        "\n".join(f"• {format_month(m)}" for m in months)
        if months else "• -"
    )

    last_check_str = (
        last_check.strftime("%d-%m-%Y %H:%M:%S") + " WIB"
        if last_check else "Belum ada data"
    )

    uptime_str = (
        format_uptime(int((now - startup_time).total_seconds()))
        if startup_time else "Tidak diketahui"
    )

    return "\n".join([
        "🤖 Semeru Quota Bot",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "🟢 Status Bot",
        "Running",
        "",
        f"{website_icon} Website",
        website_label,
        "",
        "📅 Monitoring",
        month_lines,
        "",
        "🕒 Last Check",
        last_check_str,
        "",
        "⏱ Uptime",
        uptime_str,
        "",
        "🎟 Available Slot",
        str(slot_count),
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "✅ Bot berjalan normal.",
    ])

