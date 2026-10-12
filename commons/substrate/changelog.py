"""The changelog: every action, decision and change in a society, across all its runs, as plain debug logs (your
decision, 12 Oct).

One append-only JSONL file per calendar day in the society's `logs/` folder (`2026-10-12.jsonl`), each line an
activity-log entry plus the run it came from. When a log is opened, earlier days' files are gzipped, so the logs stay
small on disk; nothing is kept in memory (the activity log keeps its own bounded window for the dashboard). Texts are
already cut to a fixed length by the activity log; the full text of finished work is in the reports and dossiers.

`commons log NAME` reads it back (commons/interfaces/cli/changelog.py).
"""

from __future__ import annotations

import gzip
import json
import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path


class Changelog:
    def __init__(self, folder: str | Path, run: str):
        self.folder, self.run = Path(folder), run
        self.folder.mkdir(parents=True, exist_ok=True)
        self._day, self._file = "", None
        self._lock = threading.Lock()
        compress_old(self.folder)

    def __getstate__(self) -> dict:  # the file and the lock belong to this process; resuming reopens them
        return {"folder": self.folder, "run": self.run}

    def __setstate__(self, state: dict) -> None:
        self.__init__(state["folder"], state["run"])

    def write(self, entry: dict) -> None:
        with self._lock:
            day = time.strftime("%Y-%m-%d", time.localtime(entry.get("at") or time.time()))
            if day != self._day:  # a new day: a new file, and yesterday's is compressed next time a log opens
                if self._file:
                    self._file.close()
                self._day, self._file = day, open(self.folder / f"{day}.jsonl", "a")
            assert self._file is not None
            self._file.write(json.dumps({"run": self.run, **entry}, ensure_ascii=False) + "\n")
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None


def compress_old(folder: Path) -> None:
    """Gzip every day's file but today's (a day still being written stays plain)."""
    today = time.strftime("%Y-%m-%d")
    for path in sorted(folder.glob("*.jsonl")):
        if path.stem < today:
            with open(path, "rb") as src, gzip.open(path.with_suffix(".jsonl.gz"), "wb") as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()


def read(folder: str | Path) -> Iterator[dict]:
    """Every entry, oldest day first, compressed days included."""
    folder = Path(folder)
    days = sorted({p.name.split(".")[0] for p in folder.glob("*.jsonl*")})
    for day in days:
        for path in (folder / f"{day}.jsonl.gz", folder / f"{day}.jsonl"):
            if path.exists():
                with (gzip.open(path, "rt") if path.suffix == ".gz" else open(path)) as f:
                    for line in f:
                        try:
                            yield json.loads(line)
                        except ValueError:
                            continue
