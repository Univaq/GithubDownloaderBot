import secrets

import aiosqlite

from config import settings


async def create_selection(
    user_id: int,
    chat_id: int,
    download_url: str,
    file_name: str,
    job_type: str,
) -> str:
    async with aiosqlite.connect(settings.database_path) as db:
        while True:
            selection_id = secrets.token_urlsafe(8)

            cursor = await db.execute(
                "SELECT 1 FROM selections WHERE id = ?",
                (selection_id,),
            )
            if await cursor.fetchone() is None:
                break

        await db.execute(
            """
            INSERT INTO selections (
                id,
                user_id,
                chat_id,
                download_url,
                file_name,
                job_type
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                selection_id,
                user_id,
                chat_id,
                download_url,
                file_name[:200],
                job_type,
            ),
        )

        await db.commit()

    return selection_id


async def get_selection(selection_id: str) -> dict | None:
    async with aiosqlite.connect(settings.database_path) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT * FROM selections WHERE id = ?",
            (selection_id,),
        )
        row = await cursor.fetchone()

        return dict(row) if row else None
