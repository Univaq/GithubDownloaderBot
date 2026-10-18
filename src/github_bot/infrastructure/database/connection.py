"""Small SQLite connection factory used by infrastructure adapters."""

from contextlib import asynccontextmanager
from pathlib import Path
from collections.abc import AsyncIterator

import aiosqlite


class SQLiteConnectionFactory:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys = ON")
            yield db
