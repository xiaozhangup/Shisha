from __future__ import annotations

import os
import re
import sqlite3
from itertools import chain
from pathlib import Path


def tokens(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        words.update(run[i : i + 2] for i in range(max(1, len(run) - 1)))
    return words


class History:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / "history.sqlite3"
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS processed (id INTEGER PRIMARY KEY, text TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS summaries (id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        self.db.commit()

    def similarity(self, text: str, pending: list[str]) -> float:
        current = tokens(text)
        best = 0.0
        stored = (
            row[0]
            for row in self.db.execute(
                "SELECT text FROM processed ORDER BY id DESC LIMIT 12"
            )
        )
        for previous in chain(pending, stored):
            if previous == text:
                return 1.0
            prior = tokens(previous)
            union = current | prior
            if union:
                best = max(best, len(current & prior) / len(union))
        return best

    def remember(self, text: str) -> None:
        self.db.execute("INSERT INTO processed (text) VALUES (?)", (text,))
        self.db.execute(
            "DELETE FROM processed WHERE id NOT IN (SELECT id FROM processed ORDER BY id DESC LIMIT 12)"
        )
        self.db.commit()

    def save_summary(self, message_id: int, text: str) -> None:
        self.db.execute(
            "INSERT INTO summaries (message_id, text) VALUES (?, ?)", (message_id, text)
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()
