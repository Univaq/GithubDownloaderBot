
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(
    name: str,
    default: int,
    minimum: int = 1,
) -> int:
    value = os.getenv(name, str(default)).strip()

    try:
        number = int(value)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} must be a valid integer."
        ) from exc

    if number < minimum:
        raise RuntimeError(
            f"{name} must be at least {minimum}."
        )

    return number


@dataclass(frozen=True)
class Settings:
    bot_token: str
    github_token: str | None
    use_local_bot_api: bool
    local_bot_api_url: str
    database_path: Path
    downloads_dir: Path
    max_concurrent_jobs: int
    max_queue_size: int
    max_download_bytes: int
    use_sqlite_worker_gateway: bool

    @classmethod
    def load(cls) -> "Settings":
        bot_token = os.getenv("BOT_TOKEN", "").strip()

        if not bot_token:
            raise RuntimeError(
                "BOT_TOKEN is not configured. Check your .env file."
            )

        use_local_bot_api = env_bool(
            "USE_LOCAL_BOT_API",
            False,
        )

        local_bot_api_url = os.getenv(
            "LOCAL_BOT_API_URL",
            "http://127.0.0.1:8081",
        ).strip().rstrip("/")

        if not local_bot_api_url:
            raise RuntimeError(
                "LOCAL_BOT_API_URL cannot be empty."
            )

        parsed_api_url = urlparse(local_bot_api_url)

        if (
            parsed_api_url.scheme not in {"http", "https"}
            or not parsed_api_url.hostname
            or parsed_api_url.username is not None
            or parsed_api_url.password is not None
            or parsed_api_url.query
            or parsed_api_url.fragment
        ):
            raise RuntimeError(
                "LOCAL_BOT_API_URL must be a valid HTTP(S) base URL."
            )

        max_download_mb = env_int(
            "MAX_DOWNLOAD_MB",
            default=49,
        )

        return cls(
            bot_token=bot_token,
            github_token=os.getenv(
                "GITHUB_TOKEN",
                "",
            ).strip() or None,
            use_local_bot_api=use_local_bot_api,
            local_bot_api_url=local_bot_api_url,
            database_path=BASE_DIR / "data" / "jobs.db",
            downloads_dir=BASE_DIR / "downloads",
            max_concurrent_jobs=env_int(
                "MAX_CONCURRENT_JOBS",
                default=1,
            ),
            max_queue_size=env_int(
                "MAX_QUEUE_SIZE",
                default=100,
            ),
            max_download_bytes=max_download_mb * 1024 * 1024,
            use_sqlite_worker_gateway=env_bool(
                "USE_SQLITE_WORKER_GATEWAY",
                False,
            ),
        )


settings = Settings.load()

settings.database_path.parent.mkdir(
    parents=True,
    exist_ok=True,
)

settings.downloads_dir.mkdir(
    parents=True,
    exist_ok=True,
)
