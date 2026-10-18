"""Compatibility mapping for the existing Telegram download worker.

Keep this boundary explicit while the worker still consumes dictionary-shaped
legacy jobs. The worker can be migrated independently after this mapping is
covered by integration tests.
"""

from github_bot.domain.entities.download_job import DownloadJob


def to_legacy_worker_payload(job: DownloadJob) -> dict[str, object]:
    """Convert a domain job into the keys consumed by process_download_job."""
    return {
        "id": job.id,
        "user_id": job.user_id,
        "chat_id": job.chat_id,
        "repo_url": job.source_url,
        "job_type": job.job_type,
        "file_name": job.file_name,
        "status": job.status.value,
        "error": job.error,
        "queue_message_id": job.queue_message_id,
        "queue_chat_id": job.queue_chat_id,
    }
