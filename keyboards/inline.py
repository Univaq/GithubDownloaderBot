
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.callback_cache import (
    store_repository,
    store_release,
    link_repository_to_search,
    get_repository_search,
)


CALLBACK_MAX_BYTES = 64
MAX_BUTTON_TEXT_LENGTH = 60
ITEMS_PER_PAGE = 10
MAX_REPOSITORIES = ITEMS_PER_PAGE
RELEASES_PER_PAGE = ITEMS_PER_PAGE


def _validate_callback_data(callback_data: str) -> str:
    if len(callback_data.encode("utf-8")) > CALLBACK_MAX_BYTES:
        raise ValueError(
            "Callback data exceeds Telegram's 64-byte limit."
        )
    return callback_data


def add_back_button(
    builder: InlineKeyboardBuilder,
    callback_data: str,
    text: str = "⬅️ Back",
) -> None:
    builder.button(
        text=text[:MAX_BUTTON_TEXT_LENGTH],
        callback_data=_validate_callback_data(callback_data),
    )


def _add_pagination_buttons(
    builder: InlineKeyboardBuilder,
    *,
    page: int,
    total_pages: int,
    previous_callback: str,
    info_callback: str,
    next_callback: str,
) -> None:
    """Add previous, page indicator, and next buttons when needed."""
    if total_pages <= 1:
        return

    if page > 0:
        builder.button(
            text="⬅️ Previous",
            callback_data=_validate_callback_data(previous_callback),
        )

    builder.button(
        text=f"Page {page + 1}/{total_pages}",
        callback_data=_validate_callback_data(info_callback),
    )

    if page < total_pages - 1:
        builder.button(
            text="Next ➡️",
            callback_data=_validate_callback_data(next_callback),
        )


def pagination_keyboard(
    items: list,
    page: int,
    callback_prefix: str,
    back_callback: str,
    back_text: str = "⬅️ Back",
    page_size: int = ITEMS_PER_PAGE,
    item_callback=None,
    item_text=None,
) -> InlineKeyboardMarkup:
    """Build a generic paginated keyboard with page_size items per page."""
    if page_size < 1:
        raise ValueError("page_size must be at least 1.")

    builder = InlineKeyboardBuilder()
    total_items = len(items)
    total_pages = max(
        1,
        (total_items + page_size - 1) // page_size,
    )
    page = max(0, min(page, total_pages - 1))

    start = page * page_size
    current_items = items[start:start + page_size]

    for index, item in enumerate(current_items, start=start):
        label = (
            str(item_text(item))
            if item_text is not None
            else str(item)
        )

        callback_data = (
            item_callback(item, index)
            if item_callback is not None
            else f"{callback_prefix}:{index}"
        )

        builder.button(
            text=label[:MAX_BUTTON_TEXT_LENGTH],
            callback_data=_validate_callback_data(callback_data),
        )

    _add_pagination_buttons(
        builder,
        page=page,
        total_pages=total_pages,
        previous_callback=f"{callback_prefix}:page:{page - 1}",
        info_callback=f"{callback_prefix}:info:{page}",
        next_callback=f"{callback_prefix}:page:{page + 1}",
    )

    add_back_button(builder, back_callback, back_text)
    builder.adjust(1)
    return builder.as_markup()


def repository_keyboard(
    repositories: list,
    search_token: str,
    page: int = 0,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    valid_repositories = [
        repo
        for repo in repositories
        if isinstance(repo, dict) and repo.get("full_name")
    ]

    total_pages = max(
        1,
        (len(valid_repositories) + ITEMS_PER_PAGE - 1)
        // ITEMS_PER_PAGE,
    )
    page = max(0, min(page, total_pages - 1))

    start = page * ITEMS_PER_PAGE
    current_repositories = valid_repositories[
        start:start + ITEMS_PER_PAGE
    ]

    for repo in current_repositories:
        full_name = repo["full_name"]
        repository_id = store_repository(full_name)
        link_repository_to_search(repository_id, search_token)

        builder.button(
            text=f"📦 {full_name}"[:MAX_BUTTON_TEXT_LENGTH],
            callback_data=_validate_callback_data(
                f"repo:{repository_id}"
            ),
        )

    _add_pagination_buttons(
        builder,
        page=page,
        total_pages=total_pages,
        previous_callback=f"search_page:{search_token}:{page - 1}",
        info_callback=f"search_info:{search_token}:{page}",
        next_callback=f"search_page:{search_token}:{page + 1}",
    )

    builder.button(
        text="🔎 Search Again",
        callback_data=_validate_callback_data("search:again"),
    )

    add_back_button(
        builder,
        "menu:main",
        "⬅️ Back to Menu",
    )

    builder.adjust(1)
    return builder.as_markup()


def repository_action_keyboard(
    full_name: str,
    is_favorite: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    repository_id = store_repository(full_name)
    search_token = get_repository_search(repository_id)

    favorite_action = "remove" if is_favorite else "add"
    favorite_text = (
        "❌ Remove from Favorites"
        if is_favorite
        else "⭐ Add to Favorites"
    )

    builder.button(
        text="📥 Download Source Code",
        callback_data=_validate_callback_data(
            f"choice:src:{repository_id}"
        ),
    )

    builder.button(
        text="🚀 Browse Releases",
        callback_data=_validate_callback_data(
            f"choice:rel:{repository_id}"
        ),
    )

    builder.button(
        text="📄 View README",
        callback_data=_validate_callback_data(
            f"choice:readme:{repository_id}"
        ),
    )

    builder.button(
        text=favorite_text,
        callback_data=_validate_callback_data(
            f"favorite:{favorite_action}:{repository_id}"
        ),
    )

    if search_token:
        add_back_button(
            builder,
            f"back:search:{search_token}",
            "⬅️ Back to Search Results",
        )
    else:
        add_back_button(
            builder,
            "menu:main",
            "⬅️ Back to Menu",
        )

    builder.adjust(1)
    return builder.as_markup()


def releases_keyboard(
    full_name: str,
    releases: list,
    page: int = 0,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    repository_id = store_repository(full_name)

    valid_releases = [
        release
        for release in releases
        if isinstance(release, dict) and release.get("tag_name")
    ]

    total_pages = max(
        1,
        (len(valid_releases) + RELEASES_PER_PAGE - 1)
        // RELEASES_PER_PAGE,
    )
    page = max(0, min(page, total_pages - 1))

    start = page * RELEASES_PER_PAGE
    current_releases = valid_releases[
        start:start + RELEASES_PER_PAGE
    ]

    for release in current_releases:
        tag = release["tag_name"]
        name = release.get("name") or tag
        release_id = store_release(full_name, tag)

        builder.button(
            text=f"🚀 {name}"[:MAX_BUTTON_TEXT_LENGTH],
            callback_data=_validate_callback_data(
                f"rel:{release_id}"
            ),
        )

    _add_pagination_buttons(
        builder,
        page=page,
        total_pages=total_pages,
        previous_callback=f"releases_page:{repository_id}:{page - 1}",
        info_callback=f"releases_info:{repository_id}:{page}",
        next_callback=f"releases_page:{repository_id}:{page + 1}",
    )

    add_back_button(
        builder,
        f"back:repo:{repository_id}",
        "⬅️ Back to Repository",
    )

    builder.adjust(1)
    return builder.as_markup()


def download_keyboard(
    selections: list,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for selection_id, label in selections:
        builder.button(
            text=str(label)[:MAX_BUTTON_TEXT_LENGTH],
            callback_data=_validate_callback_data(
                f"get:{selection_id}"
            ),
        )

    builder.adjust(1)
    return builder.as_markup()


def readme_download_keyboard(
    token: str,
    repository_id: str,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="📥 Download README (.md)",
        callback_data=_validate_callback_data(
            f"readme_fmt:md:{token}:0"
        ),
    )

    add_back_button(
        builder,
        f"back:repo:{repository_id}",
        "⬅️ Back to Repository",
    )

    builder.adjust(1)
    return builder.as_markup()


def search_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    add_back_button(
        builder,
        "menu:main",
        "⬅️ Back to Menu",
    )

    builder.adjust(1)
    return builder.as_markup()

def download_completion_keyboard(
    full_name: str | None,
    *,
    readme: bool = False,
) -> InlineKeyboardMarkup:
    """Actions shown after a downloaded file has been sent."""
    builder = InlineKeyboardBuilder()

    if full_name and full_name.count("/") == 1:
        repository_id = store_repository(full_name)
        # Keep the repository name in callback data when it fits, so this
        # button also works when the download worker and bot use separate
        # processes with independent in-memory callback caches.
        repository_ref = (
            full_name
            if len(f"back:repo:{full_name}".encode("utf-8")) <= CALLBACK_MAX_BYTES
            else repository_id
        )
        if not readme:
            builder.button(
                text="📥 Download another file",
                callback_data=_validate_callback_data(
                    f"download:another:{repository_id}"
                ),
            )
        builder.button(
            text="📁 Back to Repository",
            callback_data=_validate_callback_data(
                f"back:repo:{repository_ref}"
            ),
        )
    else:
        builder.button(
            text="🔎 Search Again",
            callback_data=_validate_callback_data("search:again"),
        )

    builder.button(
        text="🏠 Main Menu",
        callback_data=_validate_callback_data("menu:main"),
    )
    builder.adjust(1)
    return builder.as_markup()

