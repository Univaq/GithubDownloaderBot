"""SQLite implementation of the application job repository port.

This adapter targets the existing jobs table. It does not create or migrate the
schema; the existing bootstrap remains the schema owner until the migration step.
"""

from datetime import datetime
from pathlib import Path

from github_bot.application.ports.job_repository import JobRepository
from github_bot.domain.entities.download_job import DownloadJob, JobStatus
from github_bot.infrastructure.database.connection import SQLiteConnectionFactory


class SQLiteJobRepository(JobRepository):
    def __init__(self, database_path: Path) -> None:
        self._connections = SQLiteConnectionFactory(database_path)

    @staticmethod
    def _map_row(row) -> DownloadJob:
        created_at = None
        raw_created_at = row["created_at"]
        if raw_created_at:
            try:
                created_at = datetime.fromisoformat(raw_created_at)
            except (TypeError, ValueError):
                created_at = None
        return DownloadJob(
            id=row["id"],
            user_id=row["user_id"],
            chat_id=row["chat_id"],
            source_url=row["repo_url"],
            job_type=row["job_type"] or "source",
            file_name=row["file_name"],
            status=JobStatus(row["status"]),
            created_at=created_at,
            error=row["error"],
        )

    async def get_by_id(self, job_id: int) -> DownloadJob | None:
        async with self._connections.connect() as db:
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            return self._map_row(row) if row is not None else None

    async def claim_next(self) -> DownloadJob | None:
        async with self._connections.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
            )
            row = await cursor.fetchone()
            if row is None:
                await db.commit()
                return None
            cursor = await db.execute(
                "UPDATE jobs SET status = 'running', updated_at = CURRENT_TIMESTAMP, "
                "error = NULL WHERE id = ? AND status = 'queued'",
                (row["id"],),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return None
            await db.commit()
            values = dict(row)
            values["status"] = JobStatus.RUNNING.value
            return self._map_row(values)

    async def set_status(
        self,
        job_id: int,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> bool:
        async with self._connections.connect() as db:
            cursor = await db.execute(
                "UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP, error = ? "
                "WHERE id = ?",
                (status.value, error[:500] if error else None, job_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def count_queued(self) -> int:
        async with self._connections.connect() as db:
            cursor = await db.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued'")
            row = await cursor.fetchone()
            return int(row[0]) if row else 0
