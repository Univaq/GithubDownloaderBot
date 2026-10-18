"""Small SQLite connection factory used by infrastructure adapters."""

from pathlib import Path

import aiosqlite


class SQLiteConnectionFactory:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    async def connect(self) -> aiosqlite.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(self.database_path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        return db
