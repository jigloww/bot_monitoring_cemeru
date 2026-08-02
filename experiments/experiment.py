"""Experiment configuration and immutable artifact storage."""
from __future__ import annotations

import re

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from experiments.utils import now_iso, write_json_exclusive, write_text_exclusive


_EXPERIMENT_PATTERN = re.compile(r"^exp_(\d+)$")


@dataclass(frozen=True)
class ExperimentConfig:
    """Resolved settings for one before/after fingerprint experiment."""

    project_root: Path
    reports_root: Path
    baseline_path: Path
    url: str
    channel: str = ""
    headless: bool = True
    profile: Path | None = None
    wait_ms: int = 5_000
    label: str = ""


@dataclass(frozen=True)
class Experiment:
    """A uniquely allocated experiment directory whose files are write-once."""

    experiment_id: str
    directory: Path
    started_at: str

    @classmethod
    def create(cls, reports_root: Path) -> "Experiment":
        """Atomically reserve the next exp_NNN directory."""
        reports_root.mkdir(parents=True, exist_ok=True)
        numbers = []
        for path in reports_root.iterdir():
            if not path.is_dir():
                continue
            match = _EXPERIMENT_PATTERN.match(path.name)
            if match:
                numbers.append(int(match.group(1)))

        number = max(numbers, default=0) + 1
        while True:
            experiment_id = f"exp_{number:03d}"
            directory = reports_root / experiment_id
            try:
                directory.mkdir(exist_ok=False)
                return cls(
                    experiment_id=experiment_id,
                    directory=directory,
                    started_at=now_iso(),
                )
            except FileExistsError:
                number += 1

    def artifact(self, filename: str) -> Path:
        """Return a safe direct-child artifact path."""
        if Path(filename).name != filename:
            raise ValueError(f"Artifact must be a filename, got: {filename}")
        return self.directory / filename

    def write_json(self, filename: str, data: Any) -> Path:
        path = self.artifact(filename)
        write_json_exclusive(path, data)
        return path

    def write_text(self, filename: str, text: str) -> Path:
        path = self.artifact(filename)
        write_text_exclusive(path, text)
        return path

    def record_failure(self, metadata: dict[str, Any], error: dict[str, Any]) -> None:
        """Commit a failed experiment without overwriting any partial artifacts."""
        failure_path = self.artifact("failure.json")
        metadata_path = self.artifact("metadata.json")
        if not failure_path.exists():
            write_json_exclusive(failure_path, error)
        if not metadata_path.exists():
            write_json_exclusive(metadata_path, metadata)

