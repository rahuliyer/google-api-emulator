from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    profile_json TEXT NOT NULL
);

CREATE TABLE tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id)
);

CREATE TABLE people (
    resource_name TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    etag TEXT NOT NULL,
    person_json TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE gmail_mailboxes (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    history_id INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE gmail_labels (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    type TEXT NOT NULL,
    label_json TEXT NOT NULL,
    PRIMARY KEY (user_id, id)
);

CREATE TABLE gmail_messages (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    thread_id TEXT NOT NULL,
    label_ids TEXT NOT NULL,
    internal_date INTEGER NOT NULL,
    history_id INTEGER NOT NULL,
    raw TEXT NOT NULL,
    message_json TEXT NOT NULL,
    PRIMARY KEY (user_id, id)
);

CREATE TABLE gmail_drafts (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    message_id TEXT NOT NULL,
    PRIMARY KEY (user_id, id)
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.conn.close()

    def reset_schema(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                PRAGMA foreign_keys = OFF;
                DROP TABLE IF EXISTS gmail_drafts;
                DROP TABLE IF EXISTS gmail_messages;
                DROP TABLE IF EXISTS gmail_labels;
                DROP TABLE IF EXISTS gmail_mailboxes;
                DROP TABLE IF EXISTS people;
                DROP TABLE IF EXISTS tokens;
                DROP TABLE IF EXISTS users;
                PRAGMA foreign_keys = ON;
                """
            )
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    @contextmanager
    def locked(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self.conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, params).fetchall())
