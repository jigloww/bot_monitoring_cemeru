"""Resource ownership and page registry for a managed browser session."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .launcher import BrowserSession


def _page_closed(page: Any) -> bool:
    checker = getattr(page, "is_closed", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    if checker is not None:
        return bool(checker)
    return False


class PageRegistry:
    """Identity-based registry that tolerates pages closing externally."""

    def __init__(self) -> None:
        self._pages: dict[int, Any] = {}

    def add(self, page: Any) -> Any:
        if page is not None:
            self._pages[id(page)] = page
        return page

    def discard(self, page: Any) -> None:
        if page is not None:
            self._pages.pop(id(page), None)

    def cleanup_closed(self) -> int:
        closed = [key for key, page in self._pages.items() if _page_closed(page)]
        for key in closed:
            self._pages.pop(key, None)
        return len(closed)

    def values(self) -> list[Any]:
        self.cleanup_closed()
        return list(self._pages.values())

    def clear(self) -> list[Any]:
        pages = list(self._pages.values())
        self._pages.clear()
        return pages

    def __len__(self) -> int:
        self.cleanup_closed()
        return len(self._pages)


@dataclass
class ManagedSession:
    """Owned launcher session plus its page registry."""

    launcher_session: BrowserSession
    pages: PageRegistry = field(default_factory=PageRegistry)

    @property
    def browser(self) -> Any:
        return self.launcher_session.browser

    @property
    def context(self) -> Any:
        return self.launcher_session.context

    def close_pages(self) -> None:
        for page in self.pages.clear():
            try:
                if not _page_closed(page) and callable(getattr(page, "close", None)):
                    page.close()
            except Exception:
                pass

    def close(self) -> None:
        self.close_pages()
        self.launcher_session.close()
