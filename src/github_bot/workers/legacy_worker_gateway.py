"""Bridge the domain repository to the legacy dictionary-based worker.

This adapter is intentionally not wired into the production worker loop yet.
It keeps claiming and terminal status updates on the same repository instance,
so the eventual cutover cannot accidentally mix persistence implementations.
"""

from github_bot.application.ports.job_repository import JobRepository
from github_bot.domain.entities.download_job import JobStatus
from github_bot.infrastructure.legacy_worker_payload import to_legacy_worker_payload


class LegacyWorkerJobGateway:
    """Expose repository operations using the legacy worker's payload contract."""

    def __init__(self, repository: JobRepository) -> None:
        self._repository = repository

    async def claim_next_payload(self) -> dict[str, object] | None:
        job = await self._repository.claim_next()
        if job is None:
            return None
        return to_legacy_worker_payload(job)

    async def mark_completed(self, job_id: int) -> bool:
        return await self._repository.set_status(
            job_id,
            JobStatus.COMPLETED,
            expected_status=JobStatus.RUNNING,
        )

    async def mark_failed(self, job_id: int, error: str) -> bool:
        return await self._repository.set_status(
            job_id,
            JobStatus.FAILED,
            expected_status=JobStatus.RUNNING,
            error=error,
        )
