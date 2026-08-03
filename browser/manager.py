"""High-level browser lifecycle manager built on :func:`launch_browser`."""
from __future__ import annotations

import threading
import time
from typing import Any

from .config import BrowserConfig
from .health import HealthSnapshot, HealthStatus
from .launcher import BrowserSession, launch_browser
from .session import ManagedSession


def _call_listener(target: Any, event: str, callback: Any) -> None:
    on = getattr(target, "on", None)
    if callable(on):
        try:
            on(event, callback)
        except Exception:
            pass


class BrowserSessionManager:
    """Own one browser lifecycle and recover only the browser when it fails.

    The manager deliberately delegates all browser creation and profile
    handling to ``launch_browser``.  It never retries pages, navigation, or
    scraping work; restart recovery only recreates browser resources.
    """

    def __init__(
        self,
        config: BrowserConfig | dict[str, Any] | None = None,
        *,
        playwright: Any = None,
        stealth_hook: Any = None,
    ) -> None:
        if config is None:
            config = BrowserConfig()
        elif isinstance(config, dict):
            config = BrowserConfig.from_dict(config)
        elif not isinstance(config, BrowserConfig):
            raise TypeError("config must be BrowserConfig, mapping, or None")
        self.config = config
        self.playwright = playwright
        self.stealth_hook = stealth_hook
        self._session: ManagedSession | None = None
        self._status = HealthStatus.STOPPED
        self._reason: str | None = None
        self._started_at: float | None = None
        self._restart_count = 0
        self._lock = threading.RLock()
        self._recovering = False
        self._shutdown_requested = False

    def _alive(self, resource: Any, *, closed_method: str = "is_closed") -> bool:
        if resource is None:
            return False
        connected = getattr(resource, "is_connected", None)
        if callable(connected):
            try:
                return bool(connected())
            except Exception:
                return False
        closed = getattr(resource, closed_method, None)
        if callable(closed):
            try:
                return not bool(closed())
            except Exception:
                return False
        return True

    def _context_alive_locked(self) -> bool:
        return self._alive(self._session.context) if self._session is not None else False

    def _browser_alive_locked(self) -> bool:
        if self._session is None:
            return False
        browser = self._session.browser
        # Persistent contexts may not expose a Browser object.  In that case
        # context liveness is the authoritative browser-process signal.
        return self._alive(browser) if browser is not None else self._context_alive_locked()

    def _set_listener_callbacks_locked(self, session: ManagedSession) -> None:
        _call_listener(session.context, "close", lambda *_args: self._on_context_closed())
        _call_listener(session.context, "page", lambda page, *_args: self._register_page(page))
        if session.browser is not None:
            _call_listener(session.browser, "disconnected", lambda *_args: self._on_browser_disconnected())

    def _register_page(self, page: Any) -> Any:
        with self._lock:
            if self._session is None or self._shutdown_requested:
                return page
            self._session.pages.add(page)
            _call_listener(page, "close", lambda *_args: self._on_page_closed(page))
            return page

    def _on_page_closed(self, page: Any) -> None:
        with self._lock:
            if self._session is not None:
                self._session.pages.discard(page)

    def _on_context_closed(self) -> None:
        with self._lock:
            if self._status in {HealthStatus.STOPPING, HealthStatus.STOPPED} or self._recovering:
                return
            self._recover_locked("context closed")

    def _on_browser_disconnected(self) -> None:
        with self._lock:
            if self._status in {HealthStatus.STOPPING, HealthStatus.STOPPED} or self._recovering:
                return
            self._recover_locked("browser disconnected")

    def _launch_locked(self) -> None:
        self._status = HealthStatus.STARTING
        self._reason = None
        session = launch_browser(
            self.config,
            playwright=self.playwright,
            stealth_hook=self.stealth_hook,
        )
        managed = ManagedSession(session)
        managed.pages.add(session.page)
        self._session = managed
        self._set_listener_callbacks_locked(managed)
        self._register_page(session.page)
        self._started_at = time.monotonic()
        self._status = HealthStatus.RUNNING

    def start(self) -> "BrowserSessionManager":
        with self._lock:
            if self._status == HealthStatus.RUNNING:
                if self._context_alive_locked() and self._browser_alive_locked():
                    return self
                self._recover_locked("start liveness probe failed")
                if self._status == HealthStatus.RUNNING:
                    return self
                if self._status == HealthStatus.FAILED:
                    raise RuntimeError(self._reason or "browser recovery failed")
            if self._status == HealthStatus.STOPPING:
                raise RuntimeError("browser session is stopping")
            self._shutdown_requested = False
            try:
                self._launch_locked()
            except Exception as exc:
                self._status = HealthStatus.FAILED
                self._reason = str(exc)
                raise
            return self

    def _close_locked(self) -> None:
        session = self._session
        self._session = None
        self._started_at = None
        if session is None:
            return
        was_recovering = self._recovering
        self._recovering = True
        try:
            session.close()
        finally:
            self._recovering = was_recovering

    def stop(self) -> None:
        with self._lock:
            if self._status == HealthStatus.STOPPED and self._session is None:
                return
            self._status = HealthStatus.STOPPING
            cleanup_error: str | None = None
            try:
                self._close_locked()
            except Exception as exc:
                cleanup_error = f"shutdown cleanup: {exc}"
            finally:
                self._status = HealthStatus.STOPPED
                self._reason = cleanup_error

    def _recover_locked(self, reason: str) -> None:
        if self._recovering or self._shutdown_requested:
            return
        self._status = HealthStatus.RESTARTING
        self._reason = reason
        self._recovering = True
        try:
            self._close_locked()
            self._restart_count += 1
            self._launch_locked()
        except Exception as exc:
            self._status = HealthStatus.FAILED
            self._reason = f"{reason}: {exc}"
        finally:
            self._recovering = False

    def restart(self) -> "BrowserSessionManager":
        with self._lock:
            self._shutdown_requested = False
            if self._session is None:
                self._restart_count += 1
                try:
                    self._launch_locked()
                except Exception as exc:
                    self._status = HealthStatus.FAILED
                    self._reason = str(exc)
                    raise
                return self
            self._recover_locked("manual restart")
            if self._status == HealthStatus.FAILED:
                raise RuntimeError(self._reason or "browser restart failed")
            return self

    def is_running(self) -> bool:
        with self._lock:
            if self._status != HealthStatus.RUNNING:
                return False
            if not self._context_alive_locked() or not self._browser_alive_locked():
                self._recover_locked("liveness probe failed")
            return self._status == HealthStatus.RUNNING

    def health(self) -> HealthSnapshot:
        with self._lock:
            if self._status == HealthStatus.RUNNING and (not self._context_alive_locked() or not self._browser_alive_locked()):
                self._recover_locked("health probe failed")
            if self._session is None:
                context_alive = browser_alive = False
                page_count = 0
            else:
                context_alive = self._context_alive_locked()
                browser_alive = self._browser_alive_locked()
                page_count = len(self._session.pages)
            uptime = time.monotonic() - self._started_at if self._started_at is not None else 0.0
            return HealthSnapshot(
                status=self._status,
                uptime=uptime,
                restart_count=self._restart_count,
                page_count=page_count,
                context_alive=context_alive,
                browser_alive=browser_alive,
                reason=self._reason,
            )

    def get_browser(self) -> Any:
        with self._lock:
            return self._session.browser if self._session is not None else None

    def get_context(self) -> Any:
        with self._lock:
            return self._session.context if self._session is not None else None

    def new_page(self) -> Any:
        with self._lock:
            if not self.is_running() or self._session is None:
                raise RuntimeError("browser session is not running")
            page = self._session.context.new_page()
            self._register_page(page)
            return page

    def close_page(self, page: Any) -> None:
        with self._lock:
            if self._session is not None:
                self._session.pages.discard(page)
            try:
                checker = getattr(page, "is_closed", None)
                already_closed = bool(checker()) if callable(checker) else bool(checker)
                if page is not None and not already_closed:
                    page.close()
            except Exception:
                pass

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown_requested = True
        self.stop()

    def __enter__(self) -> "BrowserSessionManager":
        return self.start()

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.shutdown()
