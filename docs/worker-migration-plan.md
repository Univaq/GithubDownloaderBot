# Worker migration plan

## Current ownership

The production worker in `workers/download_worker.py` still uses the legacy persistence facade:

- `claim_next_job()` atomically changes one row from `queued` to `running`.
- `process_download_job()` consumes a dictionary with legacy keys such as `repo_url`, `queue_message_id`, and `queue_chat_id`.
- `finish_job()` and `fail_job()` change a row only when its current status is `running`.

The new `SQLiteJobRepository` implements similar operations and the `to_legacy_worker_payload()` mapper translates a domain `DownloadJob` to the legacy dictionary. Neither is wired into the production worker yet.

## Non-negotiable cutover invariants

1. **Exactly one claim owner.** A job must be claimed once. Do not call legacy `claim_next_job()` and new `SQLiteJobRepository.claim_next()` for the same worker iteration.
2. **One state-transition owner.** After a job is claimed, use one repository family for completion/failure. Do not claim with one adapter and finish with another without an explicit transaction/ownership design.
3. **Compare-and-set transitions.** Completion and failure must require the current state to be `running`; stale workers must not overwrite a newer state.
4. **Payload compatibility.** Preserve `id`, `user_id`, `chat_id`, `repo_url`, `job_type`, `file_name`, `status`, `error`, `queue_message_id`, and `queue_chat_id`.
5. **Side effects stay intact.** Keep progress updates, Telegram document upload, user failure notification, queue-message cleanup, and temporary-file cleanup unchanged during the first persistence cutover.
6. **Single active poller.** Do not run two bot instances against the same Telegram bot token during rollout; Telegram long polling can conflict.

## Recommended migration sequence

1. Keep the current production worker unchanged while tests cover row mapping and the compatibility payload.
2. Add worker-loop tests with stubbed persistence functions and a fake bot. Cover successful claim/completion, processing failure/failure status, failed status update, and graceful stop while idle.
3. Introduce one explicit worker persistence dependency (a small protocol or callbacks) so the worker's orchestration can be tested independently of SQLite.
4. In a separate change, switch the dependency to the new repository and keep the legacy payload mapper at the boundary. Ensure completion/failure use the same repository instance that claimed the job.
5. Run the full CI suite and a controlled staging/manual smoke test before deployment. Keep the old facade available until rollback is no longer needed.

## Rollback

If the new worker path fails verification, revert the worker wiring only and return to the legacy facade. Do not run both worker paths concurrently, and do not change the database schema as part of the first worker cutover.

## Current readiness

The architecture PR is still a draft. The adapter and mapper are test-covered, but production worker wiring and live deployment have not been performed.
