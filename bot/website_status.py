"""
WebsiteStatus — Status website Semeru dan exception terkait.

Dipakai oleh:
    clients/playwright_client.py  → raise WebsiteError saat request gagal
    monitor.py                    → propagate ke caller
    semeru_quota_bot.py           → tangkap, simpan ke state
    messages.py                   → tampilkan label & icon yang tepat
    handlers.py                   → baca dari state untuk /status
"""
from __future__ import annotations

from enum import Enum


# ==================================================
# STATUS ENUM
# ==================================================

class WebsiteStatus(Enum):
    NORMAL                = "Normal"
    CLOUDFLARE_PROTECTION = "Cloudflare Protection"
    HTTP_ERROR            = "HTTP Error"
    TIMEOUT               = "Connection Timeout"
    DNS_ERROR             = "DNS Resolution Failed"
    UNKNOWN               = "Unknown Error"

    @property
    def icon(self) -> str:
        if self == WebsiteStatus.NORMAL:
            return "🟢"
        if self == WebsiteStatus.CLOUDFLARE_PROTECTION:
            return "🟡"
        return "🔴"

    @property
    def is_ok(self) -> bool:
        return self == WebsiteStatus.NORMAL

    @classmethod
    def from_value(cls, value: str) -> "WebsiteStatus":
        """
        Buat WebsiteStatus dari string value yang disimpan di state JSON.
        Fallback ke UNKNOWN jika value tidak dikenal.
        """
        for member in cls:
            if member.value == value:
                return member
        return cls.UNKNOWN


# ==================================================
# EXCEPTION
# ==================================================

class WebsiteError(Exception):
    """
    Exception yang membawa WebsiteStatus untuk klasifikasi error website.

    Contoh:
        raise WebsiteError(WebsiteStatus.TIMEOUT, "30s timeout exceeded")
    """

    def __init__(self, status: WebsiteStatus, detail: str = "") -> None:
        self.status = status
        self.detail = detail
        super().__init__(
            f"{status.value}: {detail}" if detail else status.value
        )
