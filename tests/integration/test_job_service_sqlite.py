import aiosqlite
import pytest

from github_bot.application.services.job_service import JobService
from github_bot.domain.entities.download_job import JobStatus
from github_bot.domain.exceptions import InvalidJobStateError, QueueFullError
from github_bot.infrastructure.database.sqlite_job_repository import SQLiteJobRepository


async def _create_jobs_table(database_path):
    async with aiosqlite.connect(database_path) as db:
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
            "INSERT INTO jobs (user_id, chat_id, repo_url) VALUES (?, ?, ?)",
            (10, 20, "https://github.com/example/one/archive/main.zip"),
        )
        await db.execute(
            "INSERT INTO jobs (user_id, chat_id, repo_url) VALUES (?, ?, ?)",
            (11, 21, "https://github.com/example/two/archive/main.zip"),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_job_service_enforces_lifecycle_against_sqlite(tmp_path):
    database_path = tmp_path / "jobs.db"
    await _create_jobs_table(database_path)
    repository = SQLiteJobRepository(database_path)
    service = JobService(repository, max_queue_size=2)

    await service.transition(1, JobStatus.RUNNING)
    await service.transition(1, JobStatus.COMPLETED)

    job = await service.get_job(1)
    assert job.status is JobStatus.COMPLETED

    with pytest.raises(InvalidJobStateError):
        await service.transition(1, JobStatus.FAILED)


@pytest.mark.asyncio
async def test_job_service_detects_stale_state_before_transition(tmp_path):
    database_path = tmp_path / "jobs.db"
    await _create_jobs_table(database_path)
    repository = SQLiteJobRepository(database_path)
    service = JobService(repository, max_queue_size=2)

    # Simulate another worker claiming the job after the service read its state.
    assert await repository.set_status(
        1, JobStatus.RUNNING, expected_status=JobStatus.QUEUED
    )
    with pytest.raises(InvalidJobStateError, match="changed concurrently"):
        await service.transition(1, JobStatus.RUNNING)


@pytest.mark.asyncio
async def test_job_service_queue_capacity_uses_repository_count(tmp_path):
    database_path = tmp_path / "jobs.db"
    await _create_jobs_table(database_path)
    repository = SQLiteJobRepository(database_path)
    service = JobService(repository, max_queue_size=2)

    await service.ensure_queue_has_capacity()

    # The configured capacity is reached once the two queued jobs are counted.
    with pytest.raises(QueueFullError):
        await JobService(repository, max_queue_size=1).ensure_queue_has_capacity()
