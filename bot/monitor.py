"""
Modul monitoring website Semeru.

Bertanggung jawab untuk:
- Parsing halaman kuota (tidak berubah)
- Resolving daftar bulan yang di-monitor

Cara pengambilan HTML didelegasikan ke:
    bot.clients.playwright_client.fetch_html()

Jika website client perlu diganti, hanya clients/ yang perlu dimodifikasi.
Parser di modul ini tidak perlu diubah.
"""
from __future__ import annotations

import html
import re

from datetime import datetime

from bot.clients.playwright_client import fetch_html
from bot.constants import (
    BASE_URL,
    QUOTA_ENDPOINT,
    LOCAL_TZ,
    MONTHS_ID,
    MONTH_NAMES,
    QuotaSlot,
)


# ==================================================
# PARSING — tidak berubah dari versi sebelumnya
# ==================================================

def fetch_available_months() -> list[str]:
    """Ambil daftar bulan yang tersedia dari halaman utama website."""
    body   = fetch_html(BASE_URL)
    months = re.findall(r'<option[^>]+value="(\d{4}-\d{2})"', body)
    return list(dict.fromkeys(months))


def strip_tags(value: str) -> str:
    """Hapus semua HTML tag dan normalkan whitespace."""
    text = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(" ".join(text.split()))


def parse_indonesian_date(display_date: str) -> str:
    """
    Konversi tanggal format Indonesia ke ISO 8601.

    Contoh input : "Sabtu, 12 Juli 2026"
    Contoh output: "2026-07-12"
    """
    match = re.search(
        r",\s*(\d{1,2})\s+([A-Za-z`]+)\s+(\d{4})",
        display_date,
    )

    if not match:
        raise ValueError(f"Cannot parse date: {display_date}")

    day, month_name, year = match.groups()
    month = MONTHS_ID.get(month_name)

    if month is None:
        raise ValueError(f"Unknown Indonesian month name: {month_name}")

    return f"{year}-{month}-{int(day):02d}"


def parse_quota_table(body: str, year_month: str) -> list[QuotaSlot]:
    """
    Parse tabel kuota dari HTML response website Semeru.
    Hanya mengembalikan slot dengan kuota > 0.
    """
    slots: list[QuotaSlot] = []

    rows = re.findall(
        r"<tr[^>]*>(.*?)</tr>",
        body,
        re.IGNORECASE | re.DOTALL,
    )

    for row in rows:
        cells = re.findall(
            r"<td[^>]*>(.*?)</td>",
            row,
            re.IGNORECASE | re.DOTALL,
        )

        if len(cells) < 2:
            continue

        display_date = strip_tags(cells[0])

        if "kuota penuh" in cells[1].lower():
            continue

        available_match = re.search(
            r'<span[^>]*class="[^"]*text-green[^"]*"[^>]*>\s*(\d+)\s*',
            cells[1],
            re.IGNORECASE,
        )

        if available_match is None:
            continue

        quota = int(available_match.group(1))

        if quota <= 0:
            continue

        slots.append(
            QuotaSlot(
                year_month=year_month,
                iso_date=parse_indonesian_date(display_date),
                display_date=display_date,
                quota=quota,
            )
        )

    return slots


def fetch_month_quota(year_month: str) -> list[QuotaSlot]:
    """Ambil kuota untuk satu bulan tertentu dari API website."""
    body = fetch_html(
        QUOTA_ENDPOINT,
        {
            "action":     "kapasitas",
            "id_site":    "8",
            "year_month": year_month,
        },
    )
    return parse_quota_table(body, year_month)


# ==================================================
# AGREGASI
# ==================================================

def get_current_slots(months: list[str]) -> dict[str, int]:
    """
    Ambil semua slot tersedia untuk daftar bulan yang diberikan.

    Returns:
        dict dengan key iso_date (str) dan value quota (int).

    Raises:
        WebsiteError: Jika website tidak dapat diakses.
    """
    result: dict[str, int] = {}

    for year_month in months:
        for slot in fetch_month_quota(year_month):
            result[slot.iso_date] = slot.quota

    return result


# ==================================================
# CONFIG HELPER
# ==================================================

def resolve_months(
    configured_months: str,
    max_months:        int = 2,
) -> list[str]:
    """
    Tentukan daftar bulan yang akan di-monitor.

    - Jika CHECK_MONTHS di .env terisi, gunakan itu.
    - Jika kosong, gunakan bulan sekarang + bulan depan
      (hanya yang tersedia di website).

    Raises:
        WebsiteError: Jika gagal mengambil daftar bulan dari website.
    """
    if configured_months.strip():
        return [
            item.strip()
            for item in configured_months.split(",")
            if item.strip()
        ]

    now           = datetime.now(LOCAL_TZ)
    current_year  = now.year
    current_month = now.month

    next_year  = current_year
    next_month = current_month + 1

    if next_month > 12:
        next_month = 1
        next_year += 1

    target_months = {
        f"{current_year}-{current_month:02d}",
        f"{next_year}-{next_month:02d}",
    }

    available_months = fetch_available_months()

    return [
        month
        for month in available_months
        if month in target_months
    ][:max_months]


def format_month(year_month: str) -> str:
    """Konversi "2026-07" → "Juli 2026"."""
    year, month = year_month.split("-")
    return f"{MONTH_NAMES.get(month, month)} {year}"
