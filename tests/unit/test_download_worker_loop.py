import asyncio
from unittest.mock import AsyncMock

import pytest

import workers.download_worker as worker


@pytest.mark.asyncio
async def test_worker_loop_marks_successful_job_completed(monkeypatch):
    job = {"id": 12, "chat_id": 34, "repo_url": "https://example.test/repo.zip"}
    stop_event = asyncio.Event()
    bot = AsyncMock()

    monkeypatch.setattr(worker, "claim_next_job", AsyncMock(return_value=job))
    process = AsyncMock()
    monkeypatch.setattr(worker, "process_download_job", process)

    async def finish(job_id):
        assert job_id == 12
        stop_event.set()
        return True

    finish_mock = AsyncMock(side_effect=finish)
    monkeypatch.setattr(worker, "finish_job", finish_mock)

    await worker.worker_loop(bot, stop_event)

    process.assert_awaited_once_with(bot, job)
    finish_mock.assert_awaited_once_with(12)
    worker.claim_next_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_loop_marks_processing_failure_and_notifies_user(monkeypatch):
    job = {"id": 13, "chat_id": 35, "repo_url": "https://example.test/broken.zip"}
    stop_event = asyncio.Event()
    bot = AsyncMock()

    monkeypatch.setattr(worker, "claim_next_job", AsyncMock(return_value=job))
    monkeypatch.setattr(
        worker,
        "process_download_job",
        AsyncMock(side_effect=RuntimeError("download failed")),
    )

    async def fail(job_id, error):
        assert job_id == 13
        assert error == "download failed"
        stop_event.set()
        return True

    fail_mock = AsyncMock(side_effect=fail)
    monkeypatch.setattr(worker, "fail_job", fail_mock)

    await worker.worker_loop(bot, stop_event)

    fail_mock.assert_awaited_once_with(13, "download failed")
    bot.send_message.assert_awaited_once_with(
        chat_id=35,
        text="Download or upload failed. Please try again later.",
    )
    worker.finish_job.assert_not_called()
