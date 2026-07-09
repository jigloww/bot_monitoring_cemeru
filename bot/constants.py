"""
Konstanta global untuk Semeru Quota Bot.
"""
from __future__ import annotations

import urllib.parse

from dataclasses import dataclass
from datetime import timedelta, timezone


# ==================================================
# TIMEZONE
# ==================================================

LOCAL_TZ = timezone(
    timedelta(hours=7),
    name="GMT+07:00"
)


# ==================================================
# WEBSITE
# ==================================================

BASE_URL = "https://bromotenggersemeru.id/"

QUOTA_ENDPOINT = urllib.parse.urljoin(
    BASE_URL,
    "website/home/get_view"
)


# ==================================================
# BULAN (Indonesia)
# ==================================================

MONTHS_ID = {
    "Januari":   "01",
    "Februari":  "02",
    "Maret":     "03",
    "April":     "04",
    "Mei":       "05",
    "Juni":      "06",
    "Juli":      "07",
    "Agustus":   "08",
    "September": "09",
    "Oktober":   "10",
    "November":  "11",
    "Desember":  "12",
}

MONTH_NAMES = {
    "01": "Januari",
    "02": "Februari",
    "03": "Maret",
    "04": "April",
    "05": "Mei",
    "06": "Juni",
    "07": "Juli",
    "08": "Agustus",
    "09": "September",
    "10": "Oktober",
    "11": "November",
    "12": "Desember",
}


# ==================================================
# DATA MODEL
# ==================================================

@dataclass(frozen=True)
class QuotaSlot:
    year_month:   str
    iso_date:     str
    display_date: str
    quota:        int
