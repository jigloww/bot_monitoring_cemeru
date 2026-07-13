"""
Message builders untuk Semeru Quota Bot.

Semua fungsi hanya membangun string pesan — tidak ada side-effect.

Push Message (aktif di main loop):
    build_daily_report()        — morning / night report
    build_change_messages()     — quota alert
    build_error_message()       — website error (sekali per incident)
    build_suspended_message()   — monitoring suspended (sekali per incident)
    build_recovery_message()    — website recovery (sekali per incident)

Pull Message (/status):
    build_status_message()      — respons command /status

Disimpan (tidak aktif di main loop):
    build_startup_message()     — placeholder fase berikutnya
    build_heartbeat_message()   — placeholder fase berikutnya
    format_uptime()             — helper
"""
from __future__ import annotations

from datetime import datetime

from bot.constants      import LOCAL_TZ
from bot.monitor        import format_month
from bot.website_status import WebsiteStatus


# ==================================================
# HELPER
# ==================================================

def format_uptime(seconds: int) -> str:
    """Format detik menjadi string uptime yang mudah dibaca."""
    days,    seconds = divmod(seconds, 86400)
    hours,   seconds = divmod(seconds, 3600)
    minutes, _       = divmod(seconds, 60)

    parts: list[str] = []
    if days:    parts.append(f"{days} hari")
    if hours:   parts.append(f"{hours} jam")
    if minutes: parts.append(f"{minutes} menit")

    return " ".join(parts) if parts else "Kurang dari 1 menit"


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%d-%m-%Y %H:%M WIB")


# ==================================================
# PUSH MESSAGE — aktif di main loop
# ==================================================

def build_daily_report(
    title:          str,
    months:         list[str],
    current_slots:  dict[str, int],
    website_status: WebsiteStatus = WebsiteStatus.NORMAL,
) -> str:
    """
    Bangun pesan laporan harian (morning/night report).

    Jika website_status bukan NORMAL, tampilkan pesan error
    sebagai pengganti data kuota agar laporan tidak menyesatkan.
    """
    lines: list[str] = [title, ""]

    if not website_status.is_ok:
        lines.append(f"⚠️ Data kuota tidak dapat diperbarui.")
        lines.append(f"Penyebab: {website_status.value}")
        lines.append("")
    else:
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

    lines.append(datetime.now(LOCAL_TZ).strftime("🕒 %d %b %Y %H:%M WIB"))
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


def build_error_message(
    status: WebsiteStatus,
    now:    datetime,
) -> str:
    """
    Bangun pesan notifikasi website error (dikirim sekali per incident).
    Menyertakan penyebab spesifik berdasarkan WebsiteStatus.
    """
    return "\n".join([
        "🚨 WEBSITE ERROR",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "🔴 Penyebab",
        status.value,
        "",
        "🕒 Waktu",
        _fmt_time(now),
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "⚠️ Bot tidak dapat mengambil data kuota.",
        "Monitoring akan dicoba kembali secara otomatis.",
    ])


def build_suspended_message(
    status: WebsiteStatus,
    now:    datetime,
) -> str:
    """
    Bangun pesan monitoring suspended (dikirim sekali per incident,
    bersamaan dengan build_error_message).
    """
    return "\n".join([
        "⚠️ MONITORING SUSPENDED",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "Monitoring sementara tidak dapat dilakukan.",
        "",
        "Penyebab:",
        status.value,
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "Bot akan mencoba kembali secara otomatis.",
    ])


def build_recovery_message(now: datetime) -> str:
    """Bangun pesan notifikasi website recovery (dikirim sekali per incident)."""
    return "\n".join([
        "✅ WEBSITE RECOVERY",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "Website Semeru kembali dapat diakses.",
        "",
        "🕒 Recovery Time",
        _fmt_time(now),
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "🟢 Monitoring kuota kembali berjalan.",
    ])


# ==================================================
# PULL MESSAGE — /status
# ==================================================

def build_status_message(
    months:         list[str],
    current_slots:  dict[str, int],
    last_check:     datetime | None,
    website_status: WebsiteStatus,
    startup_time:   datetime | None,
    now:            datetime,
) -> str:
    """Pesan status lengkap untuk command /status."""
    slot_count = len(current_slots)

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

    # Slot count: tampilkan "Tidak dapat dibaca" saat website error
    slot_str = str(slot_count) if website_status.is_ok else "Tidak dapat dibaca"

    return "\n".join([
        "🤖 Semeru Quota Bot",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "🟢 Status Bot",
        "Running",
        "",
        f"{website_status.icon} Website",
        website_status.value,
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
        slot_str,
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "✅ Bot berjalan normal.",
    ])


# ==================================================
# DISIMPAN — tidak dipanggil di main loop saat ini
# ==================================================

def build_startup_message(months: list[str], now: datetime) -> str:
    """[DISIMPAN] Pesan startup — tidak dikirim otomatis."""
    month_lines = "\n".join(f"• {month}" for month in months)
    return (
        "🤖 Semeru Quota Bot\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🟢 Bot berhasil dijalankan.\n\n"
        f"🕒 Waktu : {now.strftime('%d-%m-%Y %H:%M:%S')}\n\n"
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
    """[DISIMPAN] Pesan heartbeat — tidak dikirim otomatis."""
    uptime      = format_uptime(int((last_check - startup_time).total_seconds()))
    month_lines = "\n".join(f"• {month}" for month in months)
    return (
        "❤️ Daily Heartbeat\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🤖 Semeru Quota Bot\n\n"
        "🟢 Status : Running\n"
        f"⏱ Uptime : {uptime}\n\n"
        f"🕒 Last Check : {last_check.strftime('%d-%m-%Y %H:%M:%S')} WIB\n\n"
        "📅 Monitoring\n"
        f"{month_lines}\n\n"
        f"🎯 Available Slot : {slot_count}\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "✅ Bot berjalan normal."
    )
