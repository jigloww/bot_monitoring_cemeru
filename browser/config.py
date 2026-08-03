"""Typed, serializable configuration for the browser launcher."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BrowserConfig:
    """All orchestration options accepted by :func:`launch_browser`.

    The class contains no stealth defaults.  ``enable_stealth`` only controls
    whether a caller-supplied hook is invoked by the launcher.
    """

    browser: str = "chromium"  # chrome | chromium | bundled
    executable_path: str | Path | None = None
    channel: str = ""
    headless: bool = True
    persistent: bool = False
    profile_path: str | Path | None = None
    user_data_dir: str | Path | None = None
    viewport: tuple[int, int] | dict[str, int] | None = None
    user_agent: str | None = None
    locale: str | None = None
    timezone: str | None = None
    extra_http_headers: dict[str, str] | None = None
    downloads_dir: str | Path | None = None
    permissions: list[str] = field(default_factory=list)
    proxy: dict[str, Any] | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    geolocation: dict[str, float] | None = None
    color_scheme: str | None = None
    reduced_motion: str | None = None
    java_script_enabled: bool = True
    accept_downloads: bool = True
    ignore_https_errors: bool = False
    enable_stealth: bool = False
    url: str = "about:blank"
    timeout: int = 60_000

    def __post_init__(self) -> None:
        self.browser = str(self.browser or "chromium").lower()
        if self.browser not in {"chrome", "chromium", "bundled"}:
            raise ValueError("browser must be chrome, chromium, or bundled")
        if self.viewport is not None:
            if isinstance(self.viewport, tuple):
                if len(self.viewport) != 2 or any(int(value) <= 0 for value in self.viewport):
                    raise ValueError("viewport tuple must contain positive width and height")
            elif isinstance(self.viewport, dict):
                if int(self.viewport.get("width", 0)) <= 0 or int(self.viewport.get("height", 0)) <= 0:
                    raise ValueError("viewport requires positive width and height")
            else:
                raise ValueError("viewport must be a (width, height) tuple or mapping")
        if self.extra_http_headers is not None:
            self.extra_http_headers = {str(key): str(value) for key, value in self.extra_http_headers.items()}
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")

    def context_options(self) -> dict[str, Any]:
        """Return Playwright context options without mutating this config."""
        options: dict[str, Any] = {
            "java_script_enabled": self.java_script_enabled,
            "accept_downloads": self.accept_downloads,
            "ignore_https_errors": self.ignore_https_errors,
        }
        if self.viewport is not None:
            options["viewport"] = {"width": int(self.viewport[0]), "height": int(self.viewport[1])} if isinstance(self.viewport, tuple) else {"width": int(self.viewport["width"]), "height": int(self.viewport["height"])}
        if self.user_agent: options["user_agent"] = self.user_agent
        if self.locale: options["locale"] = self.locale
        if self.timezone: options["timezone_id"] = self.timezone
        if self.extra_http_headers: options["extra_http_headers"] = dict(self.extra_http_headers)
        if self.permissions: options["permissions"] = list(dict.fromkeys(self.permissions))
        if self.geolocation is not None: options["geolocation"] = dict(self.geolocation)
        if self.color_scheme: options["color_scheme"] = self.color_scheme
        if self.reduced_motion: options["reduced_motion"] = self.reduced_motion
        return options

    def launch_options(self) -> dict[str, Any]:
        """Return Playwright browser launch options."""
        options: dict[str, Any] = {"headless": self.headless, "args": list(self.args)}
        if self.channel: options["channel"] = self.channel
        elif self.browser == "chrome" and not self.executable_path: options["channel"] = "chrome"
        if self.executable_path: options["executable_path"] = str(self.executable_path)
        if self.downloads_dir: options["downloads_path"] = str(self.downloads_dir)
        if self.proxy: options["proxy"] = dict(self.proxy)
        if self.env: options["env"] = dict(self.env)
        return options

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("executable_path", "profile_path", "user_data_dir", "downloads_dir"):
            if data[key] is not None: data[key] = str(data[key])
        if isinstance(self.viewport, tuple): data["viewport"] = {"width": self.viewport[0], "height": self.viewport[1]}
        return data

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BrowserConfig":
        data = dict(value)
        viewport = data.get("viewport")
        if isinstance(viewport, dict): data["viewport"] = {"width": int(viewport["width"]), "height": int(viewport["height"])}
        return cls(**data)
