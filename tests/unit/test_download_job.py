from github_bot.domain.entities.download_job import DownloadJob, JobStatus


def test_queued_job_can_start_and_cancel() -> None:
    job = DownloadJob(
        id=1,
        user_id=10,
        chat_id=20,
        source_url="https://github.com/example/project/archive/refs/heads/main.zip",
    )
    assert job.can_start()
    assert job.can_cancel()


def test_completed_job_cannot_start_or_cancel() -> None:
    job = DownloadJob(
        id=1,
        user_id=10,
        chat_id=20,
        source_url="https://github.com/example/project/archive/refs/heads/main.zip",
        status=JobStatus.COMPLETED,
    )
    assert not job.can_start()
    assert not job.can_cancel()
