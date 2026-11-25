"""JSON rename journal: record a batch so it can be undone.

A journal is a small JSON document written next to the renamed files
(default ``.bulk-rename-journal.json`` in the target directory, or any
path given with ``--journal``)::

    {
      "version": 1,
      "created_at": "2026-11-25T09:44:00+07:00",
      "directory": "/home/user/photos",
      "renames": [
        {"old": "IMG_0001.jpg", "new": "photo-0001.jpg"},
        ...
      ]
    }

Names are stored relative to the directory the rename ran in, so a
journal stays valid if the whole folder is moved. ``undo`` renames every
``new`` back to ``old``, skipping (and reporting) entries whose target
no longer exists.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

JOURNAL_VERSION = 1
DEFAULT_JOURNAL_NAME = ".bulk-rename-journal.json"


@dataclass
class Journal:
    """One completed rename batch."""

    directory: str
    renames: list[dict[str, str]] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "version": JOURNAL_VERSION,
            "created_at": self.created_at,
            "directory": self.directory,
            "renames": self.renames,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Journal":
        if data.get("version") != JOURNAL_VERSION:
            raise ValueError(
                f"unsupported journal version: {data.get('version')!r}"
            )
        return cls(
            directory=data["directory"],
            renames=list(data["renames"]),
            created_at=data.get("created_at", ""),
        )


def write_journal(path: str, journal: Journal) -> None:
    """Write ``journal`` as pretty JSON to ``path`` (UTF-8)."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(journal.to_dict(), fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def read_journal(path: str) -> Journal:
    """Read and validate a journal file."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: journal is not a JSON object")
    return Journal.from_dict(data)


def default_journal_path(directory: str) -> str:
    """The journal path used when the user gives none."""
    return os.path.join(directory, DEFAULT_JOURNAL_NAME)
