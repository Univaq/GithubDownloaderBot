
import logging
import re
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards.inline import (
    repository_keyboard,
    repository_action_keyboard,
)
from keyboards.main import search_mode_keyboard
from repositories.jobs import add_search_history, is_favorite
from services.callback_cache import (
    get_search_results,
    store_search_results,
)
from services.repository_presenter import format_repository_card
from services.github import (
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubService,
)


logger = logging.getLogger(__name__)
router = Router(name="search")

SEARCH_LIMIT = 5
SEARCH_WINDOW_SECONDS = 60
MAX_QUERY_LENGTH = 200

_user_searches: dict[int, deque[float]] = defaultdict(deque)

GITHUB_URL_PATTERN = re.compile(
    r"https?://github\.com/[^\s<>]+|"
    r"(?:www\.)?github\.com/[^\s<>]+",
    re.IGNORECASE,
)


def is_search_allowed(user_id: int) -> bool:
    now = time.monotonic()
    timestamps = _user_searches[user_id]

    while timestamps and now - timestamps[0] >= SEARCH_WINDOW_SECONDS:
        timestamps.popleft()

    if len(timestamps) >= SEARCH_LIMIT:
        return False

    timestamps.append(now)
    return True


def extract_github_repository(text: str) -> tuple[str, str] | None:
    """Extract and validate a GitHub repository URL."""
    match = GITHUB_URL_PATTERN.search(text)

    if not match:
        return None

    raw_url = match.group(0).rstrip(".,;!?)\"']}")

    if not raw_url.lower().startswith(("http://", "https://")):
        raw_url = f"https://{raw_url}"

    try:
        parsed = urlparse(raw_url)

        if parsed.scheme not in {"http", "https"}:
            return None

        if parsed.hostname not in {"github.com", "www.github.com"}:
            return None

        if parsed.port not in (None, 80, 443):
            return None

        if parsed.username is not None or parsed.password is not None:
            return None

    except ValueError:
        return None

    parts = parsed.path.strip("/").split("/")

    # GitHub repository links may point to a branch, directory, file, or tab,
    # e.g. /owner/repo/tree/feature/my-branch. The repository identity is
    # always the first two path segments; the rest is repository navigation.
    if len(parts) < 2:
        return None

    owner, repo = parts[:2]

    if repo.endswith(".git"):
        repo = repo[:-4]

    if not owner or not repo:
        return None

    if not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?",
        owner,
    ):
        return None

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        return None

    if repo in {".", ".."} or repo.endswith("."):
        return None

    return owner, repo


async def update_search_message(
    message: Message,
    text: str,
    *,
    edit: bool,
    reply_markup=None,
    parse_mode: str | None = None,
) -> Message | None:
    """Edit the existing bot message, or send a reply for direct searches."""
    if not edit:
        return await message.answer(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )

    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TelegramBadRequest as exc:
        error_text = str(exc).lower()
        if "message is not modified" in error_text:
            return message

        logger.warning("Could not edit search message; sending a replacement: %s", exc)
        try:
            return await message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except Exception:
            logger.exception("Could not send replacement search message")
            return None

    return message


async def search_from_saved_prompt(
    message: Message,
    state: FSMContext,
    query: str,
) -> None:
    """Reuse the existing search prompt instead of deleting it."""
    data = await state.get_data()
    chat_id = data.get("search_prompt_chat_id")
    message_id = data.get("search_prompt_message_id")

    # Remove the user's query message so the chat only shows the search results.
    try:
        await message.delete()
    except TelegramBadRequest as exc:
        logger.debug("Could not delete the user's search query: %s", exc)

    await state.clear()

    user_id = message.from_user.id if message.from_user else None
    status_message: Message | None = None

    if chat_id is not None and message_id is not None:
        try:
            status_message = await message.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="🔎 Searching GitHub…",
            )
        except TelegramBadRequest as exc:
            logger.warning(
                "Could not edit saved search prompt; sending a status message: %s",
                exc,
            )

    if status_message is None:
        try:
            status_message = await message.answer(
                "🔎 Searching GitHub…"
            )
        except Exception:
            logger.exception("Could not send search status message")
            return

    await perform_repository_search(
        status_message,
        query,
        user_id=user_id,
        edit=True,
        status_already_shown=True,
    )


async def perform_repository_search(
    message: Message,
    query: str,
    user_id: int | None = None,
    edit: bool = False,
    status_already_shown: bool = False,
) -> None:
    query = query.strip()

    if not query:
        await update_search_message(
            message,
            "Enter a repository name or a search query to get started.",
            edit=edit,
        )
        return

    if len(query) > MAX_QUERY_LENGTH:
        await update_search_message(
            message,
            (
                "Your search query is too long. "
                f"Maximum length: {MAX_QUERY_LENGTH} characters."
            ),
            edit=edit,
        )
        return

    actual_user_id = (
        user_id
        if user_id is not None
        else message.from_user.id
        if message.from_user
        else None
    )

    if actual_user_id is None:
        await update_search_message(
            message,
            "We couldn’t identify your account. Please try again.",
            edit=edit,
        )
        return

    if not is_search_allowed(actual_user_id):
        await update_search_message(
            message,
            (
                "You’ve reached the search limit. "
                "Please wait a minute before searching again."
            ),
            edit=edit,
        )
        return

    await add_search_history(actual_user_id, query)

    status_message = message

    if not status_already_shown:
        if edit:
            try:
                await status_message.edit_text(
                    "🔎 Searching GitHub…"
                )
            except TelegramBadRequest as exc:
                logger.warning("Could not update search status: %s", exc)
        else:
            status_message = await message.answer(
                "🔎 Searching GitHub…"
            )

    try:
        repository_info = extract_github_repository(query)

        # Accept owner/repository as an exact lookup as well as a full URL.
        if repository_info is None:
            plain_repo = query.strip().strip("/")
            if re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9_.-]+",
                plain_repo,
            ):
                owner_part, repo_part = plain_repo.split("/", 1)
                if repo_part not in {".", ".."} and not repo_part.endswith("."):
                    repository_info = (owner_part, repo_part)

        async with GitHubService() as github:
            if repository_info:
                owner, repo_name = repository_info
                repository = await github.get_repository(owner, repo_name)

                favorite_status = await is_favorite(
                    actual_user_id,
                    repository["full_name"],
                )

                await status_message.edit_text(
                    format_repository_card(repository["full_name"], repository),
                    reply_markup=repository_action_keyboard(
                        repository["full_name"],
                        is_favorite=favorite_status,
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                return

            # Fetch at most two API pages, with ten repositories per page.
            # GitHub's default best-match ranking is more useful for names
            # such as "Pattng" than sorting every query by star count.
            # Search repository names first. Generic GitHub search can bury
            # a small/exact project name under README and description matches.
            repositories = await github.search_repositories(
                f"{query} in:name",
                per_page=10,
                max_results=20,
            )

            if len(repositories) < 20:
                broad_results = await github.search_repositories(
                    query,
                    per_page=10,
                    max_results=20,
                )
                seen = {item["full_name"].casefold() for item in repositories}
                for item in broad_results:
                    key = item["full_name"].casefold()
                    if key not in seen:
                        repositories.append(item)
                        seen.add(key)
                    if len(repositories) >= 20:
                        break

        if not repositories:
            await status_message.edit_text("No repositories found. Try another name or keyword.")
            return

        search_token = store_search_results(repositories)

        await status_message.edit_text(
            "📚 Here are the matching repositories. Choose one to continue:",
            reply_markup=repository_keyboard(
                repositories,
                search_token,
                page=0,
            ),
        )

    except GitHubNotFoundError:
        await status_message.edit_text(
            "We couldn’t find that GitHub repository. Check the name or link and try again."
        )

    except GitHubRateLimitError:
        await status_message.edit_text(
            "⏳ GitHub’s request limit has been reached. Please try again in a little while."
        )

    except GitHubError:
        logger.exception("GitHub repository lookup failed")
        await status_message.edit_text(
            "We couldn’t retrieve data from GitHub. Please try again."
        )

    except TelegramBadRequest:
        logger.exception("Telegram rejected a search message edit")

    except Exception:
        logger.exception("Unexpected repository lookup error")
        try:
            await status_message.edit_text(
                "Something unexpected happened. Please try again in a moment."
            )
        except TelegramBadRequest:
            logger.exception("Could not display the search error message")


@router.message(Command("repo"))
async def search_command(
    message: Message,
    state: FSMContext,
) -> None:
    query = (
        message.text.partition(" ")[2].strip()
        if message.text
        else ""
    )

    if not query:
        await state.clear()
        await state.set_state("waiting_for_repository_query")
        prompt = await message.answer(
            "🔎 Search GitHub by repository name, keywords, or a repository link.",
            reply_markup=search_mode_keyboard(),
        )
        await state.update_data(
            search_prompt_chat_id=prompt.chat.id,
            search_prompt_message_id=prompt.message_id,
        )
        return

    await state.clear()
    await perform_repository_search(message, query)


@router.message(
    StateFilter("waiting_for_repository_query"),
    F.text.regexp(r"(?i)(?:https?://)?(?:www\.)?github\.com/"),
)
async def github_link_during_search(
    message: Message,
    state: FSMContext,
) -> None:
    await search_from_saved_prompt(
        message,
        state,
        message.text or "",
    )


@router.message(
    StateFilter("waiting_for_repository_query"),
    F.text,
)
async def search_from_text(
    message: Message,
    state: FSMContext,
) -> None:
    query = (message.text or "").strip()

    if not query:
        await message.answer(
            "Enter a repository name or a search query to get started."
        )
        return

    await search_from_saved_prompt(message, state, query)


@router.message(
    F.text.regexp(r"(?i)(?:https?://)?(?:www\.)?github\.com/"),
)
async def automatic_github_link_handler(
    message: Message,
    state: FSMContext,
) -> None:
    # If the user sends a GitHub URL while searching, reuse that prompt.
    current_state = await state.get_state()

    if current_state == "waiting_for_repository_query":
        await search_from_saved_prompt(
            message,
            state,
            message.text or "",
        )
        return

    await perform_repository_search(
        message,
        message.text or "",
    )


@router.callback_query(F.data == "search:again")
async def search_again(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        await callback.answer("This message is no longer available. Please open the menu again.", show_alert=True)
        return

    await callback.answer()
    await state.set_state("waiting_for_repository_query")
    await state.update_data(
        search_prompt_chat_id=callback.message.chat.id,
        search_prompt_message_id=callback.message.message_id,
    )

    try:
        await callback.message.edit_text(
            "🔎 Send a repository name, a search query, or a GitHub link to get started.",
            reply_markup=search_mode_keyboard(),
        )
    except TelegramBadRequest as exc:
        logger.warning("Could not display the search-again prompt: %s", exc)


@router.callback_query(F.data.startswith("search_page:"))
async def change_search_page(callback: CallbackQuery) -> None:
    if not callback.data or callback.message is None:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    try:
        _, search_token, page_text = callback.data.split(":", 2)
        page = int(page_text)
    except (ValueError, TypeError):
        await callback.answer("That page selection isn’t valid.", show_alert=True)
        return

    if page < 0:
        await callback.answer("That page number isn’t valid.", show_alert=True)
        return

    repositories = get_search_results(search_token)

    if repositories is None:
        await callback.answer(
            "These search results have expired. Please start a new search and try again 🔎",
            show_alert=True,
        )
        return

    total_pages = max(1, (len(repositories) + 9) // 10)
    if page >= total_pages:
        await callback.answer("That page doesn’t exist. Please choose another page.", show_alert=True)
        return

    await callback.answer()

    try:
        await callback.message.edit_text(
            "📚 Here are the matching repositories. Choose one to continue:",
            reply_markup=repository_keyboard(
                repositories,
                search_token,
                page=page,
            ),
        )
    except TelegramBadRequest as exc:
        logger.warning("Could not change search results page: %s", exc)


@router.callback_query(F.data.startswith("search_info:"))
async def search_page_info(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    try:
        _, search_token, page_text = callback.data.split(":", 2)
        page = int(page_text)
    except (ValueError, TypeError):
        await callback.answer("That page selection isn’t valid.", show_alert=True)
        return

    repositories = get_search_results(search_token)

    if repositories is None:
        await callback.answer(
            "These search results have expired. Please start a new search and try again 🔎",
            show_alert=True,
        )
        return

    total_pages = max(1, (len(repositories) + 9) // 10)

    if page < 0 or page >= total_pages:
        await callback.answer("That page number isn’t valid.", show_alert=True)
        return

    await callback.answer(f"Page {page + 1}/{total_pages}")


@router.callback_query(F.data.startswith("back:search:"))
async def back_to_search_results(
    callback: CallbackQuery,
) -> None:
    if not callback.data or callback.message is None:
        await callback.answer("That action didn’t work. Please try again.", show_alert=True)
        return

    search_token = callback.data.removeprefix("back:search:")
    repositories = get_search_results(search_token)

    if repositories is None:
        await callback.answer(
            "These search results have expired. Please start a new search and try again 🔎",
            show_alert=True,
        )
        return

    await callback.answer()

    try:
        await callback.message.edit_text(
            "📚 Here are the matching repositories. Choose one to continue:",
            reply_markup=repository_keyboard(
                repositories,
                search_token,
                page=0,
            ),
        )
    except TelegramBadRequest as exc:
        logger.warning("Could not restore search results: %s", exc)
