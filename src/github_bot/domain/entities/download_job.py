"""Download job entity and lifecycle rules."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class DownloadJob:
    id: int
    user_id: int
    chat_id: int
    source_url: str
    job_type: str = "source"
    file_name: str | None = None
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime | None = None
    error: str | None = None

    def can_start(self) -> bool:
        return self.status is JobStatus.QUEUED

    def can_cancel(self) -> bool:
        return self.status in {JobStatus.QUEUED, JobStatus.RUNNING}
