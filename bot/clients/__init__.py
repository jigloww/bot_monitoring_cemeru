"""
Package clients — Website client layer untuk Semeru Quota Bot.

Memisahkan cara pengambilan HTML dari logika parsing dan monitoring.
Jika metode pengambilan HTML perlu diganti di masa depan,
cukup ganti implementasi di package ini tanpa menyentuh monitor.py.

Modul:
    playwright_client  — Playwright (cookies) + requests (HTTP)
"""
