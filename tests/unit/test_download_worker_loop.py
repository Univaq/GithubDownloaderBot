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
    finish_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(worker, "fail_job", fail_mock)
    monkeypatch.setattr(worker, "finish_job", finish_mock)

    await worker.worker_loop(bot, stop_event)

    fail_mock.assert_awaited_once_with(13, "download failed")
    bot.send_message.assert_awaited_once_with(
        chat_id=35,
        text="Download or upload failed. Please try again later.",
    )
    finish_mock.assert_not_awaited()



@pytest.mark.asyncio
async def test_worker_loop_stops_cleanly_when_idle(monkeypatch):
    stop_event = asyncio.Event()
    bot = AsyncMock()

    async def claim_nothing():
        stop_event.set()
        return None

    claim_mock = AsyncMock(side_effect=claim_nothing)
    monkeypatch.setattr(worker, "claim_next_job", claim_mock)
    process_mock = AsyncMock()
    monkeypatch.setattr(worker, "process_download_job", process_mock)

    await worker.worker_loop(bot, stop_event)

    claim_mock.assert_awaited_once_with()
    process_mock.assert_not_awaited()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_loop_survives_failure_to_persist_failed_status(monkeypatch):
    job = {"id": 14, "chat_id": 36, "repo_url": "https://example.test/error.zip"}
    stop_event = asyncio.Event()
    bot = AsyncMock()

    async def notify_and_stop(**kwargs):
        stop_event.set()

    bot.send_message.side_effect = notify_and_stop
    monkeypatch.setattr(worker, "claim_next_job", AsyncMock(return_value=job))
    monkeypatch.setattr(
        worker,
        "process_download_job",
        AsyncMock(side_effect=RuntimeError("network error")),
    )
    fail_mock = AsyncMock(side_effect=RuntimeError("database unavailable"))
    monkeypatch.setattr(worker, "fail_job", fail_mock)
    finish_mock = AsyncMock()
    monkeypatch.setattr(worker, "finish_job", finish_mock)

    await worker.worker_loop(bot, stop_event)

    fail_mock.assert_awaited_once_with(14, "network error")
    bot.send_message.assert_awaited_once_with(
        chat_id=36,
        text="Download or upload failed. Please try again later.",
    )
    finish_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_loop_does_not_retry_job_when_completion_status_is_not_saved(
    monkeypatch,
):
    job = {"id": 15, "chat_id": 37, "repo_url": "https://example.test/repo.zip"}
    stop_event = asyncio.Event()
    bot = AsyncMock()

    monkeypatch.setattr(worker, "claim_next_job", AsyncMock(return_value=job))
    process_mock = AsyncMock()
    monkeypatch.setattr(worker, "process_download_job", process_mock)

    async def finish_and_stop(job_id):
        assert job_id == 15
        stop_event.set()
        return False

    finish_mock = AsyncMock(side_effect=finish_and_stop)
    fail_mock = AsyncMock()
    monkeypatch.setattr(worker, "finish_job", finish_mock)
    monkeypatch.setattr(worker, "fail_job", fail_mock)

    await worker.worker_loop(bot, stop_event)

    process_mock.assert_awaited_once_with(bot, job)
    finish_mock.assert_awaited_once_with(15)
    fail_mock.assert_not_awaited()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_loop_does_not_retry_when_saving_completion_raises(monkeypatch):
    job = {"id": 16, "chat_id": 38, "repo_url": "https://example.test/repo.zip"}
    stop_event = asyncio.Event()
    bot = AsyncMock()

    monkeypatch.setattr(worker, "claim_next_job", AsyncMock(return_value=job))
    process_mock = AsyncMock()
    monkeypatch.setattr(worker, "process_download_job", process_mock)

    async def fail_to_save_completion(job_id):
        assert job_id == 16
        stop_event.set()
        raise RuntimeError("database unavailable")

    finish_mock = AsyncMock(side_effect=fail_to_save_completion)
    monkeypatch.setattr(worker, "finish_job", finish_mock)
    fail_mock = AsyncMock()
    monkeypatch.setattr(worker, "fail_job", fail_mock)

    await worker.worker_loop(bot, stop_event)

    process_mock.assert_awaited_once_with(bot, job)
    finish_mock.assert_awaited_once_with(16)
    fail_mock.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    worker.claim_next_job.assert_awaited_once_with()



@pytest.mark.asyncio
async def test_worker_loop_uses_injected_gateway_for_claim_and_completion(monkeypatch):
    job = {"id": 17, "chat_id": 39, "repo_url": "https://example.test/repo.zip"}
    stop_event = asyncio.Event()
    bot = AsyncMock()

    class Gateway:
        def __init__(self):
            self.claim_calls = 0
            self.completed = []

        async def claim_next_payload(self):
            self.claim_calls += 1
            return job

        async def mark_completed(self, job_id):
            self.completed.append(job_id)
            stop_event.set()
            return True

        async def mark_failed(self, job_id, error):
            raise AssertionError("failure transition must not be used")

    gateway = Gateway()
    process_mock = AsyncMock()
    monkeypatch.setattr(worker, "process_download_job", process_mock)
    legacy_claim = AsyncMock(side_effect=AssertionError("legacy claim used"))
    legacy_finish = AsyncMock(side_effect=AssertionError("legacy finish used"))
    monkeypatch.setattr(worker, "claim_next_job", legacy_claim)
    monkeypatch.setattr(worker, "finish_job", legacy_finish)

    await worker.worker_loop(bot, stop_event, job_gateway=gateway)

    process_mock.assert_awaited_once_with(bot, job)
    assert gateway.claim_calls == 1
    assert gateway.completed == [17]
    legacy_claim.assert_not_awaited()
    legacy_finish.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_loop_uses_injected_gateway_for_failure(monkeypatch):
    job = {"id": 18, "chat_id": 40, "repo_url": "https://example.test/broken.zip"}
    stop_event = asyncio.Event()
    bot = AsyncMock()

    class Gateway:
        async def claim_next_payload(self):
            return job

        async def mark_completed(self, job_id):
            raise AssertionError("completion transition must not be used")

        async def mark_failed(self, job_id, error):
            assert job_id == 18
            assert error == "gateway path failed"
            stop_event.set()
            return True

    monkeypatch.setattr(
        worker,
        "process_download_job",
        AsyncMock(side_effect=RuntimeError("gateway path failed")),
    )
    legacy_claim = AsyncMock(side_effect=AssertionError("legacy claim used"))
    legacy_fail = AsyncMock(side_effect=AssertionError("legacy failure used"))
    monkeypatch.setattr(worker, "claim_next_job", legacy_claim)
    monkeypatch.setattr(worker, "fail_job", legacy_fail)

    await worker.worker_loop(bot, stop_event, job_gateway=Gateway())

    legacy_claim.assert_not_awaited()
    legacy_fail.assert_not_awaited()
    bot.send_message.assert_awaited_once_with(
        chat_id=40,
        text="Download or upload failed. Please try again later.",
    )



@pytest.mark.asyncio
async def test_worker_loop_does_not_mark_injected_gateway_job_failed_when_completion_save_raises(
    monkeypatch,
):
    job = {"id": 19, "chat_id": 41, "repo_url": "https://example.test/repo.zip"}
    stop_event = asyncio.Event()
    bot = AsyncMock()

    class Gateway:
        async def claim_next_payload(self):
            return job

        async def mark_completed(self, job_id):
            assert job_id == 19
            stop_event.set()
            raise RuntimeError("completion store unavailable")

        async def mark_failed(self, job_id, error):
            raise AssertionError("must not convert completion-save failure to job failure")

    process_mock = AsyncMock()
    monkeypatch.setattr(worker, "process_download_job", process_mock)
    legacy_claim = AsyncMock(side_effect=AssertionError("legacy claim used"))
    legacy_finish = AsyncMock(side_effect=AssertionError("legacy finish used"))
    legacy_fail = AsyncMock(side_effect=AssertionError("legacy failure used"))
    monkeypatch.setattr(worker, "claim_next_job", legacy_claim)
    monkeypatch.setattr(worker, "finish_job", legacy_finish)
    monkeypatch.setattr(worker, "fail_job", legacy_fail)

    await worker.worker_loop(bot, stop_event, job_gateway=Gateway())

    process_mock.assert_awaited_once_with(bot, job)
    legacy_claim.assert_not_awaited()
    legacy_finish.assert_not_awaited()
    legacy_fail.assert_not_awaited()
    bot.send_message.assert_not_awaited()
