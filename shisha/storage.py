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
        self.directory = directory
        path = directory / "history.sqlite3"
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        os.chmod(path, 0o600)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS processed (id INTEGER PRIMARY KEY, text TEXT NOT NULL)"
        )
        if "image_hash" not in {
            row["name"] for row in self.db.execute("PRAGMA table_info(processed)")
        }:
            self.db.execute(
                "ALTER TABLE processed ADD COLUMN image_hash TEXT NOT NULL DEFAULT ''"
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
            CREATE TABLE IF NOT EXISTS message_images (
                group_id INTEGER NOT NULL, message_id INTEGER NOT NULL, position INTEGER NOT NULL,
                start INTEGER NOT NULL, end INTEGER NOT NULL, file TEXT NOT NULL, url TEXT NOT NULL,
                cached_name TEXT NOT NULL DEFAULT '', media_type TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '', PRIMARY KEY(group_id, message_id, position)
            );
            CREATE TABLE IF NOT EXISTS ai_request_images (
                request_id INTEGER NOT NULL REFERENCES ai_requests(id), marker TEXT NOT NULL,
                group_id INTEGER NOT NULL, message_id INTEGER NOT NULL, position INTEGER NOT NULL,
                PRIMARY KEY(request_id, marker)
            );
            CREATE INDEX IF NOT EXISTS received_group_id ON received_messages(group_id, id);
            CREATE INDEX IF NOT EXISTS ai_group_id ON ai_requests(group_id, id);
            CREATE INDEX IF NOT EXISTS ai_message_lookup ON ai_request_messages(group_id, message_id);
        """)
        self.db.commit()

    def similarity(self, text: str, pending: list[str], image_hash: str = "") -> float:
        current = tokens(text)
        best = 0.0
        stored = (
            row[0]
            for row in self.db.execute(
                "SELECT text FROM processed WHERE image_hash = ? ORDER BY id DESC LIMIT 12",
                (image_hash,),
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

    def remember(self, text: str, image_hash: str = "") -> None:
        self.db.execute(
            "INSERT INTO processed (text, image_hash) VALUES (?, ?)", (text, image_hash)
        )
        self.db.execute(
            "DELETE FROM processed WHERE id NOT IN (SELECT id FROM processed ORDER BY id DESC LIMIT 12)"
        )
        self.db.commit()

    def message_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM received_messages").fetchone()[0]

    def save_summary(self, message_id: int, text: str) -> None:
        self.db.execute(
            "INSERT INTO summaries (message_id, text) VALUES (?, ?)", (message_id, text)
        )
        self.db.commit()

    def save_message(
        self, message: GroupMessage, include_existing_images: bool = False
    ) -> bool:
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
        if cursor.rowcount == 0 and include_existing_images and message.images:
            existing = self.db.execute(
                "SELECT 1 FROM message_images WHERE group_id = ? AND message_id = ? LIMIT 1",
                (message.group_id, message.message_id),
            ).fetchone()
            if existing is None:
                self.db.execute(
                    "UPDATE received_messages SET text = ? WHERE group_id = ? AND message_id = ?",
                    (message.text, message.group_id, message.message_id),
                )
        if cursor.rowcount == 1 or include_existing_images:
            self.db.executemany(
                """INSERT OR IGNORE INTO message_images
                   (group_id, message_id, position, start, end, file, url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        message.group_id,
                        message.message_id,
                        position,
                        image.start,
                        image.end,
                        image.file,
                        image.url,
                    )
                    for position, image in enumerate(message.images)
                ],
            )
        self.db.commit()
        return cursor.rowcount == 1

    def get_image(self, group_id: int, message_id: int, position: int) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM message_images WHERE group_id = ? AND message_id = ? AND position = ?",
            (group_id, message_id, position),
        ).fetchone()
        return dict(row) if row else None

    def update_image(
        self,
        group_id: int,
        message_id: int,
        position: int,
        cached_name: str,
        media_type: str,
        error: str,
    ) -> None:
        self.db.execute(
            """UPDATE message_images SET cached_name = ?, media_type = ?, error = ?
               WHERE group_id = ? AND message_id = ? AND position = ?""",
            (cached_name, media_type, error, group_id, message_id, position),
        )
        self.db.commit()

    def update_image_url(
        self, group_id: int, message_id: int, position: int, url: str
    ) -> None:
        self.db.execute(
            "UPDATE message_images SET url = ? WHERE group_id = ? AND message_id = ? AND position = ?",
            (url, group_id, message_id, position),
        )
        self.db.commit()

    def start_ai(
        self,
        trigger: GroupMessage,
        text: str,
        messages: list[GroupMessage],
        images: list[tuple[str, int, int, int]] | None = None,
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
        self.db.executemany(
            "INSERT INTO ai_request_images(request_id, marker, group_id, message_id, position) VALUES (?, ?, ?, ?, ?)",
            [(request_id, *image) for image in (images or [])],
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

    def conversation_groups(self, groups: list[str]) -> list[dict]:
        result = []
        for group_id in groups:
            latest = self.db.execute(
                """SELECT id, text, event_time FROM received_messages
                   WHERE group_id = ? ORDER BY id DESC LIMIT 1""",
                (group_id,),
            ).fetchone()
            named = self.db.execute(
                """SELECT group_name FROM received_messages
                   WHERE group_id = ? AND group_name != '' ORDER BY id DESC LIMIT 1""",
                (group_id,),
            ).fetchone()
            result.append(
                {
                    "id": group_id,
                    "name": named["group_name"] if named else "",
                    "latest": dict(latest) if latest else None,
                }
            )
        result.sort(
            key=lambda item: item["latest"]["id"] if item["latest"] else 0, reverse=True
        )
        return result

    def conversation(
        self,
        group_id: str,
        before: int | None = None,
        after: int | None = None,
        range_start: int | None = None,
        limit: int = 80,
    ) -> dict:
        if after is not None:
            rows = self.db.execute(
                """SELECT * FROM received_messages WHERE group_id = ? AND id > ?
                   ORDER BY id ASC LIMIT ?""",
                (group_id, after, limit + 1),
            ).fetchall()
            items = rows[:limit]
            next_after = items[-1]["id"] if len(rows) > limit else None
            next_before = None
            first = range_start or (items[0]["id"] if items else after)
            last = items[-1]["id"] if items else after
        else:
            rows = self.db.execute(
                """SELECT * FROM received_messages WHERE group_id = ? AND id < ?
                   ORDER BY id DESC LIMIT ?""",
                (group_id, before or 9223372036854775807, limit + 1),
            ).fetchall()
            items = list(reversed(rows[:limit]))
            next_before = items[0]["id"] if len(rows) > limit else None
            next_after = None
            first = items[0]["id"] if items else 0
            last = items[-1]["id"] if items else 0

        requests = self.db.execute(
            """SELECT a.*, MIN(m.id) AS first_message_row,
                      MAX(m.id) AS last_message_row, GROUP_CONCAT(m.id) AS message_rows
               FROM ai_requests a
               JOIN ai_request_messages am ON am.request_id = a.id
               JOIN received_messages m ON m.group_id = am.group_id AND m.message_id = am.message_id
               WHERE a.group_id = ?
               GROUP BY a.id
               HAVING first_message_row <= ? AND last_message_row >= ?
               ORDER BY first_message_row, a.id""",
            (group_id, last, first),
        ).fetchall()
        batches = []
        for row in requests:
            batch = dict(row)
            batch["message_rows"] = [
                int(value) for value in batch["message_rows"].split(",")
            ]
            batch["images"] = [
                {
                    "marker": image["marker"],
                    "url": image_url(
                        image["group_id"], image["message_id"], image["position"]
                    ),
                }
                for image in self.db.execute(
                    "SELECT * FROM ai_request_images WHERE request_id = ? ORDER BY rowid",
                    (batch["id"],),
                )
            ]
            batches.append(batch)

        unanchored = self.db.execute(
            """SELECT a.* FROM ai_requests a WHERE a.group_id = ?
               AND NOT EXISTS (
                   SELECT 1 FROM ai_request_messages am
                   JOIN received_messages m ON m.group_id = am.group_id AND m.message_id = am.message_id
                   WHERE am.request_id = a.id
               ) ORDER BY a.id""",
            (group_id,),
        ).fetchall()
        return {
            "items": [self.conversation_message(row) for row in items],
            "requests": batches,
            "unanchored": [dict(row) for row in unanchored],
            "next_before": next_before,
            "next_after": next_after,
        }

    def conversation_message(self, row: sqlite3.Row) -> dict:
        message = dict(row)
        images = self.db.execute(
            """SELECT * FROM message_images WHERE group_id = ? AND message_id = ?
               ORDER BY position""",
            (message["group_id"], message["message_id"]),
        ).fetchall()
        if images:
            parts, offset = [], 0
            for image in images:
                if image["start"] > offset:
                    parts.append(
                        {
                            "type": "text",
                            "text": message["text"][offset : image["start"]],
                        }
                    )
                parts.append(
                    {
                        "type": "image",
                        "url": image_url(
                            message["group_id"],
                            message["message_id"],
                            image["position"],
                        ),
                    }
                )
                offset = image["end"]
            if offset < len(message["text"]):
                parts.append({"type": "text", "text": message["text"][offset:]})
            message["parts"] = parts
        return message

    def close(self) -> None:
        self.db.close()


def image_url(group_id: int, message_id: int, position: int) -> str:
    return f"/api/message-images/{group_id}/{message_id}/{position}"
