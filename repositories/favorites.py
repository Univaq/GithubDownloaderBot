import aiosqlite

from config import settings


MAX_FAVORITES_PER_USER = 20


async def add_favorite(user_id: int, repo_full_name: str) -> str:
    repo_full_name = repo_full_name.strip()

    if not repo_full_name or repo_full_name.count("/") != 1:
        return "invalid"

    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute("BEGIN IMMEDIATE")

        cursor = await db.execute(
            """
            SELECT 1
            FROM favorites
            WHERE user_id = ? AND repo_full_name = ?
            """,
            (user_id, repo_full_name),
        )

        if await cursor.fetchone():
            await db.commit()
            return "exists"

        cursor = await db.execute(
            "SELECT COUNT(*) FROM favorites WHERE user_id = ?",
            (user_id,),
        )
        count = (await cursor.fetchone())[0]

        if count >= MAX_FAVORITES_PER_USER:
            await db.commit()
            return "full"

        await db.execute(
            """
            INSERT INTO favorites (user_id, repo_full_name)
            VALUES (?, ?)
            """,
            (user_id, repo_full_name),
        )
        await db.commit()
        return "added"


async def is_favorite(user_id: int, repo_full_name: str) -> bool:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            SELECT 1
            FROM favorites
            WHERE user_id = ? AND repo_full_name = ?
            """,
            (user_id, repo_full_name),
        )
        return await cursor.fetchone() is not None


async def remove_favorite(user_id: int, repo_full_name: str) -> bool:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            DELETE FROM favorites
            WHERE user_id = ? AND repo_full_name = ?
            """,
            (user_id, repo_full_name),
        )
        await db.commit()
        return cursor.rowcount == 1


async def get_favorites(user_id: int) -> list[str]:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            SELECT repo_full_name
            FROM favorites
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
