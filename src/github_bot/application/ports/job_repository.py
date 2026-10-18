"""Persistence contract for download jobs."""

from typing import Protocol

from github_bot.domain.entities.download_job import DownloadJob, JobStatus


class JobRepository(Protocol):
    async def get_by_id(self, job_id: int) -> DownloadJob | None: ...

    async def claim_next(self) -> DownloadJob | None: ...

    async def set_status(
        self,
        job_id: int,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> bool: ...

    async def count_queued(self) -> int: ...
