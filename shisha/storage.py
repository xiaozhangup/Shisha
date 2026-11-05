from __future__ import annotations

import os
import re
import sqlite3
import time
from itertools import chain
from pathlib import Path

from .models import GroupMessage


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
        self.db.row_factory = sqlite3.Row
        os.chmod(path, 0o600)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS processed (id INTEGER PRIMARY KEY, text TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS summaries (id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS received_messages (
                id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL, group_name TEXT NOT NULL,
                message_id INTEGER NOT NULL, user_id INTEGER NOT NULL, sender_name TEXT NOT NULL,
                text TEXT NOT NULL, event_time INTEGER NOT NULL,
                UNIQUE(group_id, message_id)
            );
            CREATE TABLE IF NOT EXISTS ai_requests (
                id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL, group_name TEXT NOT NULL,
                message_id INTEGER NOT NULL, text TEXT NOT NULL, created_at INTEGER NOT NULL,
                status TEXT NOT NULL, result TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS ai_request_messages (
                request_id INTEGER NOT NULL REFERENCES ai_requests(id),
                group_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                PRIMARY KEY(request_id, group_id, message_id)
            );
            CREATE INDEX IF NOT EXISTS received_group_id ON received_messages(group_id, id);
            CREATE INDEX IF NOT EXISTS ai_message_lookup ON ai_request_messages(group_id, message_id);
        """)
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

    def save_message(self, message: GroupMessage) -> bool:
        cursor = self.db.execute(
            """INSERT OR IGNORE INTO received_messages
               (group_id, group_name, message_id, user_id, sender_name, text, event_time)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                message.group_id,
                message.group_name,
                message.message_id,
                message.user_id,
                message.sender_name,
                message.text,
                message.event_time,
            ),
        )
        self.db.commit()
        return cursor.rowcount == 1

    def start_ai(
        self, trigger: GroupMessage, text: str, messages: list[GroupMessage]
    ) -> int:
        cursor = self.db.execute(
            """INSERT INTO ai_requests(group_id, group_name, message_id, text, created_at, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (
                trigger.group_id,
                trigger.group_name,
                trigger.message_id,
                text,
                int(time.time()),
            ),
        )
        request_id = cursor.lastrowid
        self.db.executemany(
            "INSERT OR IGNORE INTO ai_request_messages(request_id, group_id, message_id) VALUES (?, ?, ?)",
            [(request_id, item.group_id, item.message_id) for item in messages],
        )
        self.db.commit()
        return request_id

    def finish_ai(self, request_id: int, status: str, result: str = "") -> None:
        self.db.execute(
            "UPDATE ai_requests SET status = ?, result = ? WHERE id = ?",
            (status, result, request_id),
        )
        self.db.commit()

    def list_messages(
        self, groups: list[str], before: int | None, limit: int = 50
    ) -> dict:
        if not groups:
            return {"items": [], "next_before": None}
        placeholders = ",".join("?" for _ in groups)
        rows = self.db.execute(
            f"""SELECT m.*, EXISTS(SELECT 1 FROM ai_request_messages a
                    WHERE a.group_id = m.group_id AND a.message_id = m.message_id) AS sent_to_ai
                FROM received_messages m WHERE m.group_id IN ({placeholders}) AND m.id < ?
                ORDER BY m.id DESC LIMIT ?""",
            (*groups, before or 9223372036854775807, limit + 1),
        ).fetchall()
        return {
            "items": [dict(row) for row in rows[:limit]],
            "next_before": rows[limit - 1]["id"] if len(rows) > limit else None,
        }

    def list_ai(self, before: int | None, limit: int = 50) -> dict:
        rows = self.db.execute(
            "SELECT * FROM ai_requests WHERE id < ? ORDER BY id DESC LIMIT ?",
            (before or 9223372036854775807, limit + 1),
        ).fetchall()
        return {
            "items": [dict(row) for row in rows[:limit]],
            "next_before": rows[limit - 1]["id"] if len(rows) > limit else None,
        }

    def close(self) -> None:
        self.db.close()
