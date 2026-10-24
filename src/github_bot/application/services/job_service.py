"""Use cases for queue operations, independent of Telegram and SQLite."""

from github_bot.application.ports.job_repository import JobRepository
from github_bot.domain.entities.download_job import DownloadJob, JobStatus
from github_bot.domain.exceptions import InvalidJobStateError, JobNotFoundError, QueueFullError


class JobService:
    def __init__(self, repository: JobRepository, max_queue_size: int) -> None:
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be positive")
        self._repository = repository
        self._max_queue_size = max_queue_size

    async def get_job(self, job_id: int) -> DownloadJob:
        job = await self._repository.get_by_id(job_id)
        if job is None:
            raise JobNotFoundError(f"Job {job_id} was not found")
        return job

    async def ensure_queue_has_capacity(self) -> None:
        if await self._repository.count_queued() >= self._max_queue_size:
            raise QueueFullError("The download queue is full")

    async def transition(self, job_id: int, status: JobStatus, *, error: str | None = None) -> None:
        job = await self.get_job(job_id)
        allowed = {
            JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED},
            JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
            JobStatus.COMPLETED: set(),
            JobStatus.FAILED: set(),
            JobStatus.CANCELLED: set(),
        }
        if status not in allowed[job.status]:
            raise InvalidJobStateError(f"Cannot change job from {job.status} to {status}")
        updated = await self._repository.set_status(
            job_id,
            status,
            expected_status=job.status,
            error=error,
        )
        if not updated:
            raise InvalidJobStateError("Job status changed concurrently; reload and retry")
