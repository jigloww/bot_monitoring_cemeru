"""Temporary and persistent browser profile lifecycle."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


class ProfileManager:
    """Create profiles and clean only profiles owned by this manager."""

    def __init__(self, path: str | Path | None = None, *, persistent: bool = False, prefix: str = "browser-profile-"):
        self.requested_path = Path(path).expanduser() if path else None
        self.persistent = persistent
        self.prefix = prefix
        self.path: Path | None = None
        self.owned = False

    def create(self) -> Path:
        if self.path is not None:
            self.path.mkdir(parents=True, exist_ok=True)
            return self.path
        if self.requested_path is not None:
            self.path = self.requested_path.resolve()
            self.path.mkdir(parents=True, exist_ok=True)
            self.owned = False
        else:
            self.path = Path(tempfile.mkdtemp(prefix=self.prefix)).resolve()
            self.owned = True
        return self.path

    def cleanup(self) -> None:
        """Remove a generated temporary profile, never a persistent profile."""
        if self.persistent or not self.owned or self.path is None:
            return
        target = self.path
        self.path = None
        if target.exists() and target.is_dir():
            shutil.rmtree(target)

    def __enter__(self) -> "ProfileManager":
        self.create()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.cleanup()
