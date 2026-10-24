import pytest

from github_bot.application.services.job_service import JobService
from github_bot.domain.entities.download_job import DownloadJob, JobStatus
from github_bot.domain.exceptions import InvalidJobStateError, JobNotFoundError, QueueFullError


class FakeJobRepository:
    def __init__(self, job=None, queued=0):
        self.job = job
        self.queued = queued
        self.updated = None

    async def get_by_id(self, job_id):
        return self.job if self.job and self.job.id == job_id else None

    async def claim_next(self):
        return None

    async def set_status(self, job_id, status, *, expected_status, error=None):
        if self.job is None or self.job.status is not expected_status:
            return False
        self.updated = (job_id, status, expected_status, error)
        self.job = DownloadJob(
            id=self.job.id,
            user_id=self.job.user_id,
            chat_id=self.job.chat_id,
            source_url=self.job.source_url,
            job_type=self.job.job_type,
            file_name=self.job.file_name,
            status=status,
            created_at=self.job.created_at,
            error=error,
        )
        return True

    async def count_queued(self):
        return self.queued


def make_job(status=JobStatus.QUEUED):
    return DownloadJob(1, 10, 20, "https://github.com/example/repo/archive/main.zip", status=status)


@pytest.mark.asyncio
async def test_queue_capacity_rejects_full_queue():
    service = JobService(FakeJobRepository(queued=3), max_queue_size=3)
    with pytest.raises(QueueFullError):
        await service.ensure_queue_has_capacity()


@pytest.mark.asyncio
async def test_missing_job_raises_domain_error():
    service = JobService(FakeJobRepository(), max_queue_size=3)
    with pytest.raises(JobNotFoundError):
        await service.get_job(404)


@pytest.mark.asyncio
async def test_invalid_terminal_transition_is_rejected():
    service = JobService(FakeJobRepository(make_job(JobStatus.COMPLETED)), max_queue_size=3)
    with pytest.raises(InvalidJobStateError):
        await service.transition(1, JobStatus.CANCELLED)

class RacingJobRepository(FakeJobRepository):
    async def get_by_id(self, job_id):
        snapshot = await super().get_by_id(job_id)
        if snapshot is not None:
            self.job = make_job(JobStatus.RUNNING)
        return snapshot


@pytest.mark.asyncio
async def test_concurrent_state_change_is_not_overwritten():
    repository = RacingJobRepository(make_job(JobStatus.QUEUED))
    service = JobService(repository, max_queue_size=3)

    with pytest.raises(InvalidJobStateError, match="concurrently"):
        await service.transition(1, JobStatus.RUNNING)

    assert repository.job.status is JobStatus.RUNNING
    assert repository.updated is None

