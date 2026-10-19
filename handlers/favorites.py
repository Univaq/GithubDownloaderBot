
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards.inline import ITEMS_PER_PAGE, repository_action_keyboard
from repositories.jobs import (
    add_favorite,
    get_favorites,
    is_favorite,
    remove_favorite,
)
from services.callback_cache import get_repository, store_repository


router = Router(name="favorites")
logger = logging.getLogger(__name__)

MAX_FAVORITES = 20


def _favorites_keyboard(
    favorites: list[str],
    page: int = 0,
):
    favorites = favorites[:MAX_FAVORITES]
    total_pages = max(
        1,
        (len(favorites) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE,
    )
    page = max(0, min(page, total_pages - 1))

    start = page * ITEMS_PER_PAGE
    current_favorites = favorites[start : start + ITEMS_PER_PAGE]

    builder = InlineKeyboardBuilder()

    for full_name in current_favorites:
        repository_id = store_repository(full_name)
        builder.button(
            text=f"📦 {full_name}"[:60],
            callback_data=f"favorite:open:{repository_id}",
        )

    nav_count = 0
    if total_pages > 1:
        if page > 0:
            builder.button(
                text="⬅️ Previous",
                callback_data=f"favorites_page:{page - 1}",
            )
            nav_count += 1

        builder.button(
            text=f"📄 {page + 1}/{total_pages}",
            callback_data=f"favorites_info:{page}",
        )
        nav_count += 1

        if page < total_pages - 1:
            builder.button(
                text="Next ➡️",
                callback_data=f"favorites_page:{page + 1}",
            )
            nav_count += 1

    builder.button(
        text="🏠 Main Menu",
        callback_data="menu:main",
    )

    # مخزن هر مخزن در یک ردیف؛ کنترل‌های صفحه‌بندی در یک ردیف.
    if nav_count:
        builder.adjust(*([1] * len(current_favorites)), nav_count, 1)
    else:
        builder.adjust(1)

    return builder.as_markup(), page, total_pages


async def _render_favorites(
    message: Message,
    user_id: int,
    page: int = 0,
    edit: bool = True,
) -> None:
    favorites = (await get_favorites(user_id))[:MAX_FAVORITES]
    keyboard, page, total_pages = _favorites_keyboard(favorites, page)

    if favorites:
        text = (
            "⭐ <b>Your Favorites</b>\n\n"
            "Choose a repository to view its options.\n"
            f"Repositories: {len(favorites)}"
        )
        if total_pages > 1:
            text += f"\nPage {page + 1} of {total_pages}"
    else:
        text = "⭐ <b>Your Favorites</b>\n\nNo favorites yet. Save a repository and it’ll show up here."

    if edit:
        try:
            await message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return
        except TelegramBadRequest as exc:
            logger.warning("Could not edit Favorites page: %s", exc)

    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("favorite:add:"))
async def add_favorite_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    repository_id = callback.data.removeprefix("favorite:add:")
    full_name = get_repository(repository_id)

    if not full_name:
        await callback.answer(
            "This repository session has expired. Please open the repository again.",
            show_alert=True,
        )
        return

    result = await add_favorite(callback.from_user.id, full_name)

    if result == "full":
        await callback.answer(
            "Your Favorites are full (20 repositories). Remove one to make room.",
            show_alert=True,
        )
        return

    if result == "invalid":
        await callback.answer("That repository selection doesn’t look right.", show_alert=True)
        return

    if result == "exists":
        await callback.answer("Already saved to Favorites ⭐")
    elif result == "added":
        await callback.answer("Added to Favorites ⭐")
    else:
        await callback.answer("We couldn’t update your Favorites. Please try again.", show_alert=True)
        return

    if callback.message:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=repository_action_keyboard(
                    full_name,
                    is_favorite=True,
                )
            )
        except TelegramBadRequest as exc:
            logger.warning("Could not update favorite button: %s", exc)


async def show_favorites(
    message: Message,
    state: FSMContext,
    user_id: int | None = None,
    edit: bool = False,
) -> None:
    if user_id is None:
        if not message.from_user:
            return
        user_id = message.from_user.id

    await state.set_state("viewing_favorites")
    await _render_favorites(
        message=message,
        user_id=user_id,
        page=0,
        edit=edit,
    )


@router.callback_query(F.data.startswith("favorites_page:"))
async def favorites_page_handler(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    try:
        page = int(callback.data.removeprefix("favorites_page:"))
        if page < 0:
            raise ValueError
    except ValueError:
        await callback.answer("That page number isn’t valid.", show_alert=True)
        return

    await callback.answer()
    await state.set_state("viewing_favorites")
    await _render_favorites(
        message=callback.message,
        user_id=callback.from_user.id,
        page=page,
        edit=True,
    )


@router.callback_query(F.data.startswith("favorites_info:"))
async def favorites_info_handler(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("favorite:open:"))
async def open_favorite_handler(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not callback.data or not callback.from_user:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    repository_id = callback.data.removeprefix("favorite:open:")
    full_name = get_repository(repository_id)

    if not full_name:
        await callback.answer(
            "This Favorites session has expired. Please open Favorites again.",
            show_alert=True,
        )
        return

    if not callback.message:
        await callback.answer("This message is no longer available. Please open the menu again.", show_alert=True)
        return

    await callback.answer()

    favorite_status = await is_favorite(callback.from_user.id, full_name)
    await state.set_state("viewing_favorites")

    text = (
        f"📦 <b>{full_name}</b>\n\n"
        "What would you like to explore or download?"
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=repository_action_keyboard(
                full_name,
                is_favorite=favorite_status,
            ),
            parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        logger.warning(
            "Could not edit Favorite repository message: %s",
            exc,
        )


@router.callback_query(F.data.startswith("favorite:remove:"))
async def remove_favorite_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    repository_id = callback.data.removeprefix("favorite:remove:")
    full_name = get_repository(repository_id)

    if not full_name:
        await callback.answer(
            "This Favorites session has expired. Please open Favorites again.",
            show_alert=True,
        )
        return

    removed = await remove_favorite(callback.from_user.id, full_name)

    if not removed:
        await callback.answer("This repository isn’t in your Favorites.")
        return

    await callback.answer("Removed from Favorites 🗑️")

    if callback.message:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=repository_action_keyboard(
                    full_name,
                    is_favorite=False,
                )
            )
        except TelegramBadRequest as exc:
            logger.warning("Could not update favorite button: %s", exc)
