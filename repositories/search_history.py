import aiosqlite

from config import settings


async def add_search_history(user_id: int, query: str) -> None:
    query = query.strip()[:200]

    if not query:
        return

    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute("BEGIN IMMEDIATE")

        await db.execute(
            """
            INSERT INTO search_history (user_id, query)
            VALUES (?, ?)
            """,
            (user_id, query),
        )

        # فقط ۲۰ جست‌وجوی جدیدتر هر کاربر نگه داشته می‌شود.
        await db.execute(
            """
            DELETE FROM search_history
            WHERE user_id = ?
              AND id NOT IN (
                  SELECT id
                  FROM search_history
                  WHERE user_id = ?
                  ORDER BY id DESC
                  LIMIT 20
              )
            """,
            (user_id, user_id),
        )

        await db.commit()



async def get_search_history(
    user_id: int,
    limit: int = 20,
) -> list[dict]:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            SELECT id, query, created_at
            FROM search_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = await cursor.fetchall()

    return [
        {
            "id": row[0],
            "query": row[1],
            "created_at": row[2],
        }
        for row in rows
    ]
