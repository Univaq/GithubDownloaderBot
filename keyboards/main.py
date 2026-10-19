
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔎 Search GitHub",
        callback_data="menu:search",
    )
    builder.button(
        text="⭐ Favorites",
        callback_data="menu:favorites",
    )
    builder.button(
        text="🕘 Recent Searches",
        callback_data="menu:history",
    )

    builder.adjust(1)
    return builder.as_markup()


def github_keyboard() -> InlineKeyboardMarkup:
    """Kept for compatibility with other handlers."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔎 Search GitHub",
        callback_data="menu:search",
    )
    builder.button(
        text="⭐ Favorites",
        callback_data="menu:favorites",
    )
    builder.button(
        text="🕘 Recent Searches",
        callback_data="menu:history",
    )
    builder.button(
        text="🏠 Main Menu",
        callback_data="menu:main",
    )

    builder.adjust(1)
    return builder.as_markup()


def search_mode_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🏠 Main Menu",
        callback_data="menu:main",
    )

    builder.adjust(1)
    return builder.as_markup()


def favorites_mode_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🏠 Main Menu",
        callback_data="menu:main",
    )

    builder.adjust(1)
    return builder.as_markup()


def history_mode_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🏠 Main Menu",
        callback_data="menu:main",
    )

    builder.adjust(1)
    return builder.as_markup()
