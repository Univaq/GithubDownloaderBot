"""Telegram callbacks for repository details and actions."""

import html
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from keyboards.inline import repository_action_keyboard
from repositories.jobs import is_favorite
from services.callback_cache import get_repository
from services.github import GitHubError, GitHubRateLimitError, GitHubService
from services.repository_presenter import format_repository_card

logger = logging.getLogger(__name__)
router = Router(name="repository")


@router.callback_query(F.data.startswith("repo:"))
async def select_repository(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    token = callback.data.removeprefix("repo:")
    full_name = get_repository(token)

    if full_name is None or full_name.count("/") != 1:
        await callback.answer(
            "This selection has expired. Please search again 🔎",
            show_alert=True,
        )
        return

    await callback.answer()

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            repository = await github.get_repository(owner, repo)

        message_text = format_repository_card(full_name, repository)

    except GitHubRateLimitError:
        message_text = (
            f"📦 <b>{html.escape(full_name)}</b>\n\n"
            "⚠️ GitHub’s request limit has been reached. "
            "Repository details are temporarily unavailable. Please try again shortly.\n\n"
            "<b>Choose an action below</b>"
        )

    except GitHubError:
        logger.exception(
            "Failed to retrieve repository details: %s",
            full_name,
        )
        message_text = (
            f"📦 <b>{html.escape(full_name)}</b>\n\n"
            "⚠️ We couldn’t load the repository details. Please try again.\n\n"
            "<b>Choose an action below</b>"
        )

    except Exception:
        logger.exception(
            "Unexpected error loading repository details: %s",
            full_name,
        )
        message_text = (
            f"📦 <b>{html.escape(full_name)}</b>\n\n"
            "⚠️ Something went wrong while loading the repository details.\n\n"
            "<b>Choose an action below</b>"
        )

    favorite_status = await is_favorite(
        callback.from_user.id,
        full_name,
    )

    await callback.message.edit_text(
        message_text,
        reply_markup=repository_action_keyboard(
            full_name,
            is_favorite=favorite_status,
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
