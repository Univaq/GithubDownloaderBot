
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Protocol
from pathlib import Path
from urllib.parse import unquote, urlparse

import aiofiles
from aiogram import Bot
from aiogram.types.input_file import InputFile

from config import settings
from keyboards.inline import download_completion_keyboard
from repositories.jobs import claim_next_job, fail_job, finish_job
from services.downloader import download_to_temp, delete_temp_file


logger = logging.getLogger(__name__)

UploadProgress = Callable[[int], Awaitable[None]]


class WorkerJobGateway(Protocol):
    """Persistence operations required by worker orchestration."""

    async def claim_next_payload(self) -> dict[str, object] | None: ...

    async def mark_completed(self, job_id: int) -> bool: ...

    async def mark_failed(self, job_id: int, error: str) -> bool: ...


class LegacyWorkerPersistence:
    """Adapt the existing repository functions to the worker gateway contract."""

    async def claim_next_payload(self) -> dict[str, object] | None:
        return await claim_next_job()

    async def mark_completed(self, job_id: int) -> bool:
        return await finish_job(job_id)

    async def mark_failed(self, job_id: int, error: str) -> bool:
        return await fail_job(job_id, error)


class ProgressInputFile(InputFile):
    def __init__(
        self,
        path: Path,
        filename: str,
        progress_callback: UploadProgress,
        chunk_size: int = 64 * 1024,
    ) -> None:
        super().__init__(
            filename=filename,
            chunk_size=chunk_size,
        )
        self.path = Path(path)
        self.progress_callback = progress_callback

    async def read(self, bot: Bot):
        uploaded = 0

        async with aiofiles.open(self.path, "rb") as file:
            while True:
                chunk = await file.read(self.chunk_size)

                if not chunk:
                    break

                uploaded += len(chunk)

                try:
                    await self.progress_callback(uploaded)
                except Exception:
                    logger.debug(
                        "Upload progress callback failed",
                        exc_info=True,
                    )

                yield chunk


def make_progress_bar(
    percent: float,
    width: int = 16,
) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = round(percent * width / 100)

    return "█" * filled + "░" * (width - filled)


def repository_from_download_url(download_url: str) -> str | None:
    """Infer owner/repository from common GitHub archive and release URLs."""
    try:
        parsed = urlparse(download_url)
    except (TypeError, ValueError):
        return None

    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.strip("/").split("/") if part]

    if host == "api.github.com" and len(parts) >= 4 and parts[0] == "repos":
        owner, repo = parts[1], parts[2]
    elif host in {"github.com", "www.github.com", "codeload.github.com"} and len(parts) >= 2:
        owner, repo = parts[0], parts[1]
    else:
        return None

    if repo.endswith(".git"):
        repo = repo[:-4]

    if not owner or not repo:
        return None

    return f"{owner}/{repo}"


def release_tag_from_download_url(download_url: str) -> str | None:
    """Extract the tag from a GitHub release asset download URL."""
    try:
        parsed = urlparse(download_url)
    except (TypeError, ValueError):
        return None

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if (
        (parsed.hostname or "").lower() in {"github.com", "www.github.com"}
        and len(parts) >= 5
        and parts[2:4] == ["releases", "download"]
    ):
        return unquote(parts[4])

    return None


async def process_download_job(bot: Bot, job: dict) -> None:
    path: Path | None = None
    progress_message = None

    try:
        progress_message = await bot.send_message(
            chat_id=job["chat_id"],
            text=(
                "📥 DOWNLOAD\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "Status: Connecting to GitHub…\n"
                f"{make_progress_bar(0)} 0.0%\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "Downloaded: 0.00 MB\n"
                "Speed: Calculating…\n"
                "Source: GitHub"
            ),
        )

        last_update = 0.0
        last_bytes = 0
        last_time = time.monotonic()
        download_speed = 0.0

        async def on_download_progress(
            downloaded: int,
            total: int | None,
        ) -> None:
            nonlocal last_update
            nonlocal last_bytes
            nonlocal last_time
            nonlocal download_speed

            now = time.monotonic()
            elapsed = now - last_time

            if elapsed >= 1:
                download_speed = (downloaded - last_bytes) / elapsed
                last_bytes = downloaded
                last_time = now

            if now - last_update < 1 and downloaded != total:
                return

            last_update = now

            downloaded_mb = downloaded / (1024 * 1024)
            speed_mb = download_speed / (1024 * 1024)

            percent = 0.0
            total_mb = None

            if total is not None and total > 0:
                percent = min(100.0, downloaded * 100 / total)
                total_mb = total / (1024 * 1024)

            if total_mb is not None:
                size_text = (
                    f"Downloaded: {downloaded_mb:.2f} / "
                    f"{total_mb:.2f} MB"
                )
                progress_text = (
                    f"{make_progress_bar(percent)} {percent:.1f}%"
                )
            else:
                size_text = f"Downloaded: {downloaded_mb:.2f} MB"
                progress_text = "Progress: Receiving data…"

            text = (
                "📥 DOWNLOAD\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "Status: Downloading from GitHub\n"
                f"{progress_text}\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"{size_text}\n"
                f"Speed: {speed_mb:.2f} MB/s\n"
                "Source: GitHub"
            )

            try:
                await progress_message.edit_text(text)
            except Exception:
                logger.debug(
                    "Download progress edit failed",
                    exc_info=True,
                )

        path = await download_to_temp(
            job["repo_url"],
            progress_callback=on_download_progress,
        )

        size = path.stat().st_size
        max_size = settings.max_download_bytes

        if not settings.use_local_bot_api:
            max_size = min(max_size, 49 * 1024 * 1024)

        if size > max_size:
            raise ValueError(
                "File exceeds the configured download limit "
                f"of {max_size / (1024 * 1024):.0f} MB."
            )

        upload_started = time.monotonic()
        last_upload_update = 0.0
        upload_speed = 0.0

        await progress_message.edit_text(
            "📤 UPLOAD\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Status: Preparing your file for Telegram\n"
            f"{make_progress_bar(0)} 0.0%\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"File size: {size / (1024 * 1024):.2f} MB\n"
            "Speed: Calculating…\n"
            "Destination: Telegram"
        )

        async def on_upload_progress(uploaded: int) -> None:
            nonlocal last_upload_update
            nonlocal upload_speed

            now = time.monotonic()
            elapsed = now - upload_started

            if elapsed > 0:
                upload_speed = uploaded / elapsed

            if now - last_upload_update < 1 and uploaded < size:
                return

            last_upload_update = now

            percent = (
                min(100.0, uploaded * 100 / size)
                if size
                else 100.0
            )
            uploaded_mb = uploaded / (1024 * 1024)
            total_mb = size / (1024 * 1024)
            speed_mb = upload_speed / (1024 * 1024)

            text = (
                "📤 UPLOAD\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "Status: Uploading to Telegram\n"
                f"{make_progress_bar(percent)} {percent:.1f}%\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"Transferred: {uploaded_mb:.2f} / {total_mb:.2f} MB\n"
                f"Speed: {speed_mb:.2f} MB/s\n"
                f"Elapsed: {elapsed:.0f}s\n"
                "Destination: Telegram"
            )

            try:
                await progress_message.edit_text(text)
            except Exception:
                logger.debug(
                    "Upload progress edit failed",
                    exc_info=True,
                )

        await bot.send_document(
            chat_id=job["chat_id"],
            document=ProgressInputFile(
                path=path,
                filename=job.get("file_name") or path.name,
                progress_callback=on_upload_progress,
            ),
            caption="Your GitHub file is ready to go!",
        )

        download_url = str(job.get("repo_url") or "")
        full_name = repository_from_download_url(download_url)
        release_tag = release_tag_from_download_url(download_url)
        try:
            await bot.send_message(
                chat_id=job["chat_id"],
                text="✅ Your file is ready! What would you like to do next?",
                reply_markup=download_completion_keyboard(
                    full_name,
                    release_tag=release_tag,
                ),
            )
        except Exception:
            # The file is already delivered; a follow-up prompt failure must
            # not turn a successful download into a failed job.
            logger.exception("Could not send post-download action buttons")

    finally:
        if progress_message is not None:
            try:
                await progress_message.delete()
            except Exception:
                logger.debug(
                    "Could not delete progress message",
                    exc_info=True,
                )

        queue_message_id = job.get("queue_message_id")
        queue_chat_id = job.get("queue_chat_id")

        if (
            queue_message_id is not None
            and queue_chat_id is not None
        ):
            try:
                await bot.delete_message(
                    chat_id=queue_chat_id,
                    message_id=queue_message_id,
                )
            except Exception:
                logger.debug(
                    "Could not delete queue message",
                    exc_info=True,
                )

        if path is not None:
            try:
                await delete_temp_file(path)
            except Exception:
                logger.exception(
                    "Could not delete temporary download file"
                )


async def worker_loop(
    bot: Bot,
    stop_event: asyncio.Event,
    *,
    job_gateway: WorkerJobGateway | None = None,
) -> None:
    """Run the worker through one gateway; legacy persistence remains default."""
    gateway: WorkerJobGateway = (
        job_gateway if job_gateway is not None else LegacyWorkerPersistence()
    )
    while not stop_event.is_set():
        try:
            job = await gateway.claim_next_payload()
        except Exception:
            logger.exception(
                "Could not claim the next download job"
            )

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=2,
                )
            except asyncio.TimeoutError:
                pass

            continue

        if job is None:
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=2,
                )
            except asyncio.TimeoutError:
                pass

            continue

        try:
            await process_download_job(bot, job)

        except Exception as exc:
            logger.exception(
                "Download job %s failed",
                job["id"],
            )

            try:
                marked_failed = await gateway.mark_failed(
                    job["id"],
                    str(exc),
                )

                if not marked_failed:
                    logger.warning(
                        "Job %s could not be marked as failed.",
                        job["id"],
                    )
            except Exception:
                logger.exception(
                    "Could not mark job %s as failed",
                    job["id"],
                )

            try:
                await bot.send_message(
                    chat_id=job["chat_id"],
                    text=(
                        "We couldn’t complete your download. "
                        "Please try again in a moment."
                    ),
                )
            except Exception:
                logger.exception(
                    "Could not notify user about failed job"
                )

        else:
            try:
                marked_completed = await gateway.mark_completed(job["id"])

                if not marked_completed:
                    logger.error(
                        "Job %s was processed, but its status "
                        "could not be changed to completed.",
                        job["id"],
                    )
            except Exception:
                logger.exception(
                    "Job %s was processed, but completion "
                    "could not be saved to the database.",
                    job["id"],
                )
