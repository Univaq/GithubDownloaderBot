import aiosqlite
import pytest

from github_bot.domain.entities.download_job import JobStatus
from github_bot.infrastructure.database.sqlite_job_repository import SQLiteJobRepository
from github_bot.workers.legacy_worker_gateway import LegacyWorkerJobGateway


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
        await db.executemany(
            """INSERT INTO jobs
               (user_id, chat_id, repo_url, queue_message_id, queue_chat_id)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (10, 20, "https://github.com/example/one/archive/main.zip", 101, 20),
                (11, 21, "https://github.com/example/two/archive/main.zip", 102, 21),
            ],
        )
        await db.commit()


@pytest.mark.asyncio
async def test_sqlite_gateway_claims_and_completes_job(tmp_path):
    database_path = tmp_path / "jobs.db"
    await _create_jobs_table(database_path)
    repository = SQLiteJobRepository(database_path)
    gateway = LegacyWorkerJobGateway(repository)

    payload = await gateway.claim_next_payload()

    assert payload is not None
    assert payload["id"] == 1
    assert payload["repo_url"] == "https://github.com/example/one/archive/main.zip"
    assert payload["status"] == JobStatus.RUNNING.value
    assert payload["queue_message_id"] == 101
    assert payload["queue_chat_id"] == 20

    claimed = await repository.get_by_id(1)
    assert claimed is not None
    assert claimed.status is JobStatus.RUNNING

    assert await gateway.mark_completed(1) is True
    completed = await repository.get_by_id(1)
    assert completed is not None
    assert completed.status is JobStatus.COMPLETED
    assert completed.error is None

    # A terminal job cannot be completed a second time by a stale worker.
    assert await gateway.mark_completed(1) is False
    assert await gateway.mark_failed(1, "late failure") is False
    unchanged = await repository.get_by_id(1)
    assert unchanged is not None
    assert unchanged.status is JobStatus.COMPLETED
    assert unchanged.error is None


@pytest.mark.asyncio
async def test_sqlite_gateway_claims_and_fails_job(tmp_path):
    database_path = tmp_path / "jobs.db"
    await _create_jobs_table(database_path)
    repository = SQLiteJobRepository(database_path)
    gateway = LegacyWorkerJobGateway(repository)

    # Claim and complete the first job so the next claim selects the second.
    first_payload = await gateway.claim_next_payload()
    assert first_payload is not None
    assert first_payload["id"] == 1
    assert await gateway.mark_completed(1) is True

    payload = await gateway.claim_next_payload()
    assert payload is not None
    assert payload["id"] == 2
    assert payload["status"] == JobStatus.RUNNING.value

    assert await gateway.mark_failed(2, "network error") is True
    failed = await repository.get_by_id(2)
    assert failed is not None
    assert failed.status is JobStatus.FAILED
    assert failed.error == "network error"

    # Failed is terminal too; stale completion must not overwrite it.
    assert await gateway.mark_completed(2) is False
    unchanged = await repository.get_by_id(2)
    assert unchanged is not None
    assert unchanged.status is JobStatus.FAILED
    assert unchanged.error == "network error"


@pytest.mark.asyncio
async def test_sqlite_gateway_returns_none_after_all_jobs_are_claimed(tmp_path):
    database_path = tmp_path / "jobs.db"
    await _create_jobs_table(database_path)
    repository = SQLiteJobRepository(database_path)
    gateway = LegacyWorkerJobGateway(repository)

    first = await gateway.claim_next_payload()
    second = await gateway.claim_next_payload()

    assert first is not None and first["id"] == 1
    assert second is not None and second["id"] == 2
    assert await gateway.claim_next_payload() is None
