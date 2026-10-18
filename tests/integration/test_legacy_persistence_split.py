from types import SimpleNamespace
import os

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")

import pytest

import repositories.database as database
import repositories.favorites as favorites
import repositories.job_queue as job_queue
import repositories.search_history as search_history
import repositories.selections as selections
import repositories.jobs as legacy_jobs


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        database_path=tmp_path / "jobs.db",
        max_queue_size=100,
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
async def test_legacy_facade_and_split_repositories_share_existing_schema(
    isolated_database,
):
    await legacy_jobs.initialize_database()

    selection_id = await legacy_jobs.create_selection(
        user_id=123,
        chat_id=456,
        download_url="https://github.com/example/project/archive/main.zip",
        file_name="project.zip",
        job_type="source",
    )
    selection = await selections.get_selection(selection_id)
    assert selection is not None
    assert selection["user_id"] == 123
    assert selection["file_name"] == "project.zip"

    job_id = await legacy_jobs.enqueue_selection(selection_id, user_id=123)
    assert job_id is not None and job_id > 0
    assert await legacy_jobs.get_queue_size() == 1
    assert await selections.get_selection(selection_id) is None

    claimed = await legacy_jobs.claim_next_job()
    assert claimed is not None
    assert claimed["id"] == job_id
    assert claimed["status"] == "running"
    assert await legacy_jobs.finish_job(job_id)
    assert await legacy_jobs.get_queue_size() == 0

    assert await favorites.add_favorite(123, "example/project") == "added"
    assert await favorites.is_favorite(123, "example/project")
    assert await favorites.get_favorites(123) == ["example/project"]
    assert await favorites.remove_favorite(123, "example/project")
    assert not await favorites.is_favorite(123, "example/project")

    await search_history.add_search_history(123, "  async python  ")
    history = await search_history.get_search_history(123)
    assert len(history) == 1
    assert history[0]["query"] == "async python"

    # Existing callers can continue importing all public APIs from jobs.py.
    assert legacy_jobs.create_selection is selections.create_selection
    assert legacy_jobs.add_favorite is favorites.add_favorite
    assert legacy_jobs.add_search_history is search_history.add_search_history
