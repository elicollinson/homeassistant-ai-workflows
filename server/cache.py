from __future__ import annotations

import json
import time

import aiosqlite

from server import config

TTL_SECONDS = 86400  # 24 hours

_db: aiosqlite.Connection | None = None


async def init() -> None:
    global _db
    db_path = f"{config.CACHE_DIR}/cache.db"
    _db = await aiosqlite.connect(db_path)
    await _db.execute(
        """CREATE TABLE IF NOT EXISTS content_cache (
            tmdb_id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            created_at REAL NOT NULL
        )"""
    )
    await _db.commit()


async def get(tmdb_id: int) -> dict | None:
    if _db is None:
        return None
    cursor = await _db.execute(
        "SELECT data, created_at FROM content_cache WHERE tmdb_id = ?", (tmdb_id,)
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    data, created_at = row
    if time.time() - created_at > TTL_SECONDS:
        await _db.execute("DELETE FROM content_cache WHERE tmdb_id = ?", (tmdb_id,))
        await _db.commit()
        return None
    return json.loads(data)


async def store(tmdb_id: int, data: dict) -> None:
    if _db is None:
        return
    await _db.execute(
        "INSERT OR REPLACE INTO content_cache (tmdb_id, data, created_at) VALUES (?, ?, ?)",
        (tmdb_id, json.dumps(data), time.time()),
    )
    await _db.commit()


async def close() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
