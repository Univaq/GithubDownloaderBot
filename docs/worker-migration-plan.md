# Worker migration plan

## Current ownership

The production worker in `workers/download_worker.py` supports two persistence paths:

- By default, it uses the legacy persistence facade. This remains the safe default.
- When `USE_SQLITE_WORKER_GATEWAY=true`, it uses `LegacyWorkerJobGateway(SQLiteJobRepository(...))`.
- `process_download_job()` continues to consume the legacy-compatible dictionary payload.
- The SQLite repository claims jobs atomically and guards completion/failure transitions against stale status changes.

## Non-negotiable cutover invariants

1. **Exactly one claim owner.** A job must be claimed once. Do not call legacy `claim_next_job()` and new `SQLiteJobRepository.claim_next()` for the same worker iteration.
2. **One state-transition owner.** After a job is claimed, use one repository family for completion/failure.
3. **Compare-and-set transitions.** Completion and failure must require the current state to be `running`; stale workers must not overwrite a newer state.
4. **Payload compatibility.** Preserve `id`, `user_id`, `chat_id`, `repo_url`, `job_type`, `file_name`, `status`, `error`, `queue_message_id`, and `queue_chat_id`.
5. **Side effects stay intact.** Keep progress updates, Telegram document upload, user failure notification, queue-message cleanup, and temporary-file cleanup unchanged during the first persistence cutover.
6. **Single active poller.** Do not run two bot instances against the same Telegram bot token during rollout; Telegram long polling can conflict.

## Verification and rollout

1. Keep `USE_SQLITE_WORKER_GATEWAY` unset or set to `false` while using the legacy path.
2. Automated GitHub Actions triggers are currently disabled; the workflow can only be started manually with `workflow_dispatch`.
3. Before enabling the new gateway in production, manually run the CI workflow and verify the full test suite.
4. Then use a staging/manual smoke test to verify queue claiming, successful completion, processing failures, Telegram notifications, and restart recovery.
5. Enable `USE_SQLITE_WORKER_GATEWAY=true` only after those checks pass, and monitor logs closely.

## Rollback

If the new worker path fails verification, unset `USE_SQLITE_WORKER_GATEWAY` or set it to `false`, then restart the bot. Do not run both worker paths concurrently, and do not change the database schema as part of the first persistence cutover.

## Current readiness

The architecture PR is still a draft and has not been deployed to the VPS. The gateway is opt-in; the default remains legacy persistence. No live deployment or VPS change has been performed.