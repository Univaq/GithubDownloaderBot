"""Compatibility facade for legacy persistence imports.

New code should import focused persistence modules directly. Existing handlers
and workers can continue importing from repositories.jobs during migration.
"""
from repositories.database import SCHEMA, initialize_database
from repositories.selections import create_selection, get_selection
from repositories.job_queue import (
    enqueue_selection,
    claim_next_job,
    finish_job,
    fail_job,
    get_queue_size,
)
from repositories.favorites import (
    MAX_FAVORITES_PER_USER,
    add_favorite,
    is_favorite,
    remove_favorite,
    get_favorites,
)
from repositories.search_history import add_search_history, get_search_history

__all__ = [
    "SCHEMA", "initialize_database",
    "create_selection", "get_selection",
    "enqueue_selection", "claim_next_job", "finish_job", "fail_job",
    "get_queue_size", "MAX_FAVORITES_PER_USER", "add_favorite",
    "is_favorite", "remove_favorite", "get_favorites",
    "add_search_history", "get_search_history",
]
