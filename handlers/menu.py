
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards.main import main_keyboard, search_mode_keyboard
from repositories.jobs import get_search_history

router = Router(name="menu")
logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 10
MAX_HISTORY_ITEMS = 20


async def edit_or_send(
    callback: CallbackQuery,
    text: str,
    reply_markup=None,
    parse_mode: str | None = None,
) -> None:
    message = callback.message
    if message is None:
        return

    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TelegramBadRequest as exc:
        logger.warning("Could not edit menu message: %s", exc)


async def _render_search_history(
    callback: CallbackQuery,
    user_id: int,
    page: int = 0,
) -> None:
    # تاریخچه حداکثر ۲۰ مورد؛ هر صفحه ۱۰ مورد.
    history = (await get_search_history(user_id))[:MAX_HISTORY_ITEMS]

    total_pages = max(
        1,
        (len(history) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE,
    )
    page = max(0, min(page, total_pages - 1))

    start = page * ITEMS_PER_PAGE
    page_items = history[start : start + ITEMS_PER_PAGE]

    builder = InlineKeyboardBuilder()

    for index, item in enumerate(page_items, start=start + 1):
        query = str(item["query"])
        builder.button(
            text=f"{index}. {query}"[:60],
            callback_data=f"history:search:{item['id']}",
        )

    if total_pages > 1:
        if page > 0:
            builder.button(
                text="⬅️ Previous",
                callback_data=f"history:page:{page - 1}",
            )

        builder.button(
            text=f"📄 {page + 1}/{total_pages}",
            callback_data=f"history:info:{page}",
        )

        if page < total_pages - 1:
            builder.button(
                text="Next ➡️",
                callback_data=f"history:page:{page + 1}",
            )

    builder.button(
        text="🏠 Main Menu",
        callback_data="menu:main",
    )

    # هر جست‌وجو در یک ردیف؛ کنترل‌های صفحه‌بندی در یک ردیف.
    if total_pages > 1:
        nav_buttons = 1 + int(page > 0) + int(page < total_pages - 1)
        builder.adjust(*([1] * len(page_items)), nav_buttons, 1)
    else:
        builder.adjust(1)

    if history:
        text = (
            "🕘 <b>Search History</b>\n\n"
            "Pick a previous search to run it again."
        )
        if total_pages > 1:
            text += f"\n\nPage {page + 1} of {total_pages}"
    else:
        text = (
            "🕘 <b>Search History</b>\n\n"
            "No searches yet. Your recent searches will appear here."
        )

    await edit_or_send(
        callback,
        text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:main")
async def back_to_main_menu(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    # A callback can expire if Telegram delivers it late or it was already answered.
    # Do not let an expired acknowledgement prevent navigation to the main menu.
    try:
        await callback.answer()
    except TelegramBadRequest as exc:
        message = str(exc).lower()
        if "query is too old" not in message and "query id is invalid" not in message:
            raise
        logger.debug("Ignoring expired callback query while returning to main menu: %s", exc)

    await state.clear()

    await edit_or_send(
        callback,
        "🏠 <b>GitHub Bot</b>\n\nWhat would you like to do today?",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:search")
async def start_github_search(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    message = callback.message
    if message is None:
        await callback.answer("This message is no longer available. Please open the menu again.", show_alert=True)
        return

    await callback.answer()

    try:
        await message.edit_text(
            "🔎 Send a repository name, a search query, or a GitHub link to get started.",
            reply_markup=search_mode_keyboard(),
        )
    except TelegramBadRequest as exc:
        logger.warning("Could not display search prompt: %s", exc)
        return

    await state.set_state("waiting_for_repository_query")
    await state.update_data(
        search_prompt_chat_id=message.chat.id,
        search_prompt_message_id=message.message_id,
    )


@router.callback_query(F.data == "menu:favorites")
async def open_favorites(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not callback.from_user:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    message = callback.message
    if message is None:
        await callback.answer("This message is no longer available. Please open the menu again.", show_alert=True)
        return

    await callback.answer()

    from handlers.favorites import show_favorites

    await show_favorites(
        message,
        state,
        user_id=callback.from_user.id,
        edit=True,
    )


@router.callback_query(F.data == "menu:history")
async def show_search_history(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not callback.from_user:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    await callback.answer()
    await state.set_state("viewing_search_history")

    await _render_search_history(
        callback,
        user_id=callback.from_user.id,
        page=0,
    )


@router.callback_query(F.data.startswith("history:page:"))
async def change_history_page(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    try:
        page = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("That page number isn’t valid.", show_alert=True)
        return

    if page < 0:
        await callback.answer("That page number isn’t valid.", show_alert=True)
        return

    await callback.answer()
    await _render_search_history(
        callback,
        user_id=callback.from_user.id,
        page=page,
    )


@router.callback_query(F.data.startswith("history:info:"))
async def history_page_info(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer()
        return

    try:
        page = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer()
        return

    await callback.answer(f"History page {page + 1}")


@router.callback_query(F.data.startswith("history:search:"))
async def repeat_search_from_history(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not callback.data or not callback.from_user:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    try:
        history_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid search selection.", show_alert=True)
        return

    history = (await get_search_history(callback.from_user.id))[
        :MAX_HISTORY_ITEMS
    ]
    entry = next(
        (item for item in history if item["id"] == history_id),
        None,
    )

    if entry is None:
        await callback.answer(
            "This search history entry is no longer available.",
            show_alert=True,
        )
        return

    await callback.answer()
    await state.clear()

    if callback.message:
        from handlers.search import perform_repository_search

        await perform_repository_search(
            callback.message,
            entry["query"],
            user_id=callback.from_user.id,
            edit=True,
        )
