"""Telegram callback for selecting repository source archives."""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from handlers.releases import send_source_selection
from services.callback_cache import get_repository

router = Router(name="source_code")


@router.callback_query(F.data.startswith("choice:src:"))
async def choose_source_code(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    token = callback.data.removeprefix("choice:src:")
    full_name = get_repository(token)

    if full_name is None:
        await callback.answer(
            "This selection has expired. Please search again 🔎",
            show_alert=True,
        )
        return

    await callback.answer()
    await send_source_selection(callback, full_name)
