import secrets

import aiosqlite

from config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    repo_url TEXT NOT NULL,
    job_type TEXT NOT NULL DEFAULT 'source',
    file_name TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    error TEXT,
    queue_message_id INTEGER,
    queue_chat_id INTEGER
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created
ON jobs(status, created_at);

CREATE INDEX IF NOT EXISTS idx_jobs_user_created
ON jobs(user_id, created_at);

CREATE TABLE IF NOT EXISTS selections (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    download_url TEXT NOT NULL,
    file_name TEXT NOT NULL,
    job_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    repo_full_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, repo_full_name)
);

CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    query TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_search_history_user_created
ON search_history(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_favorites_user_created
ON favorites(user_id, created_at);
"""


async def initialize_database() -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.executescript(SCHEMA)

        cursor = await db.execute("PRAGMA table_info(jobs)")
        columns = {row[1] for row in await cursor.fetchall()}

        migrations = {
            "job_type": (
                "ALTER TABLE jobs ADD COLUMN "
                "job_type TEXT NOT NULL DEFAULT 'source'"
            ),
            "file_name": (
                "ALTER TABLE jobs ADD COLUMN file_name TEXT"
            ),
            "updated_at": (
                "ALTER TABLE jobs ADD COLUMN "
                "updated_at TEXT NOT NULL DEFAULT ''"
            ),
            "error": (
                "ALTER TABLE jobs ADD COLUMN error TEXT"
            ),
            "queue_message_id": (
                "ALTER TABLE jobs ADD COLUMN queue_message_id INTEGER"
            ),
            "queue_chat_id": (
                "ALTER TABLE jobs ADD COLUMN queue_chat_id INTEGER"
            ),
        }

        for column, sql in migrations.items():
            if column not in columns:
                await db.execute(sql)

        await db.execute(
            """
            UPDATE jobs
            SET updated_at = CURRENT_TIMESTAMP
            WHERE updated_at = ''
            """
        )

        await db.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                updated_at = CURRENT_TIMESTAMP,
                error = 'Interrupted by process restart'
            WHERE status = 'running'
            """
        )

        await db.commit()
