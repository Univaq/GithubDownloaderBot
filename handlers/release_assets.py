"""Telegram callbacks for GitHub release and asset downloads."""

import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from handlers.releases import (
    _render_release_assets,
    back_to_repository_keyboard,
    show_github_error,
)
from keyboards.inline import releases_keyboard
from repositories.jobs import create_selection, enqueue_selection
from services.callback_cache import get_release, get_repository
from services.github import (
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubService,
)

logger = logging.getLogger(__name__)
router = Router(name="release_assets")


@router.callback_query(F.data.startswith("choice:rel:"))
async def choose_releases(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("Invalid request.", show_alert=True)
        return

    token = callback.data.removeprefix("choice:rel:")
    full_name = get_repository(token)

    if full_name is None:
        await callback.answer(
            "This selection has expired. Please search again.",
            show_alert=True,
        )
        return

    if full_name.count("/") != 1:
        await callback.answer(
            "Invalid repository selection.",
            show_alert=True,
        )
        return

    await callback.answer()

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            releases = await github.get_releases(owner, repo)

        if not releases:
            await callback.message.edit_text(
                f"🚀 <b>Releases</b>\n"
                f"<code>{full_name}</code>\n\n"
                "No releases have been published for this repository.",
                reply_markup=back_to_repository_keyboard(full_name),
                parse_mode="HTML",
            )
            return

        await callback.message.edit_text(
            f"🚀 <b>Available Releases</b>\n"
            f"<code>{full_name}</code>\n\n"
            "Select a release:",
            reply_markup=releases_keyboard(full_name, releases),
            parse_mode="HTML",
        )

    except GitHubNotFoundError:
        await show_github_error(
            callback,
            "❌ Repository not found.",
            full_name,
        )

    except GitHubRateLimitError:
        await show_github_error(
            callback,
            "⏳ GitHub rate limit reached. Please try again later.",
            full_name,
        )

    except GitHubError:
        logger.exception("Failed to fetch repository releases")
        await show_github_error(
            callback,
            "❌ Failed to retrieve repository releases.",
            full_name,
        )

    except Exception:
        logger.exception("Unexpected error while fetching releases")
        await show_github_error(
            callback,
            "❌ An unexpected error occurred. Please try again later.",
            full_name,
        )

@router.callback_query(F.data.startswith("rel:"))
async def release_selected(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("Invalid request.", show_alert=True)
        return

    token = callback.data.removeprefix("rel:")
    release_info = get_release(token)

    if release_info is None:
        await callback.answer(
            "This release selection has expired. Please search again.",
            show_alert=True,
        )
        return

    full_name, tag = release_info

    if full_name.count("/") != 1 or not tag:
        await callback.answer("Invalid release selection.", show_alert=True)
        return

    await callback.answer()

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            releases = await github.get_releases(owner, repo)

        release = next(
            (
                item for item in releases
                if item.get("tag_name") == tag
            ),
            None,
        )

        if release is None:
            await callback.message.edit_text(
                "❌ This release could not be found.",
                reply_markup=back_to_repository_keyboard(full_name),
            )
            return

        assets = [
            asset
            for asset in release.get("assets", [])
            if isinstance(asset, dict)
            and asset.get("name")
            and asset.get("download_url")
        ]

        if not assets:
            await callback.message.edit_text(
                f"🚀 <b>Release:</b> <code>{html.escape(tag)}</code>\n\n"
                "This release has no downloadable assets.",
                reply_markup=back_to_repository_keyboard(full_name),
                parse_mode="HTML",
            )
            return

        await _render_release_assets(
            callback=callback,
            full_name=full_name,
            tag=tag,
            assets=assets,
            release_token=token,
            page=0,
        )

    except GitHubNotFoundError:
        await show_github_error(
            callback,
            "❌ Repository or release not found.",
            full_name,
        )
    except GitHubRateLimitError:
        await show_github_error(
            callback,
            "⏳ GitHub rate limit reached. Please try again later.",
            full_name,
        )
    except GitHubError:
        logger.exception("Failed to retrieve release assets")
        await show_github_error(
            callback,
            "❌ Failed to retrieve release information.",
            full_name,
        )
    except Exception:
        logger.exception("Unexpected error while retrieving release assets")
        await show_github_error(
            callback,
            "❌ An unexpected error occurred. Please try again later.",
            full_name,
        )

@router.callback_query(F.data.startswith("get:"))
async def enqueue_download(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("Invalid request.", show_alert=True)
        return

    selection_id = callback.data.removeprefix("get:")
    previous_message = callback.message

    # این پیام باید باقی بماند تا worker بتواند آن را به‌روزرسانی کند.
    queue_message = await previous_message.answer(
        "⏳ Download request added to the queue."
    )

    try:
        job_id = await enqueue_selection(
            selection_id=selection_id,
            user_id=callback.from_user.id,
            queue_message_id=queue_message.message_id,
            queue_chat_id=queue_message.chat.id,
        )

    except Exception:
        try:
            await queue_message.delete()
        except Exception:
            logger.debug(
                "Failed to delete queue message after enqueue error",
                exc_info=True,
            )

        logger.exception("Failed to enqueue download")
        await callback.answer(
            "Failed to add the download to the queue.",
            show_alert=True,
        )
        return

    if job_id is None or job_id == -1:
        try:
            await queue_message.delete()
        except Exception:
            logger.debug(
                "Failed to delete rejected queue message",
                exc_info=True,
            )

        if job_id == -1:
            await callback.answer(
                "The download queue is currently full.",
                show_alert=True,
            )
        else:
            await callback.answer(
                "This selection is invalid or has already been used.",
                show_alert=True,
            )

        return

    # فقط بعد از ثبت موفق دانلود، پیام قبلی ربات را حذف می‌کنیم.
    # پیام صف حذف نمی‌شود و شناسه‌های آن در دیتابیس باقی می‌مانند.
    try:
        await previous_message.delete()
    except TelegramBadRequest:
        logger.warning(
            "Could not delete previous download menu message "
            "(chat_id=%s, message_id=%s)",
            previous_message.chat.id,
            previous_message.message_id,
            exc_info=True,
        )

    await callback.answer("Download added to the queue.")

README_FILES_PER_PAGE = 10

@router.callback_query(F.data.startswith("back:releases:"))
async def back_to_releases(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("Invalid request.", show_alert=True)
        return

    token = callback.data.removeprefix("back:releases:")
    full_name = get_repository(token)

    if not full_name or full_name.count("/") != 1:
        await callback.answer(
            "This selection has expired. Please search again.",
            show_alert=True,
        )
        return

    await callback.answer()

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            releases = await github.get_releases(owner, repo)

        if not releases:
            favorite_status = await is_favorite(
                callback.from_user.id,
                full_name,
            )

            await callback.message.edit_text(
                f"No releases found for <code>{full_name}</code>.",
                parse_mode="HTML",
                reply_markup=repository_action_keyboard(
                    full_name,
                    is_favorite=favorite_status,
                ),
            )
            return

        await callback.message.edit_text(
            f"🚀 <b>Available Releases</b>\n"
            f"<code>{full_name}</code>\n\n"
            "Select a release:",
            reply_markup=releases_keyboard(full_name, releases),
            parse_mode="HTML",
        )

    except GitHubError:
        logger.exception("Failed to retrieve repository releases")

        favorite_status = await is_favorite(
            callback.from_user.id,
            full_name,
        )

        await callback.message.edit_text(
            "Failed to retrieve repository releases.",
            reply_markup=repository_action_keyboard(
                full_name,
                is_favorite=favorite_status,
            ),
        )

@router.callback_query(F.data.startswith("releases_page:"))
async def change_releases_page(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("Invalid request.", show_alert=True)
        return

    try:
        _, token, page_text = callback.data.split(":", 2)
        page = int(page_text)
    except (ValueError, TypeError):
        await callback.answer("Invalid page selection.", show_alert=True)
        return

    if page < 0:
        await callback.answer("Invalid page number.", show_alert=True)
        return

    full_name = get_repository(token)

    if not full_name or full_name.count("/") != 1:
        await callback.answer(
            "This selection has expired. Please search again.",
            show_alert=True,
        )
        return

    await callback.answer()

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            releases = await github.get_releases(owner, repo)

        if not releases:
            await callback.message.edit_text(
                f"No releases found for <code>{html.escape(full_name)}</code>.",
                reply_markup=back_to_repository_keyboard(full_name),
                parse_mode="HTML",
            )
            return

        # releases_keyboard خودش شماره صفحه را بررسی و اصلاح می‌کند.
        await callback.message.edit_text(
            f"🚀 <b>Available Releases</b>\n"
            f"<code>{html.escape(full_name)}</code>\n\n"
            "Select a release:",
            reply_markup=releases_keyboard(
                full_name,
                releases,
                page=page,
            ),
            parse_mode="HTML",
        )

    except GitHubNotFoundError:
        await show_github_error(
            callback,
            "❌ Repository not found.",
            full_name,
        )

    except GitHubRateLimitError:
        await show_github_error(
            callback,
            "⏳ GitHub rate limit reached. Please try again later.",
            full_name,
        )

    except GitHubError:
        logger.exception(
            "Failed to load releases page for %s",
            full_name,
        )
        await show_github_error(
            callback,
            "❌ Failed to retrieve repository releases.",
            full_name,
        )

    except Exception:
        logger.exception(
            "Unexpected error while changing releases page for %s",
            full_name,
        )
        await show_github_error(
            callback,
            "❌ An unexpected error occurred. Please try again later.",
            full_name,
        )

@router.callback_query(F.data.startswith("releases_info:"))
async def releases_page_info(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid request.", show_alert=True)
        return

    try:
        _, token, page_text = callback.data.split(":", 2)
        page = int(page_text)
    except (ValueError, TypeError):
        await callback.answer("Invalid page selection.", show_alert=True)
        return

    if page < 0:
        await callback.answer("Invalid page number.", show_alert=True)
        return

    if get_repository(token) is None:
        await callback.answer(
            "This selection has expired. Please search again.",
            show_alert=True,
        )
        return

    # دکمهٔ شماره صفحه فقط اطلاعات می‌دهد؛ لازم نیست پیام ویرایش شود.
    await callback.answer(f"Page {page + 1}")

@router.callback_query(F.data.startswith("assets_page:"))
async def change_assets_page(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("Invalid request.", show_alert=True)
        return

    try:
        _, token, page_text = callback.data.split(":", 2)
        page = int(page_text)
        if page < 0:
            raise ValueError
    except ValueError:
        await callback.answer("Invalid page.", show_alert=True)
        return

    release_info = get_release(token)

    if release_info is None:
        await callback.answer(
            "This release selection has expired. Please search again.",
            show_alert=True,
        )
        return

    full_name, tag = release_info

    if full_name.count("/") != 1:
        await callback.answer("Invalid release selection.", show_alert=True)
        return

    await callback.answer()

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            releases = await github.get_releases(owner, repo)

        release = next(
            (
                item for item in releases
                if item.get("tag_name") == tag
            ),
            None,
        )

        if release is None:
            await show_github_error(
                callback,
                "❌ This release could not be found.",
                full_name,
            )
            return

        assets = [
            asset
            for asset in release.get("assets", [])
            if isinstance(asset, dict)
            and asset.get("name")
            and asset.get("download_url")
        ]

        if not assets:
            await show_github_error(
                callback,
                "This release has no downloadable assets.",
                full_name,
            )
            return

        await _render_release_assets(
            callback=callback,
            full_name=full_name,
            tag=tag,
            assets=assets,
            release_token=token,
            page=page,
        )

    except GitHubRateLimitError:
        await show_github_error(
            callback,
            "⏳ GitHub rate limit reached. Please try again later.",
            full_name,
        )
    except GitHubError:
        logger.exception("Failed to change release assets page")
        await show_github_error(
            callback,
            "❌ Failed to retrieve release assets.",
            full_name,
        )
    except Exception:
        logger.exception("Unexpected error while changing assets page")
        await show_github_error(
            callback,
            "❌ An unexpected error occurred.",
            full_name,
        )

@router.callback_query(F.data.startswith("assets_info:"))
async def assets_page_info(callback: CallbackQuery):
    if not callback.data:
        await callback.answer()
        return

    try:
        _, token, page_text = callback.data.split(":", 2)
        page = int(page_text)
    except ValueError:
        await callback.answer("Invalid page.", show_alert=True)
        return

    if page < 0 or get_release(token) is None:
        await callback.answer("Invalid or expired page.", show_alert=True)
        return

    await callback.answer(f"Page {page + 1}")
