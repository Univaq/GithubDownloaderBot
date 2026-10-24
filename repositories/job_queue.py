import aiosqlite

from config import settings


async def enqueue_selection(
    selection_id: str,
    user_id: int,
    queue_message_id: int | None = None,
    queue_chat_id: int | None = None,
) -> int | None:
    async with aiosqlite.connect(settings.database_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")

        cursor = await db.execute(
            """
            SELECT *
            FROM selections
            WHERE id = ? AND user_id = ?
            """,
            (selection_id, user_id),
        )
        selection = await cursor.fetchone()

        if selection is None:
            await db.rollback()
            return None

        cursor = await db.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE status = 'queued'
            """
        )
        queued_count = (await cursor.fetchone())[0]

        if queued_count >= settings.max_queue_size:
            await db.rollback()
            return -1

        cursor = await db.execute(
            """
            INSERT INTO jobs (
                user_id,
                chat_id,
                repo_url,
                job_type,
                file_name,
                queue_message_id,
                queue_chat_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                selection["user_id"],
                selection["chat_id"],
                selection["download_url"],
                selection["job_type"],
                selection["file_name"],
                queue_message_id,
                queue_chat_id,
            ),
        )

        job_id = cursor.lastrowid

        await db.execute(
            "DELETE FROM selections WHERE id = ?",
            (selection_id,),
        )

        await db.commit()
        return job_id


async def claim_next_job() -> dict | None:
    async with aiosqlite.connect(settings.database_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")

        cursor = await db.execute(
            """
            SELECT *
            FROM jobs
            WHERE status = 'queued'
            ORDER BY id
            LIMIT 1
            """
        )
        row = await cursor.fetchone()

        if row is None:
            await db.commit()
            return None

        cursor = await db.execute(
            """
            UPDATE jobs
            SET status = 'running',
                updated_at = CURRENT_TIMESTAMP,
                error = NULL
            WHERE id = ? AND status = 'queued'
            """,
            (row["id"],),
        )

        if cursor.rowcount != 1:
            await db.rollback()
            return None

        job = dict(row)
        job["status"] = "running"

        await db.commit()
        return job


async def finish_job(job_id: int) -> bool:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            UPDATE jobs
            SET status = 'completed',
                updated_at = CURRENT_TIMESTAMP,
                error = NULL
            WHERE id = ? AND status = 'running'
            """,
            (job_id,),
        )
        await db.commit()
        return cursor.rowcount == 1


async def fail_job(job_id: int, error: str) -> bool:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                updated_at = CURRENT_TIMESTAMP,
                error = ?
            WHERE id = ? AND status = 'running'
            """,
            (error[:500], job_id),
        )
        await db.commit()
        return cursor.rowcount == 1


async def get_queue_size() -> int:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE status = 'queued'
            """
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
