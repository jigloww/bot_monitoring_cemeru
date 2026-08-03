"""Single entry point for Playwright browser orchestration."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import BrowserConfig
from .context import create_context, create_persistent_context, invoke_stealth_hook, new_context, persistent_context
from .profile import ProfileManager


def _executable_available(path: str | Path | None) -> bool:
    if not path: return False
    return Path(path).expanduser().is_file()


def _browser_type(playwright: Any, config: BrowserConfig) -> Any:
    return playwright.chromium


def _launch(browser_type: Any, config: BrowserConfig) -> Any:
    options = config.launch_options()
    if config.browser == "chrome" and not config.executable_path and not config.channel:
        options["channel"] = "chrome"
    try:
        return browser_type.launch(**options)
    except Exception:
        # Chrome channels are optional.  Falling back to bundled Chromium keeps
        # the launcher usable on CI/VPS hosts without Chrome installed.
        options.pop("channel", None)
        options.pop("executable_path", None)
        return browser_type.launch(**options)


@dataclass
class BrowserSession:
    playwright: Any
    browser: Any
    context: Any
    page: Any
    persistent: bool
    profile: ProfileManager | None = None
    owns_playwright: bool = False
    _closed: bool = False

    def close(self) -> None:
        if self._closed: return
        self._closed = True
        try:
            if self.context is not None: self.context.close()
        except Exception:
            # Cleanup must never mask the monitoring/worker exception that
            # triggered shutdown.
            pass
        finally:
            if self.browser is not None and not self.persistent:
                try: self.browser.close()
                except Exception: pass
            if self.profile is not None: self.profile.cleanup()
            if self.owns_playwright:
                try: self.playwright.stop()
                except Exception: pass

    def __iter__(self):
        """Allow ``browser, context, page = launch_browser(...)`` callers."""
        yield self.browser
        yield self.context
        yield self.page

    def __enter__(self) -> "BrowserSession": return self
    def __exit__(self, _exc_type, _exc, _tb) -> None: self.close()


def launch_browser(config: BrowserConfig | dict[str, Any] | None = None, *, playwright: Any = None, stealth_hook: Any = None) -> BrowserSession:
    """Launch a browser and return a ready context/page session.

    ``stealth_hook`` is intentionally dependency-injected.  A registry or
    module loader can be passed by production callers without the launcher
    importing or modifying stealth code itself.
    """
    if config is None:
        config = BrowserConfig()
    elif isinstance(config, dict):
        config = BrowserConfig.from_dict(config)
    elif not isinstance(config, BrowserConfig):
        raise TypeError("config must be BrowserConfig, mapping, or None")
    owns_playwright = playwright is None
    if playwright is None:
        from playwright.sync_api import sync_playwright
        playwright = sync_playwright().start()
    browser_type = _browser_type(playwright, config)
    profile: ProfileManager | None = None
    browser = None
    context = None
    persistent = bool(config.persistent)
    try:
        if persistent:
            profile_path = config.profile_path or config.user_data_dir
            profile = ProfileManager(profile_path, persistent=True)
            context = create_persistent_context(playwright, profile, config)
            # Persistent Playwright contexts expose their Browser through the
            # context.  Returning it when available keeps the session shape
            # identical for persistent and temporary launches.
            browser = getattr(context, "browser", None)
        else:
            browser = _launch(browser_type, config)
            context = create_context(browser, config)
        if config.enable_stealth:
            invoke_stealth_hook(stealth_hook, context)
        page = context.new_page()
        if config.url and config.url != "about:blank":
            page.goto(config.url, wait_until="domcontentloaded", timeout=config.timeout)
        return BrowserSession(playwright, browser, context, page, persistent, profile, owns_playwright)
    except Exception:
        if context is not None:
            try: context.close()
            except Exception: pass
        if browser is not None and not persistent:
            try: browser.close()
            except Exception: pass
        if profile is not None: profile.cleanup()
        if owns_playwright:
            try: playwright.stop()
            except Exception: pass
        raise


def available_executables() -> dict[str, str | None]:
    names = {
        "chrome": ["chrome", "chrome.exe", "google-chrome", "google-chrome.exe", "chromium", "chromium.exe", "chromium-browser", "chromium-browser.exe"],
        "chromium": ["chromium", "chromium.exe", "chromium-browser", "chromium-browser.exe"],
    }
    result: dict[str, str | None] = {}
    for key, candidates in names.items():
        result[key] = next((shutil.which(candidate) for candidate in candidates if shutil.which(candidate)), None)
    return result
