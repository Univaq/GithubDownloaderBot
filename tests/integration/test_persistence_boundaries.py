from types import SimpleNamespace
import os

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")

import pytest

import repositories.database as database
import repositories.favorites as favorites
import repositories.job_queue as job_queue
import repositories.search_history as search_history
import repositories.selections as selections


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        database_path=tmp_path / "jobs.db",
        max_queue_size=1,
    )
    for module in (
        database,
        favorites,
        job_queue,
        search_history,
        selections,
    ):
        monkeypatch.setattr(module, "settings", settings)
    return settings.database_path


@pytest.mark.asyncio
async def test_queue_capacity_and_selection_owner_are_enforced(isolated_database):
    await database.initialize_database()

    foreign_selection = await selections.create_selection(
        user_id=10,
        chat_id=100,
        download_url="https://example.test/foreign.zip",
        file_name="foreign.zip",
        job_type="source",
    )
    assert await job_queue.enqueue_selection(foreign_selection, user_id=11) is None
    assert await selections.get_selection(foreign_selection) is not None

    first = await selections.create_selection(
        user_id=10,
        chat_id=100,
        download_url="https://example.test/first.zip",
        file_name="first.zip",
        job_type="source",
    )
    second = await selections.create_selection(
        user_id=12,
        chat_id=120,
        download_url="https://example.test/second.zip",
        file_name="second.zip",
        job_type="source",
    )

    first_job_id = await job_queue.enqueue_selection(first, user_id=10)
    assert first_job_id is not None and first_job_id > 0
    assert await job_queue.get_queue_size() == 1

    # Full queue must not consume the pending selection.
    assert await job_queue.enqueue_selection(second, user_id=12) == -1
    assert await selections.get_selection(second) is not None

    claimed = await job_queue.claim_next_job()
    assert claimed is not None
    assert claimed["id"] == first_job_id
    assert await job_queue.finish_job(first_job_id)
    assert await job_queue.get_queue_size() == 0

    second_job_id = await job_queue.enqueue_selection(second, user_id=12)
    assert second_job_id is not None and second_job_id > 0


@pytest.mark.asyncio
async def test_favorites_are_deduplicated_and_capped_per_user(isolated_database):
    await database.initialize_database()

    assert await favorites.add_favorite(1, "not-a-repository") == "invalid"
    for index in range(favorites.MAX_FAVORITES_PER_USER):
        assert await favorites.add_favorite(1, f"owner/repo-{index}") == "added"

    assert await favorites.add_favorite(1, "owner/repo-0") == "exists"
    assert await favorites.add_favorite(1, "owner/overflow") == "full"

    # Limits are per-user; another user can still save a favorite.
    assert await favorites.add_favorite(2, "owner/overflow") == "added"
    assert len(await favorites.get_favorites(1)) == favorites.MAX_FAVORITES_PER_USER
    assert await favorites.get_favorites(2) == ["owner/overflow"]


@pytest.mark.asyncio
async def test_search_history_keeps_only_latest_twenty_per_user(isolated_database):
    await database.initialize_database()

    for index in range(25):
        await search_history.add_search_history(1, f"query-{index}")
    await search_history.add_search_history(1, "   ")
    await search_history.add_search_history(2, "private-query")

    history = await search_history.get_search_history(1, limit=50)
    assert len(history) == 20
    assert history[0]["query"] == "query-24"
    assert history[-1]["query"] == "query-5"
    other_user_history = await search_history.get_search_history(2)
    assert len(other_user_history) == 1
    assert other_user_history[0]["query"] == "private-query"


@pytest.mark.asyncio
async def test_database_startup_marks_interrupted_running_jobs_failed(
    isolated_database,
):
    import aiosqlite

    await database.initialize_database()
    async with aiosqlite.connect(isolated_database) as db:
        cursor = await db.execute(
            """
            INSERT INTO jobs (user_id, chat_id, repo_url, status)
            VALUES (?, ?, ?, 'running')
            """,
            (99, 999, "https://example.test/interrupted.zip"),
        )
        job_id = cursor.lastrowid
        await db.commit()

    # Simulate a process restart: startup initialization repairs stale state.
    await database.initialize_database()
    async with aiosqlite.connect(isolated_database) as db:
        cursor = await db.execute(
            "SELECT status, error FROM jobs WHERE id = ?",
            (job_id,),
        )
        status, error = await cursor.fetchone()

    assert status == "failed"
    assert error == "Interrupted by process restart"
