"""
Playwright Website Client — Semeru Quota Bot.

Strategi hybrid (future-proof):
    1. Browser (headless + persistent profile) membuka halaman utama.
       Urutan launch:
           a. Google Chrome Stable (channel="chrome") — fingerprint lebih realistis.
           b. Chromium bawaan Playwright — fallback otomatis jika Chrome tidak tersedia.
       Profile disimpan di data/browser_profile/ agar Cloudflare mengenali
       browser yang sama pada siklus monitoring berikutnya.
    2. Setelah halaman terbuka, cek Cloudflare challenge.
       Jika ada: polling setiap 2 detik maksimal 45 detik.
    3. HTML halaman utama diambil langsung dari Playwright (sudah ter-bypass).
    4. Cookies dari Playwright context diekstrak ke requests.Session.
    5. POST request quota menggunakan requests.Session + cookies tersebut.
    6. Jika requests POST mendapat 403 → Playwright refresh session otomatis.

Hanya modul ini yang perlu dimodifikasi jika mekanisme bypass Cloudflare berubah.
"""
from __future__ import annotations

import time

from pathlib import Path

import requests

from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright_stealth  import Stealth

from bot.constants      import BASE_URL
from bot.logger         import logger
from bot.website_status import WebsiteError, WebsiteStatus


# ==================================================
# CONSTANTS
# ==================================================

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# Profile persistent — Cloudflare mengenali browser yang sama setiap siklus
_BROWSER_PROFILE_DIR = Path("data/browser_profile")

# Konfigurasi polling Cloudflare challenge
_CF_CHALLENGE_MAX_WAIT = 45   # detik maksimal menunggu
_CF_POLL_INTERVAL      = 2    # detik antar cek

# Direktori untuk file diagnostic
_LOGS_DIR = Path("logs")

# Modul-level session cache — di-share sepanjang hidup proses
_session: requests.Session | None = None

_SEP = "━" * 44


# ==================================================
# DIAGNOSTIC HELPERS
# ==================================================

def _safe_eval(page, js: str, default=None):
    """Jalankan JavaScript di browser; kembalikan default jika gagal."""
    try:
        return page.evaluate(js)
    except Exception:
        return default


def _get_cookie_names(context) -> list[str]:
    """Kembalikan list nama cookie dari context (tidak termasuk value)."""
    try:
        return [c.get("name", "") for c in context.cookies()]
    except Exception:
        return []


def _has_cookie(context, name: str) -> bool:
    """Cek apakah cookie dengan nama tertentu ada di context."""
    return name in _get_cookie_names(context)


def _count_storage(page, storage_type: str) -> int:
    """
    Hitung jumlah item di localStorage / sessionStorage.
    storage_type: "localStorage" | "sessionStorage"
    """
    return _safe_eval(page, f"{storage_type}.length", default=0) or 0


def _is_cf_iframe_present(page) -> bool:
    """Deteksi apakah iframe challenge Cloudflare masih ada di DOM."""
    result = _safe_eval(
        page,
        """
        !!document.querySelector(
            'iframe[src*="challenges.cloudflare.com"], '
            'iframe[src*="cdn-cgi/challenge"]'
        )
        """,
        default=False,
    )
    return bool(result)


def _get_ready_state(page) -> str:
    """Ambil document.readyState dari browser."""
    return _safe_eval(page, "document.readyState", default="unknown") or "unknown"


def _log_browser_state(page, context, elapsed: int) -> None:
    """
    Log state lengkap browser selama polling Cloudflare challenge.
    Semua error ditangkap agar polling tidak crash.
    """
    try:
        title          = page.title()
    except Exception:
        title          = "(error)"
    try:
        url            = page.url
    except Exception:
        url            = "(error)"

    ready_state    = _get_ready_state(page)
    cf_challenge   = _is_cloudflare_challenge(page)
    cf_iframe      = _is_cf_iframe_present(page)
    has_clearance  = _has_cookie(context, "cf_clearance")
    has_cf_bm      = _has_cookie(context, "__cf_bm")
    cookie_names   = _get_cookie_names(context)
    local_len      = _count_storage(page, "localStorage")
    session_len    = _count_storage(page, "sessionStorage")

    logger.info(_SEP)
    logger.info(f"[CLIENT] Waiting challenge... ({elapsed}s)")
    logger.info(f"  Title                : {title}")
    logger.info(f"  URL                  : {url}")
    logger.info(f"  ReadyState           : {ready_state}")
    logger.info(f"  Cloudflare Challenge : {'YES' if cf_challenge else 'NO'}")
    logger.info(f"  Cloudflare iframe    : {'YES' if cf_iframe else 'NO'}")
    logger.info(f"  cf_clearance         : {'YES' if has_clearance else 'NO'}")
    logger.info(f"  __cf_bm              : {'YES' if has_cf_bm else 'NO'}")
    logger.info(f"  Cookies              : {len(cookie_names)}")
    logger.info(f"  LocalStorage         : {local_len}")
    logger.info(f"  SessionStorage       : {session_len}")
    logger.info(_SEP)


def _log_fingerprint(page) -> None:
    """
    Log fingerprint browser satu kali setelah halaman terbuka.
    Menggunakan evaluate() agar membaca nilai nyata dari browser instance.
    """
    fp = {
        "Navigator.webdriver":         _safe_eval(page, "navigator.webdriver"),
        "Navigator.languages":         _safe_eval(page, "JSON.stringify(navigator.languages)"),
        "Navigator.platform":          _safe_eval(page, "navigator.platform"),
        "Navigator.vendor":            _safe_eval(page, "navigator.vendor"),
        "Navigator.userAgent":         _safe_eval(page, "navigator.userAgent"),
        "Navigator.hardwareConcurrency": _safe_eval(page, "navigator.hardwareConcurrency"),
        "Navigator.deviceMemory":      _safe_eval(page, "navigator.deviceMemory"),
        "Navigator.maxTouchPoints":    _safe_eval(page, "navigator.maxTouchPoints"),
        "Timezone":                    _safe_eval(page, "Intl.DateTimeFormat().resolvedOptions().timeZone"),
        "Screen Resolution":           _safe_eval(page, "`${screen.width}x${screen.height}`"),
        "Viewport":                    _safe_eval(page, "`${window.innerWidth}x${window.innerHeight}`"),
        "Color Scheme":                _safe_eval(
            page,
            "window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'",
        ),
    }

    logger.info(_SEP)
    logger.info("[CLIENT] Browser Fingerprint")
    for key, val in fp.items():
        logger.info(f"  {key:<34}: {val}")
    logger.info(_SEP)


def _log_cookies(context, label: str = "Cookie list") -> None:
    """Log seluruh nama cookie (tanpa value) ke logger."""
    names = _get_cookie_names(context)
    logger.info(f"[CLIENT] {label} ({len(names)} cookies):")
    for name in names:
        logger.info(f"  • {name}")


def _save_diagnostic_files(page, prefix: str) -> None:
    """
    Simpan HTML dan screenshot ke logs/ dengan prefix tertentu.
    prefix: "challenge_success" | "challenge_timeout"
    """
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)

        html_path = _LOGS_DIR / f"{prefix}.html"
        png_path  = _LOGS_DIR / f"{prefix}.png"

        try:
            html_path.write_text(page.content(), encoding="utf-8")
            logger.info(f"[CLIENT] Saved HTML : {html_path}")
        except Exception as exc:
            logger.warning(f"[CLIENT] Failed to save HTML: {exc}")

        try:
            page.screenshot(path=str(png_path), full_page=True)
            logger.info(f"[CLIENT] Saved screenshot : {png_path}")
        except Exception as exc:
            logger.warning(f"[CLIENT] Failed to save screenshot: {exc}")

    except Exception as exc:
        logger.warning(f"[CLIENT] Diagnostic save failed: {exc}")


def _attach_event_listeners(page) -> None:
    """
    Pasang event listener untuk console, page error, request failed,
    dan response ≥400. Semua bersifat diagnostic saja.
    """
    # Console messages dari browser
    def _on_console(msg):
        try:
            mtype = msg.type  # "log" | "error" | "warning" | "info"
            text  = msg.text
            logger.info(f"[CONSOLE:{mtype.upper()}] {text}")
        except Exception:
            pass

    # JavaScript exceptions yang tidak tertangkap
    def _on_page_error(exc):
        try:
            logger.warning(f"[CLIENT] Page error: {exc}")
        except Exception:
            pass

    # Request yang gagal di network level
    def _on_request_failed(req):
        try:
            logger.warning(
                f"[CLIENT] Request failed: {req.method} {req.url} "
                f"— {req.failure}"
            )
        except Exception:
            pass

    # Response HTTP ≥400 — termasuk 403 Cloudflare
    def _on_response(resp):
        try:
            status = resp.status
            url    = resp.url

            # Selalu log redirect / challenge URL yang menarik
            if (
                "challenges.cloudflare.com" in url
                or "cdn-cgi/challenge" in url
            ):
                logger.info(f"[CLIENT] [NETWORK] CF challenge URL → {url}")

            if status >= 400:
                content_type = resp.headers.get("content-type", "")
                location     = resp.headers.get("location", "")
                logger.warning(
                    f"[CLIENT] [NETWORK] HTTP {status} ← {url} "
                    f"| Content-Type: {content_type}"
                    + (f" | Redirect: {location}" if location else "")
                )
        except Exception:
            pass

    page.on("console",       _on_console)
    page.on("pageerror",     _on_page_error)
    page.on("requestfailed", _on_request_failed)
    page.on("response",      _on_response)


# ==================================================
# CLOUDFLARE DETECTION & WAIT
# ==================================================

def _is_cloudflare_challenge(page) -> bool:
    """
    Cek apakah halaman saat ini masih dalam Cloudflare Challenge atau
    sedang dalam proses verifikasi JavaScript Cloudflare.

    Indikator Cloudflare masih aktif:
        - Title mengandung "Just a moment" atau "Tunggu sebentar"
        - URL mengandung "__cf_chl"
        - HTML mengandung "challenges.cloudflare.com" (JS challenge aktif)
        - window.__cfRLUnblockHandlers ada di global scope
        - Elemen form/div challenge Cloudflare ada di DOM
    """
    try:
        title = page.title()
        url   = page.url
        html  = page.content()

        if "__cf_chl" in url:
            return True
        if "Just a moment" in title or "Tunggu sebentar" in title:
            return True
        if "challenges.cloudflare.com" in html:
            return True

        # Cek window.__cfRLUnblockHandlers (Cloudflare JS global)
        cf_handler = _safe_eval(
            page,
            "typeof window.__cfRLUnblockHandlers !== 'undefined'",
            default=False,
        )
        if cf_handler:
            return True

        # Cek elemen DOM challenge Cloudflare
        cf_elem = _safe_eval(
            page,
            """
            !!(
                document.querySelector('#challenge-form') ||
                document.querySelector('#cf-challenge-running') ||
                document.querySelector('.cf-browser-verification')
            )
            """,
            default=False,
        )
        if cf_elem:
            return True

        return False
    except Exception:
        return False


def _wait_for_challenge(page, context) -> None:
    """
    Polling setiap _CF_POLL_INTERVAL detik sampai Cloudflare Challenge benar-benar selesai.
    Selesai = tidak ada lagi indikator Cloudflare di title, URL, maupun konten halaman.
    Maksimal _CF_CHALLENGE_MAX_WAIT detik.

    Setiap iterasi menampilkan Browser State Logging lengkap.
    Pada sukses: simpan challenge_success.html + .png, log timing.
    Pada timeout: simpan challenge_timeout.html + .png, log cookie list.

    Raises:
        WebsiteError(CLOUDFLARE_PROTECTION): Jika challenge tidak selesai tepat waktu.
    """
    elapsed    = 0
    t_start    = time.monotonic()

    while elapsed < _CF_CHALLENGE_MAX_WAIT:
        time.sleep(_CF_POLL_INTERVAL)
        elapsed += _CF_POLL_INTERVAL

        # [1] Browser State Logging setiap polling
        _log_browser_state(page, context, elapsed)

        if not _is_cloudflare_challenge(page):
            # [3] Challenge Success
            solve_time = time.monotonic() - t_start
            logger.info("[CLIENT] Challenge solved successfully.")
            logger.info(f"[CLIENT] Solve time   : {solve_time:.2f} seconds")

            has_clearance = _has_cookie(context, "cf_clearance")
            logger.info(
                f"[CLIENT] cf_clearance : {'acquired' if has_clearance else 'not yet acquired'}"
            )

            # Log cookie list pasca-solve
            _log_cookies(context, "Cookies after challenge solved")

            # Simpan HTML + screenshot
            _save_diagnostic_files(page, "challenge_success")

            # Tunggu halaman stabil setelah redirect post-challenge
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except PlaywrightTimeout:
                pass  # Non-fatal — lanjut ambil konten
            return

    # [4] Challenge Timeout
    logger.warning(f"[CLIENT] Challenge timeout after {elapsed}s")

    # Log cookie list saat timeout
    _log_cookies(context, "Cookies at timeout")

    # Simpan HTML + screenshot untuk analisis
    _save_diagnostic_files(page, "challenge_timeout")

    raise WebsiteError(
        WebsiteStatus.CLOUDFLARE_PROTECTION,
        "Cloudflare challenge was not solved within timeout",
    )


# ==================================================
# BROWSER LAUNCH
# ==================================================

# Argumen launch yang sama dipakai oleh Chrome maupun Chromium
_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
]

# Opsi context yang sama dipakai oleh Chrome maupun Chromium
_CONTEXT_OPTIONS: dict = dict(
    user_data_dir       = str(_BROWSER_PROFILE_DIR),
    headless            = True,
    args                = _LAUNCH_ARGS,
    user_agent          = _USER_AGENT,
    viewport            = {"width": 1366, "height": 768},
    locale              = "id-ID",
    timezone_id         = "Asia/Jakarta",
    color_scheme        = "light",
    java_script_enabled = True,
    extra_http_headers  = {
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    },
)


def _launch_context(pw):
    """
    Coba launch Google Chrome Stable terlebih dahulu.
    Jika Chrome tidak tersedia / gagal, fallback ke Chromium bawaan Playwright.

    Urutan:
        1. pw.chromium.launch_persistent_context(..., channel="chrome")
        2. pw.chromium.launch_persistent_context(...)  ← tanpa channel

    Returns:
        BrowserContext yang sudah siap dipakai.
    """
    # Coba Google Chrome Stable
    logger.info("[CLIENT] Launching Google Chrome...")
    try:
        context = pw.chromium.launch_persistent_context(
            channel = "chrome",
            **_CONTEXT_OPTIONS,
        )
        logger.info("[CLIENT] Google Chrome launched successfully.")
        return context

    except Exception as chrome_exc:
        logger.warning(f"[CLIENT] Google Chrome not found. ({chrome_exc})")
        logger.info("[CLIENT] Falling back to bundled Chromium.")

    # Fallback: Chromium bawaan Playwright
    context = pw.chromium.launch_persistent_context(**_CONTEXT_OPTIONS)
    logger.info("[CLIENT] Bundled Chromium launched successfully.")
    return context


# ==================================================
# PLAYWRIGHT CONTEXT HELPER
# ==================================================

def _run_in_browser(callback) -> object:
    """
    Buka Playwright persistent context, jalankan callback(page, context),
    tutup context (profile tersimpan ke disk), kembalikan hasil callback.

    Args:
        callback: function(page, context) -> Any

    Raises:
        WebsiteError: Jika terjadi error saat membuka halaman atau challenge timeout.
    """
    _BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # [9] Performance Timing — t0: start
    t_start = time.monotonic()

    try:
        with sync_playwright() as pw:

            # [9] Launch timing
            t_launch = time.monotonic()
            context  = _launch_context(pw)
            logger.info(
                f"[CLIENT] [TIMING] Launch     : {time.monotonic() - t_launch:.2f}s"
            )

            page = context.new_page()

            # [7][8] Pasang event listener console, pageerror, requestfailed, response
            _attach_event_listeners(page)

            # Terapkan stealth sebelum navigasi apapun
            # agar fingerprint headless tidak terdeteksi Cloudflare
            t_stealth = time.monotonic()
            Stealth(
                navigator_languages_override = ("id-ID", "id", "en-US", "en"),
                navigator_platform_override  = "Win32",
                navigator_vendor_override    = "Google Inc.",
            ).use_sync(page)
            logger.info("[CLIENT] Stealth applied")
            logger.info(
                f"[CLIENT] [TIMING] Stealth    : {time.monotonic() - t_stealth:.2f}s"
            )

            logger.info("[CLIENT] Opening website...")

            # [9] Open website timing
            t_open = time.monotonic()
            try:
                # domcontentloaded (bukan networkidle) — Cloudflare challenge
                # tidak pernah mencapai networkidle sehingga selalu timeout
                page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
            except PlaywrightTimeout as exc:
                context.close()
                raise WebsiteError(
                    WebsiteStatus.TIMEOUT,
                    "Timeout saat membuka halaman website",
                ) from exc

            logger.info(
                f"[CLIENT] [TIMING] Open site  : {time.monotonic() - t_open:.2f}s"
            )

            # [2] Fingerprint logging — satu kali setelah halaman terbuka
            _log_fingerprint(page)

            # Deteksi dan tunggu Cloudflare challenge
            t_cf = time.monotonic()
            if _is_cloudflare_challenge(page):
                logger.info("[CLIENT] Cloudflare challenge detected")
                logger.info(
                    f"[CLIENT] [TIMING] CF detected: {time.monotonic() - t_cf:.2f}s"
                )
                # [1][3][4][6] — diagnostic semuanya di dalam _wait_for_challenge
                _wait_for_challenge(page, context)
                logger.info(
                    f"[CLIENT] [TIMING] CF solved  : {time.monotonic() - t_cf:.2f}s"
                )
            else:
                logger.info("[CLIENT] No challenge detected")

            # Jalankan callback dengan page dan context yang sudah terbypass
            result = callback(page, context)

            context.close()   # Profile tersimpan ke disk

            # [9] Total browser lifetime
            logger.info(
                f"[CLIENT] [TIMING] Total      : {time.monotonic() - t_start:.2f}s"
            )
            return result

    except WebsiteError:
        raise
    except Exception as exc:
        msg = str(exc)
        if any(k in msg for k in ("ERR_NAME_NOT_RESOLVED", "getaddrinfo", "nodename")):
            raise WebsiteError(WebsiteStatus.DNS_ERROR, msg) from exc
        raise WebsiteError(WebsiteStatus.UNKNOWN, msg) from exc


def _extract_session(page, context) -> requests.Session:
    """
    Callback untuk _run_in_browser: ekstrak cookies dari context
    dan buat requests.Session.

    Menggunakan API storage state Playwright yang lebih lengkap dari context.cookies()
    untuk memastikan semua cookies (termasuk HTTPOnly) ikut terbawa.
    """
    # storage_state() lebih andal daripada context.cookies()
    # karena mencakup cookies dari semua origins yang dikunjungi
    try:
        storage  = context.storage_state()
        raw_cookies = storage.get("cookies", [])
    except Exception:
        raw_cookies = context.cookies()

    session = requests.Session()
    session.headers.update({
        "User-Agent":       _USER_AGENT,
        "Referer":          BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Accept-Language":  "id-ID,id;q=0.9,en;q=0.8",
    })
    for c in raw_cookies:
        session.cookies.set(
            c.get("name", ""),
            c.get("value", ""),
            domain = c.get("domain", ""),
            path   = c.get("path", "/"),
        )

    logger.info(f"[CLIENT] Session ready — {len(raw_cookies)} cookies obtained")
    return session


def _fetch_html_via_playwright(page, context) -> str:
    """
    Callback untuk _run_in_browser: ambil HTML halaman utama langsung
    dari Playwright (sudah ter-bypass Cloudflare), dan sekaligus
    update session dengan cookies terbaru.
    """
    global _session

    # Ambil cookies dan update session
    _session = _extract_session(page, context)

    # Ambil HTML langsung dari page yang sudah terbuka
    return page.content()


# ==================================================
# SESSION MANAGEMENT
# ==================================================

def _build_session() -> requests.Session:
    """
    Buka Playwright, lewati Cloudflare, ekstrak cookies ke requests.Session baru.
    Session di-cache di modul level untuk dipakai oleh request berikutnya.
    """
    session = _run_in_browser(_extract_session)
    return session  # type: ignore[return-value]


def _get_session(force_refresh: bool = False) -> requests.Session:
    """Kembalikan session yang di-cache; buat baru jika belum ada atau force."""
    global _session
    if _session is None or force_refresh:
        _session = _build_session()
    return _session


# ==================================================
# ERROR CLASSIFICATION
# ==================================================

def _classify(exc: Exception) -> WebsiteError:
    """Petakan requests exception ke WebsiteError dengan status tepat."""
    msg = str(exc)
    if isinstance(exc, requests.exceptions.ConnectionError):
        if any(k in msg for k in ("Name or service not known", "getaddrinfo", "nodename")):
            return WebsiteError(WebsiteStatus.DNS_ERROR, msg)
        return WebsiteError(WebsiteStatus.HTTP_ERROR, msg)
    if isinstance(exc, requests.exceptions.Timeout):
        return WebsiteError(WebsiteStatus.TIMEOUT, msg)
    if isinstance(exc, requests.exceptions.HTTPError):
        return WebsiteError(WebsiteStatus.HTTP_ERROR, msg)
    return WebsiteError(WebsiteStatus.UNKNOWN, msg)


# ==================================================
# PUBLIC INTERFACE
# ==================================================

def fetch_html(
    url:  str,
    data: dict[str, str] | None = None,
    *,
    _retry: bool = True,
) -> str:
    """
    Ambil HTML dari URL.

    Untuk GET ke BASE_URL (halaman utama):
        → Playwright membuka halaman, bypass Cloudflare, kembalikan HTML langsung.
          Cookies diperbarui di saat yang sama.

    Untuk GET/POST lainnya (quota endpoint):
        → requests.Session menggunakan cookies dari Playwright.
        → Jika 403 terdeteksi, Playwright refresh session lalu retry sekali.

    Args:
        url:   URL tujuan.
        data:  Jika diisi → POST request. Jika None → GET request.

    Returns:
        HTML body sebagai string.

    Raises:
        WebsiteError: Dengan WebsiteStatus yang sesuai jika request gagal.
    """
    # GET ke halaman utama → pakai Playwright langsung
    # (bypass Cloudflare + update session sekaligus)
    if data is None and url == BASE_URL:
        return _run_in_browser(_fetch_html_via_playwright)  # type: ignore[return-value]

    # GET/POST ke endpoint lain → pakai requests.Session
    session = _get_session()

    try:
        if data is not None:
            resp = session.post(url, data=data, timeout=30)
        else:
            resp = session.get(url, timeout=30)

    except WebsiteError:
        raise
    except Exception as exc:
        raise _classify(exc) from exc

    # Cloudflare 403 → refresh session sekali lalu retry
    if resp.status_code == 403:
        if _retry:
            logger.warning("[CLIENT] HTTP 403 — refreshing Playwright session...")
            _get_session(force_refresh=True)
            return fetch_html(url, data, _retry=False)

        raise WebsiteError(
            WebsiteStatus.CLOUDFLARE_PROTECTION,
            "HTTP 403 — Cloudflare Protection (session refresh tidak berhasil)",
        )

    if resp.status_code >= 500:
        raise WebsiteError(
            WebsiteStatus.HTTP_ERROR,
            f"HTTP {resp.status_code} — Server Error",
        )

    if not resp.ok:
        raise WebsiteError(
            WebsiteStatus.HTTP_ERROR,
            f"HTTP {resp.status_code}",
        )

    return resp.text
