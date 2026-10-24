from unittest.mock import AsyncMock

import pytest

from github_bot.domain.entities.download_job import DownloadJob, JobStatus
from github_bot.infrastructure.legacy_worker_payload import to_legacy_worker_payload
from github_bot.workers.legacy_worker_gateway import LegacyWorkerJobGateway


@pytest.mark.asyncio
async def test_gateway_claims_from_repository_and_returns_legacy_payload():
    job = DownloadJob(
        id=21,
        user_id=7,
        chat_id=8,
        source_url="https://example.test/repo.zip",
        status=JobStatus.RUNNING,
        queue_message_id=101,
        queue_chat_id=8,
    )
    repository = AsyncMock()
    repository.claim_next.return_value = job
    gateway = LegacyWorkerJobGateway(repository)

    payload = await gateway.claim_next_payload()

    assert payload == to_legacy_worker_payload(job)
    assert payload["repo_url"] == "https://example.test/repo.zip"
    assert payload["queue_message_id"] == 101
    repository.claim_next.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_gateway_returns_none_when_repository_queue_is_empty():
    repository = AsyncMock()
    repository.claim_next.return_value = None
    gateway = LegacyWorkerJobGateway(repository)

    assert await gateway.claim_next_payload() is None
    repository.claim_next.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_gateway_uses_running_compare_and_set_for_terminal_states():
    repository = AsyncMock()
    repository.set_status.side_effect = [True, True]
    gateway = LegacyWorkerJobGateway(repository)

    assert await gateway.mark_completed(21)
    assert await gateway.mark_failed(22, "network error")

    assert repository.set_status.await_args_list[0].args == (
        21,
        JobStatus.COMPLETED,
    )
    assert repository.set_status.await_args_list[0].kwargs == {
        "expected_status": JobStatus.RUNNING,
    }
    assert repository.set_status.await_args_list[1].args == (
        22,
        JobStatus.FAILED,
    )
    assert repository.set_status.await_args_list[1].kwargs == {
        "expected_status": JobStatus.RUNNING,
        "error": "network error",
    }
