from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    source TEXT,
    published_at TEXT,
    summary TEXT,
    tags TEXT,
    importance INTEGER DEFAULT 0,
    source_score INTEGER DEFAULT 0,
    relevance_score INTEGER DEFAULT 0,
    final_score INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    processed INTEGER DEFAULT 0
);
"""

MIGRATIONS = {
    "source_score": "ALTER TABLE news ADD COLUMN source_score INTEGER DEFAULT 0",
    "relevance_score": "ALTER TABLE news ADD COLUMN relevance_score INTEGER DEFAULT 0",
    "final_score": "ALTER TABLE news ADD COLUMN final_score INTEGER DEFAULT 0",
}


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path) -> None:
    with get_connection(db_path) as conn:
        conn.execute(SCHEMA)
        migrate_db(conn)
        conn.commit()


def migrate_db(conn: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(news)").fetchall()
    }
    for column, sql in MIGRATIONS.items():
        if column in existing_columns:
            continue
        try:
            conn.execute(sql)
            print(f"[db] колонка қосылды: {column}")
        except sqlite3.OperationalError as exc:
            print(f"[db] migration өткізіліп кетті ({column}): {exc}")


def get_existing_titles(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT title FROM news").fetchall()
    return [row["title"] for row in rows if row["title"]]


def insert_news(conn: sqlite3.Connection, items: Iterable[dict]) -> int:
    inserted = 0
    sql = """
    INSERT OR IGNORE INTO news
        (title, url, source, published_at, summary, tags, importance, source_score, relevance_score, final_score)
    VALUES
        (:title, :url, :source, :published_at, :summary, :tags, :importance, :source_score, :relevance_score, :final_score)
    """
    for item in items:
        tags = item.get("tags", [])
        row = {
            "title": item.get("title", "").strip(),
            "url": item.get("url", "").strip(),
            "source": item.get("source", ""),
            "published_at": item.get("published_at", ""),
            "summary": item.get("summary", ""),
            "tags": json.dumps(tags, ensure_ascii=False),
            "importance": int(item.get("importance", 0)),
            "source_score": int(item.get("source_score", 0)),
            "relevance_score": int(item.get("relevance_score", 0)),
            "final_score": int(item.get("final_score", 0)),
        }
        if not row["title"] or not row["url"]:
            continue
        cur = conn.execute(sql, row)
        if cur.rowcount:
            inserted += 1
    conn.commit()
    return inserted


def fetch_recent_news(conn: sqlite3.Connection, limit: int = 500) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            id, title, url, source, published_at, summary, tags, importance,
            source_score, relevance_score, final_score, created_at
        FROM news
        ORDER BY final_score DESC, importance DESC, COALESCE(published_at, created_at) DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    try:
        data["tags"] = json.loads(data.get("tags") or "[]")
    except json.JSONDecodeError:
        data["tags"] = []
    return data
