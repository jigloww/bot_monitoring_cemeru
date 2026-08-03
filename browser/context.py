"""Context construction and stealth hook integration."""
from __future__ import annotations

from typing import Any, Callable

from .config import BrowserConfig
from .profile import ProfileManager


def invoke_stealth_hook(hook: Any, context: Any) -> bool:
    """Invoke a caller-provided registry/install hook exactly once."""
    if hook is None:
        return False
    installer: Callable[..., Any] | None = None
    if callable(hook): installer = hook
    elif callable(getattr(hook, "install", None)): installer = hook.install
    elif callable(getattr(hook, "install_context", None)): installer = hook.install_context
    if installer is None:
        raise TypeError("stealth_hook must be callable or expose install(context)")
    installer(context)
    return True


def create_context(browser: Any, config: BrowserConfig) -> Any:
    return browser.new_context(**config.context_options())


def create_persistent_context(playwright: Any, profile: ProfileManager, config: BrowserConfig) -> Any:
    user_data = profile.create()
    options = config.launch_options()
    if config.browser == "chrome" and not config.executable_path and not config.channel:
        options["channel"] = "chrome"
    options.update(config.context_options())
    try:
        return playwright.chromium.launch_persistent_context(str(user_data), **options)
    except Exception:
        # A Chrome channel is optional on CI/VPS hosts.  Retry with the
        # bundled Chromium while preserving every other caller option.
        options.pop("channel", None)
        options.pop("executable_path", None)
        return playwright.chromium.launch_persistent_context(str(user_data), **options)


def new_context(browser: Any, config: BrowserConfig) -> Any:
    """Public alias matching Playwright's non-persistent context terminology."""
    return create_context(browser, config)


def persistent_context(playwright: Any, profile: ProfileManager, config: BrowserConfig) -> Any:
    """Public alias for creating a persistent context."""
    return create_persistent_context(playwright, profile, config)
