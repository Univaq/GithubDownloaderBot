"""Telegram callbacks for README discovery and download flows."""

import html
import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from keyboards.inline import download_completion_keyboard

from handlers.releases import (
    back_to_repository_keyboard,
    readme_files_keyboard,
    show_readme_format_options,
)
from services.callback_cache import get_readme, get_repository
from services.github import (
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubService,
)

logger = logging.getLogger(__name__)
router = Router(name="readme")


@router.callback_query(F.data.startswith("choice:readme:"))
async def choose_readme(callback: CallbackQuery):
    if not callback.data or not callback.message:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    token = callback.data.removeprefix("choice:readme:")
    full_name = get_repository(token)

    if not full_name or full_name.count("/") != 1:
        await callback.answer("Please start a new search and try again 🔎", show_alert=True)
        return

    await callback.answer()
    message = callback.message

    try:
        owner, repo = full_name.split("/", 1)

        async with GitHubService() as github:
            files = await github.get_readme_files(owner, repo)

        if not files:
            await message.edit_text(
                "No README files found in this repository.",
                reply_markup=back_to_repository_keyboard(full_name),
            )
            return

        if len(files) == 1:
            await show_readme_format_options(
                message,
                full_name,
                files[0],
            )
            return

        builder = InlineKeyboardBuilder()

        for index, file in enumerate(files[:20]):
            builder.button(
                text=f"📄 {file['name']}"[:60],
                callback_data=f"readme_lang:{token}:{index}",
            )

        builder.button(
            text="📦 Back to Repository",
            callback_data=f"back:repo:{token}",
        )
        builder.adjust(1)

        await message.edit_text(
            f"📄 Choose a README file\n"
            f"Repository: {html.escape(full_name)}\n\n"
            f"Found {len(files)} README files.",
            reply_markup=readme_files_keyboard(
                token=token,
                files=files,
                page=0,
            ),
            parse_mode="HTML",
        )

    except GitHubNotFoundError:
        await message.edit_text(
            "We couldn’t find this repository or its README files.",
            reply_markup=back_to_repository_keyboard(full_name),
        )

    except GitHubRateLimitError:
        await message.edit_text(
            "GitHub’s request limit has been reached. Please try again in a little while.",
            reply_markup=back_to_repository_keyboard(full_name),
        )

    except GitHubError:
        logger.exception("Failed to retrieve README files")
        await message.edit_text(
            "We couldn’t load the README files. Please try again.",
            reply_markup=back_to_repository_keyboard(full_name),
        )

    except Exception:
        logger.exception("Unexpected error while finding README files")
        await message.edit_text(
            "Something unexpected happened. Please try again.",
            reply_markup=back_to_repository_keyboard(full_name),
        )

@router.callback_query(F.data.startswith("readme_page:"))
async def change_readme_page(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    try:
        _, token, page_text = callback.data.split(":", 2)
        page = int(page_text)
        if page < 0:
            raise ValueError
    except ValueError:
        await callback.answer("That page number isn’t valid.", show_alert=True)
        return

    full_name = get_repository(token)

    if not full_name or full_name.count("/") != 1:
        await callback.answer(
            "This selection has expired. Please search again 🔎",
            show_alert=True,
        )
        return

    await callback.answer()

    try:
        owner, repo = full_name.split("/", 1)

        async with GitHubService() as github:
            files = await github.get_readme_files(owner, repo)

        if not files:
            await callback.message.edit_text(
                "No README files found in this repository.",
                reply_markup=back_to_repository_keyboard(full_name),
            )
            return

        await callback.message.edit_text(
            f"📄 Choose a README file\n"
            f"Repository: {html.escape(full_name)}\n\n"
            f"Found {len(files)} README files.",
            reply_markup=readme_files_keyboard(
                token=token,
                files=files,
                page=page,
            ),
            parse_mode="HTML",
        )

    except GitHubRateLimitError:
        await callback.message.edit_text(
            "GitHub’s request limit has been reached. Please try again in a little while.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except GitHubError:
        logger.exception("Failed to load README page")
        await callback.message.edit_text(
            "We couldn’t load the README files. Please try again.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except Exception:
        logger.exception("Unexpected error while changing README page")
        await callback.message.edit_text(
            "Something unexpected happened. Please try again.",
            reply_markup=back_to_repository_keyboard(full_name),
        )

@router.callback_query(F.data.startswith("readme_info:"))
async def readme_page_info(callback: CallbackQuery):
    if not callback.data:
        await callback.answer()
        return

    try:
        _, token, page_text = callback.data.split(":", 2)
        page = int(page_text)
    except ValueError:
        await callback.answer("That page number isn’t valid.", show_alert=True)
        return

    if page < 0 or get_repository(token) is None:
        await callback.answer(
            "This page is no longer available. Please open the list again.",
            show_alert=True,
        )
        return

    await callback.answer(f"Page {page + 1}")

@router.callback_query(F.data.startswith("readme_lang:"))
async def choose_readme_language(callback: CallbackQuery):
    if not callback.data or not callback.message:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    try:
        _, token, index_text = callback.data.split(":", 2)
        index = int(index_text)
    except ValueError:
        await callback.answer("That selection isn’t valid.", show_alert=True)
        return

    full_name = get_repository(token)

    if not full_name or full_name.count("/") != 1:
        await callback.answer("Please start a new search and try again 🔎", show_alert=True)
        return

    await callback.answer()
    message = callback.message

    try:
        await message.edit_text("⏳ Loading README…")

        owner, repo = full_name.split("/", 1)

        async with GitHubService() as github:
            files = await github.get_readme_files(owner, repo)

        if index < 0 or index >= min(len(files), 20):
            await message.edit_text(
                "README selection is no longer available.",
                reply_markup=back_to_repository_keyboard(full_name),
            )
            return

        await show_readme_format_options(
            message,
            full_name,
            files[index],
        )

    except GitHubNotFoundError:
        await message.edit_text(
            "We couldn’t find this repository or its README files.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except GitHubRateLimitError:
        await message.edit_text(
            "GitHub’s request limit has been reached. Please try again in a little while.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except GitHubError:
        logger.exception("Failed to retrieve selected README")
        await message.edit_text(
            "We couldn’t load the README content. Please try again.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except Exception:
        logger.exception("Unexpected error while selecting README")
        await message.edit_text(
            "Something unexpected happened. Please try again.",
            reply_markup=back_to_repository_keyboard(full_name),
        )

@router.callback_query(F.data.startswith("readme_fmt:"))
async def choose_readme_format(callback: CallbackQuery):
    if not callback.data or not callback.message:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    try:
        _, file_format, readme_id, index_text = callback.data.split(":", 3)
        index = int(index_text)
    except ValueError:
        await callback.answer("That selection isn’t valid.", show_alert=True)
        return

    if file_format != "md" or index != 0:
        await callback.answer("That selection isn’t valid.", show_alert=True)
        return

    info = get_readme(readme_id)

    if not info:
        await callback.answer(
            "Please select the README again.",
            show_alert=True,
        )
        return

    full_name, path, _ = info

    if full_name.count("/") != 1:
        await callback.answer("That repository selection doesn’t look right.", show_alert=True)
        return

    await callback.answer()
    message = callback.message

    try:
        owner, repo = full_name.split("/", 1)

        await message.edit_text("⏳ Preparing your README…")

        async with GitHubService() as github:
            content = await github.get_readme_content(
                owner,
                repo,
                path,
            )

        filename = path.rsplit("/", 1)[-1] or "README.md"

        document = BufferedInputFile(
            content.encode("utf-8"),
            filename=filename,
        )

        await message.answer_document(
            document=document,
            caption=f"README for {full_name}",
        )
        # Remove the temporary status message only after the document was
        # sent successfully, then place the completion prompt at the end.
        await message.delete()
        await message.answer(
            "✅ README is ready! 📄 Choose what you’d like to do next.",
            reply_markup=download_completion_keyboard(
                full_name,
                readme=True,
            ),
        )

    except GitHubNotFoundError:
        await message.edit_text(
            "We couldn’t find this repository or README file.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except GitHubRateLimitError:
        await message.edit_text(
            "GitHub’s request limit has been reached. Please try again in a little while.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except GitHubError:
        logger.exception("Failed to download README")
        await message.edit_text(
            "We couldn’t download the README. Please try again.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except Exception:
        logger.exception("Unexpected error while downloading README")
        await message.edit_text(
            "Something unexpected happened. Please try again.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
