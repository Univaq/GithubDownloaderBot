from github_bot.domain.entities.download_job import DownloadJob, JobStatus
from github_bot.infrastructure.legacy_worker_payload import to_legacy_worker_payload


def test_domain_job_maps_to_all_legacy_worker_fields():
    job = DownloadJob(
        id=7,
        user_id=41,
        chat_id=99,
        source_url="https://github.com/example/repo/archive/main.zip",
        job_type="release",
        file_name="release.zip",
        status=JobStatus.RUNNING,
        error=None,
        queue_message_id=501,
        queue_chat_id=99,
    )

    assert to_legacy_worker_payload(job) == {
        "id": 7,
        "user_id": 41,
        "chat_id": 99,
        "repo_url": "https://github.com/example/repo/archive/main.zip",
        "job_type": "release",
        "file_name": "release.zip",
        "status": "running",
        "error": None,
        "queue_message_id": 501,
        "queue_chat_id": 99,
    }


def test_domain_job_maps_missing_queue_message_as_none():
    job = DownloadJob(
        id=8,
        user_id=42,
        chat_id=100,
        source_url="https://github.com/example/repo/archive/main.zip",
    )

    payload = to_legacy_worker_payload(job)

    assert payload["queue_message_id"] is None
    assert payload["queue_chat_id"] is None
    assert payload["repo_url"] == job.source_url
