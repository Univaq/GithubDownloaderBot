import aiosqlite
import pytest

from github_bot.domain.entities.download_job import JobStatus
from github_bot.infrastructure.database.sqlite_job_repository import SQLiteJobRepository


@pytest.mark.asyncio
async def test_repository_maps_existing_jobs_schema_and_transitions(tmp_path):
    db_path = tmp_path / "jobs.db"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """CREATE TABLE jobs (
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
            )"""
        )
        await db.execute(
            "INSERT INTO jobs (user_id, chat_id, repo_url, file_name, queue_message_id, queue_chat_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (42, 99, "https://github.com/example/project/archive/main.zip", "project.zip", 1234, 5678),
        )
        await db.commit()

    repository = SQLiteJobRepository(db_path)
    job = await repository.get_by_id(1)
    assert job is not None
    assert job.user_id == 42
    assert job.source_url.endswith("main.zip")
    assert job.status is JobStatus.QUEUED
    assert job.queue_message_id == 1234
    assert job.queue_chat_id == 5678
    assert await repository.count_queued() == 1

    claimed = await repository.claim_next()
    assert claimed is not None
    assert claimed.status is JobStatus.RUNNING
    assert claimed.queue_message_id == 1234
    assert claimed.queue_chat_id == 5678
    assert await repository.count_queued() == 0
    assert await repository.set_status(
        1, JobStatus.COMPLETED, expected_status=JobStatus.RUNNING
    )
    assert not await repository.set_status(
        1, JobStatus.FAILED, expected_status=JobStatus.RUNNING
    )
    finished = await repository.get_by_id(1)
    assert finished is not None
    assert finished.status is JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_claim_next_returns_none_for_empty_queue(tmp_path):
    db_path = tmp_path / "jobs.db"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """CREATE TABLE jobs (
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
            )"""
        )
        await db.commit()
    repository = SQLiteJobRepository(db_path)
    assert await repository.claim_next() is None
