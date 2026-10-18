
import html
import logging
import re
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards.inline import (
    repository_action_keyboard,
    releases_keyboard,
)
from services.repository_presenter import format_repository_card, format_repository_date
from services.readme_renderer import (
    clean_readme_content,
    format_markdown_inline,
    split_readme_preview,
)
from services.callback_cache import (
    get_repository,
    get_release,
    store_readme,
    get_readme,
    store_repository,
)
from services.github import (
    GitHubService,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
)
from repositories.jobs import (
    create_selection,
    enqueue_selection,
    is_favorite,
)

logger = logging.getLogger(__name__)
router = Router(name="releases")


def back_to_repository_keyboard(full_name: str):
    repository_id = store_repository(full_name)
    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬅️ Back to Repository",
        callback_data=f"back:repo:{repository_id}",
    )

    builder.adjust(1)
    return builder.as_markup()


async def show_github_error(
    callback: CallbackQuery,
    error_message: str,
    full_name: str | None = None,
) -> None:
    if callback.message is not None:
        keyboard = (
            back_to_repository_keyboard(full_name)
            if full_name
            else None
        )

        await callback.message.edit_text(
            error_message,
            reply_markup=keyboard,
        )
    else:
        await callback.answer(error_message, show_alert=True)


def readme_preview_keyboard(
    readme_id: str,
    full_name: str,
):
    repository_id = store_repository(full_name)
    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬇️ Download README",
        callback_data=f"readme_fmt:md:{readme_id}:0",
    )
    builder.button(
        text="⬅️ Back to Repository",
        callback_data=f"back:repo:{repository_id}",
    )
    builder.adjust(1)

    return builder.as_markup()


@router.callback_query(F.data.startswith("repo:"))
async def select_repository(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("Invalid request.", show_alert=True)
        return

    token = callback.data.removeprefix("repo:")
    full_name = get_repository(token)

    if full_name is None or full_name.count("/") != 1:
        await callback.answer(
            "This selection has expired. Please search again.",
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
            f"📁 <b>{html.escape(full_name)}</b>\n\n"
            "⚠️ GitHub rate limit reached. "
            "Repository details are temporarily unavailable.\n\n"
            "<b>Choose an action below</b>"
        )

    except GitHubError:
        logger.exception(
            "Failed to retrieve repository details: %s",
            full_name,
        )
        message_text = (
            f"📁 <b>{html.escape(full_name)}</b>\n\n"
            "⚠️ Repository details could not be loaded.\n\n"
            "<b>Choose an action below</b>"
        )

    except Exception:
        logger.exception(
            "Unexpected error loading repository details: %s",
            full_name,
        )
        message_text = (
            f"📁 <b>{html.escape(full_name)}</b>\n\n"
            "⚠️ An unexpected error occurred while loading details.\n\n"
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


@router.callback_query(F.data.startswith("choice:src:"))
async def choose_source_code(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("Invalid request.", show_alert=True)
        return

    token = callback.data.removeprefix("choice:src:")
    full_name = get_repository(token)

    if full_name is None:
        await callback.answer(
            "This selection has expired. Please search again.",
            show_alert=True,
        )
        return

    await callback.answer()
    await send_source_selection(callback, full_name)


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


async def send_source_selection(
    callback: CallbackQuery,
    full_name: str,
    tag: str | None = None,
):
    if callback.message is None or full_name.count("/") != 1:
        return

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            repository = await github.get_repository(owner, repo)
            ref = tag or repository["default_branch"]
            source_url = github.get_source_url(owner, repo, ref)

    except GitHubNotFoundError:
        await show_github_error(
            callback,
            "❌ Repository or requested version not found.",
            full_name,
        )
        return

    except GitHubRateLimitError:
        await show_github_error(
            callback,
            "⏳ GitHub rate limit reached. Please try again later.",
            full_name,
        )
        return

    except GitHubError:
        logger.exception("Failed to retrieve repository source")
        await show_github_error(
            callback,
            "❌ Failed to retrieve repository source code.",
            full_name,
        )
        return

    except Exception:
        logger.exception("Unexpected error while retrieving source")
        await show_github_error(
            callback,
            "❌ An unexpected error occurred. Please try again later.",
            full_name,
        )
        return

    selection_id = await create_selection(
        user_id=callback.from_user.id,
        chat_id=callback.message.chat.id,
        download_url=source_url,
        file_name=f"{repo}-{ref}.zip",
        job_type="source",
    )

    repository_id = store_repository(full_name)

    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬇️ Download Source Code",
        callback_data=f"get:{selection_id}",
    )
    builder.button(
        text="⬅️ Back to Repository",
        callback_data=f"back:repo:{repository_id}",
    )
    builder.adjust(1)

    await callback.message.edit_text(
        f"📦 <b>Source Code</b>\n"
        f"Repository: <code>{full_name}</code>\n"
        f"Version: <code>{ref}</code>\n\n"
        "Press the button below to add the download to the queue.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


def source_selection_keyboard(selection_id: str, repository_id: str):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬇️ Download Source Code",
        callback_data=f"get:{selection_id}",
    )
    builder.button(
        text="⬅️ Back to Repository",
        callback_data=f"back:repo:{repository_id}",
    )

    builder.adjust(1)
    return builder.as_markup()


ASSETS_PER_PAGE = 10


async def _render_release_assets(
    callback: CallbackQuery,
    full_name: str,
    tag: str,
    assets: list[dict],
    release_token: str,
    page: int = 0,
) -> None:
    if callback.message is None:
        return

    total_pages = max(
        1,
        (len(assets) + ASSETS_PER_PAGE - 1) // ASSETS_PER_PAGE,
    )
    page = max(0, min(page, total_pages - 1))

    start = page * ASSETS_PER_PAGE
    page_assets = assets[start : start + ASSETS_PER_PAGE]

    repository_id = store_repository(full_name)
    builder = InlineKeyboardBuilder()

    for asset in page_assets:
        if not isinstance(asset, dict):
            continue

        download_url = asset.get("download_url")
        file_name = asset.get("name")

        if not download_url or not file_name:
            continue

        selection_id = await create_selection(
            user_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
            download_url=download_url,
            file_name=file_name,
            job_type="asset",
        )

        size_mb = (asset.get("size") or 0) / (1024 * 1024)

        builder.button(
            text=f"⬇️ {file_name} ({size_mb:.1f} MB)"[:60],
            callback_data=f"get:{selection_id}",
        )

    nav_count = 0

    if total_pages > 1:
        if page > 0:
            builder.button(
                text="⬅️ Previous",
                callback_data=f"assets_page:{release_token}:{page - 1}",
            )
            nav_count += 1

        builder.button(
            text=f"📄 {page + 1}/{total_pages}",
            callback_data=f"assets_info:{release_token}:{page}",
        )
        nav_count += 1

        if page < total_pages - 1:
            builder.button(
                text="Next ➡️",
                callback_data=f"assets_page:{release_token}:{page + 1}",
            )
            nav_count += 1

    builder.button(
        text="⬅️ Back to Releases",
        callback_data=f"back:releases:{repository_id}",
    )

    if nav_count:
        builder.adjust(*([1] * len(page_assets)), nav_count, 1)
    else:
        builder.adjust(1)

    text = (
        f"🚀 <b>Release Assets</b>\n"
        f"Repository: <code>{html.escape(full_name)}</code>\n"
        f"Version: <code>{html.escape(tag)}</code>\n\n"
        f"Files: {len(assets)}\n"
        f"Select a file to download:"
    )

    if total_pages > 1:
        text += f"\nPage {page + 1} of {total_pages}"

    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
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


def readme_files_keyboard(
    token: str,
    files: list[dict],
    page: int = 0,
):
    builder = InlineKeyboardBuilder()

    total_pages = max(
        1,
        (len(files) + README_FILES_PER_PAGE - 1)
        // README_FILES_PER_PAGE,
    )
    page = max(0, min(page, total_pages - 1))

    start = page * README_FILES_PER_PAGE
    current_files = files[start:start + README_FILES_PER_PAGE]

    for index, file in enumerate(current_files, start=start):
        name = file.get("name") or file.get("path") or "README"
        builder.button(
            text=f"📄 {name}"[:60],
            callback_data=f"readme_lang:{token}:{index}",
        )

    nav_count = 0

    if total_pages > 1:
        if page > 0:
            builder.button(
                text="⬅️ Previous",
                callback_data=f"readme_page:{token}:{page - 1}",
            )
            nav_count += 1

        builder.button(
            text=f"📄 Page {page + 1}/{total_pages}",
            callback_data=f"readme_info:{token}:{page}",
        )
        nav_count += 1

        if page < total_pages - 1:
            builder.button(
                text="Next ➡️",
                callback_data=f"readme_page:{token}:{page + 1}",
            )
            nav_count += 1

    builder.button(
        text="⬅️ Back to Repository",
        callback_data=f"back:repo:{token}",
    )

    if nav_count:
        builder.adjust(
            *([1] * len(current_files)),
            nav_count,
            1,
        )
    else:
        builder.adjust(1)

    return builder.as_markup()

async def show_readme_format_options(
    message,
    full_name: str,
    readme_file: dict,
):
    owner, repo = full_name.split("/", 1)
    path = readme_file["path"]

    readme_id = store_readme(
        full_name,
        path,
        readme_file.get("download_url"),
    )

    async with GitHubService() as github:
        content = await github.get_readme_content(
            owner,
            repo,
            path,
        )

    content = clean_readme_content(content)

    preview_limit = 500
    preview_content = content[:preview_limit]

    if len(content) > preview_limit:
        last_newline = preview_content.rfind("\n")
        last_space = preview_content.rfind(" ")
        cut_position = max(last_newline, last_space)

        if cut_position > 300:
            preview_content = preview_content[:cut_position]

        preview_content += (
            "\n\n... Preview shortened. "
            "Download the README to read the full file."
        )

    preview_html = split_readme_preview(preview_content)
    preview_text = "\n\n".join(preview_html)

    keyboard = readme_preview_keyboard(
        readme_id,
        full_name,
    )

    text = (
        f"📄 <b>README Preview</b> "
        f"(<code>{html.escape(readme_file['name'])}</code>)\n\n"
        f"{preview_text}"
    )

    await message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

@router.callback_query(F.data.startswith("back:repo:"))
async def back_to_repository(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("Invalid request.", show_alert=True)
        return

    token = callback.data.removeprefix("back:repo:")
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
            repository = await github.get_repository(owner, repo)

        message_text = format_repository_card(full_name, repository)

    except GitHubError:
        logger.exception(
            "Failed to load repository details: %s",
            full_name,
        )
        message_text = (
            f"📦 <b>{html.escape(full_name)}</b>\n\n"
            "Repository details are temporarily unavailable.\n\n"
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
