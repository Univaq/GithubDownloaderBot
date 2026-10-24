
import base64
import binascii
import logging
from urllib.parse import quote, urlparse

import httpx

from config import settings


logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubError(Exception):
    """Base exception for GitHub API errors."""


class GitHubNotFoundError(GitHubError):
    """Repository or resource was not found."""


class GitHubRateLimitError(GitHubError):
    """GitHub API rate limit was reached."""


class GitHubService:
    def __init__(self) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "GitHubFinderBot/1.0",
        }

        if settings.github_token:
            headers["Authorization"] = (
                f"Bearer {settings.github_token}"
            )

        self.client = httpx.AsyncClient(
            base_url=GITHUB_API,
            headers=headers,
            timeout=httpx.Timeout(
                connect=10.0,
                read=20.0,
                write=10.0,
                pool=10.0,
            ),
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    @staticmethod
    def parse_repository_url(
        url: str,
    ) -> tuple[str, str] | None:
        """Parse a GitHub repository URL into owner and repository."""
        try:
            parsed = urlparse(url.strip())

            if parsed.scheme not in {"https", "http"}:
                return None

            if parsed.hostname not in {"github.com", "www.github.com"}:
                return None

            if (
                parsed.username is not None
                or parsed.password is not None
                or parsed.port is not None
            ):
                return None

        except (AttributeError, TypeError, ValueError):
            return None

        parts = [part for part in parsed.path.split("/") if part]

        if len(parts) != 2:
            return None

        owner, repo = parts

        if repo.endswith(".git"):
            repo = repo[:-4]

        if not owner or not repo:
            return None

        if any(char in owner + repo for char in ("?", "#", "\\", "\x00")):
            return None

        return owner, repo

    async def _get(
        self,
        path: str,
        params: dict | None = None,
    ):
        try:
            response = await self.client.get(path, params=params)

        except httpx.TimeoutException as exc:
            logger.warning("GitHub API request timed out: %s", path)
            raise GitHubError(
                "GitHub API request timed out."
            ) from exc

        except httpx.RequestError as exc:
            logger.warning("GitHub API connection failed: %s", path)
            raise GitHubError(
                "Could not connect to GitHub API."
            ) from exc

        if response.status_code == 404:
            raise GitHubNotFoundError(
                "The requested repository or resource was not found."
            )

        if response.status_code in {403, 429}:
            remaining = response.headers.get("X-RateLimit-Remaining")
            retry_after = response.headers.get("Retry-After")

            if (
                remaining == "0"
                or response.status_code == 429
                or retry_after is not None
            ):
                raise GitHubRateLimitError(
                    "GitHub API rate limit exceeded."
                )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "GitHub API returned HTTP %s for %s",
                response.status_code,
                path,
            )
            raise GitHubError(
                f"GitHub API returned HTTP {response.status_code}."
            ) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise GitHubError(
                "GitHub API returned an invalid JSON response."
            ) from exc


    async def search_repositories(
        self,
        query: str,
        per_page: int = 100,
        max_results: int = 20,
    ) -> list[dict]:
        """Fetch repository search results across GitHub API pages."""
        query = query.strip()

        if not query:
            return []

        # GitHub repository search allows up to 100 items per API page.
        per_page = min(max(per_page, 1), 100)
        max_results = min(max(max_results, 1), 1000)

        repositories: list[dict] = []
        page = 1

        while len(repositories) < max_results:
            page_size = min(per_page, max_results - len(repositories))

            data = await self._get(
                "/search/repositories",
                params={
                    "q": query,
                    # Use GitHub default best-match ranking, so exact/name
                    # matches are not buried behind higher-star repositories.
                    "per_page": page_size,
                    "page": page,
                },
            )

            if not isinstance(data, dict):
                raise GitHubError("Invalid repository search response.")

            items = data.get("items", [])

            if not isinstance(items, list):
                raise GitHubError("Invalid repository search results.")

            for item in items:
                if not isinstance(item, dict):
                    continue

                full_name = item.get("full_name")
                html_url = item.get("html_url")

                if not full_name or not html_url:
                    continue

                repositories.append(
                    {
                        "full_name": full_name,
                        "description": item.get("description"),
                        "html_url": html_url,
                        "default_branch": item.get("default_branch") or "main",
                        "stars": item.get("stargazers_count", 0),
                        "language": item.get("language"),
                        "private": item.get("private", False),
                    }
                )

                if len(repositories) >= max_results:
                    break

            if len(items) < page_size or not items:
                break

            page += 1

        return repositories


    async def get_repository(
        self,
        owner: str,
        repo: str,
    ) -> dict:
        data = await self._get(
            f"/repos/{quote(owner, safe='')}/"
            f"{quote(repo, safe='')}"
        )

        if not isinstance(data, dict):
            raise GitHubError("Invalid repository response.")

        try:
            license_data = data.get("license")

            if isinstance(license_data, dict):
                license_name = (
                    license_data.get("spdx_id")
                    or license_data.get("name")
                )
            else:
                license_name = None

            return {
                "full_name": data["full_name"],
                "description": data.get("description"),
                "html_url": data["html_url"],
                "default_branch": data.get("default_branch") or "main",
                "stars": data.get("stargazers_count", 0),
                "forks": data.get("forks_count", 0),
                "open_issues": data.get("open_issues_count", 0),
                "watchers": data.get("subscribers_count", 0),
                "language": data.get("language"),
                "license": license_name,
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "pushed_at": data.get("pushed_at"),
                "private": data.get("private", False),
                "archived": data.get("archived", False),
                "fork": data.get("fork", False),
                "size": data.get("size", 0),
            }

        except KeyError as exc:
            raise GitHubError(
                "Repository response is missing required fields."
            ) from exc

    async def get_repository_from_url(self, url: str) -> dict:
        parsed = self.parse_repository_url(url)

        if parsed is None:
            raise ValueError(
                "Please provide a valid GitHub repository URL, "
                "for example: "
                "https://github.com/owner/repository"
            )

        owner, repo = parsed
        return await self.get_repository(owner, repo)

    async def get_releases(
        self,
        owner: str,
        repo: str,
        per_page: int = 100,
    ) -> list[dict]:
        """Fetch all repository releases, following API pagination."""
        per_page = min(max(per_page, 1), 100)

        path = (
            f"/repos/{quote(owner, safe='')}/"
            f"{quote(repo, safe='')}/releases"
        )

        releases = []
        page = 1

        while True:
            data = await self._get(
                path,
                params={
                    "per_page": per_page,
                    "page": page,
                },
            )

            if not isinstance(data, list):
                raise GitHubError("Invalid releases response.")

            for item in data:
                if not isinstance(item, dict):
                    continue

                tag_name = item.get("tag_name")

                if not tag_name:
                    continue

                assets = []
                raw_assets = item.get("assets", [])

                if not isinstance(raw_assets, list):
                    raw_assets = []

                for asset in raw_assets:
                    if not isinstance(asset, dict):
                        continue

                    name = asset.get("name")
                    download_url = asset.get("browser_download_url")

                    if not name or not download_url:
                        continue

                    assets.append(
                        {
                            "name": name,
                            "size": asset.get("size", 0),
                            "download_url": download_url,
                            "content_type": asset.get("content_type"),
                        }
                    )

                releases.append(
                    {
                        "tag_name": tag_name,
                        "name": item.get("name") or tag_name,
                        "draft": item.get("draft", False),
                        "prerelease": item.get("prerelease", False),
                        "published_at": item.get("published_at"),
                        "html_url": item.get("html_url"),
                        "assets": assets,
                    }
                )

            if len(data) < per_page:
                break

            page += 1

        return releases

    @staticmethod
    def get_source_url(
        owner: str,
        repo: str,
        ref: str,
    ) -> str:
        """Build a GitHub codeload URL for a branch, tag, or commit."""
        owner_path = quote(owner, safe="")
        repo_path = quote(repo, safe="")
        ref_path = quote(ref, safe="")

        return (
            f"https://codeload.github.com/{owner_path}/"
            f"{repo_path}/zip/{ref_path}"
        )

    async def get_readme_files(
        self,
        owner: str,
        repo: str,
    ) -> list[dict]:
        """Return README files available in the repository root."""
        response = await self._get(
            f"/repos/{quote(owner, safe='')}/"
            f"{quote(repo, safe='')}/contents"
        )

        if not isinstance(response, list):
            return []

        readme_files = []

        supported_extensions = (
            ".md",
            ".markdown",
            ".rst",
            ".txt",
            ".html",
            ".htm",
            ".mdx",
        )

        for item in response:
            if not isinstance(item, dict):
                continue

            if item.get("type") != "file":
                continue

            name = item.get("name", "")
            lower_name = name.lower()

            if not lower_name.startswith("readme"):
                continue

            if (
                lower_name == "readme"
                or any(
                    lower_name.endswith(extension)
                    for extension in supported_extensions
                )
            ):
                readme_files.append(
                    {
                        "name": name,
                        "path": item.get("path", name),
                        "download_url": item.get("download_url"),
                        "html_url": item.get("html_url"),
                    }
                )

        return sorted(
            readme_files,
            key=lambda item: (
                item["name"].lower() != "readme.md",
                item["name"].lower(),
            ),
        )

    async def get_readme_content(
        self,
        owner: str,
        repo: str,
        path: str,
    ) -> str:
        """Fetch and decode a README file from GitHub."""
        if (
            not path
            or path.startswith("/")
            or "\x00" in path
        ):
            raise ValueError("Invalid README path.")

        api_path = (
            f"/repos/{quote(owner, safe='')}/"
            f"{quote(repo, safe='')}/contents/"
            f"{quote(path, safe='/')}"
        )

        data = await self._get(api_path)

        if not isinstance(data, dict):
            raise GitHubError("Invalid README response.")

        content = data.get("content")
        encoding = data.get("encoding")

        if content and encoding == "base64":
            try:
                decoded = base64.b64decode(content)
                return decoded.decode("utf-8-sig")
            except (binascii.Error, UnicodeDecodeError) as exc:
                raise GitHubError(
                    "Failed to decode README content."
                ) from exc

        download_url = data.get("download_url")

        if not download_url:
            raise GitHubError(
                "README content is unavailable through "
                "the GitHub Contents API."
            )

        try:
            parsed_url = urlparse(download_url)

            if (
                parsed_url.scheme != "https"
                or parsed_url.hostname
                not in {
                    "raw.githubusercontent.com",
                    "github.com",
                }
                or parsed_url.username is not None
                or parsed_url.password is not None
                or parsed_url.port not in (None, 443)
            ):
                raise GitHubError(
                    "The README download URL is not allowed."
                )

            # Do not forward the GitHub API authorization header to
            # a different host.
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=20.0,
                    write=10.0,
                    pool=10.0,
                ),
                follow_redirects=False,
            ) as download_client:
                response = await download_client.get(download_url)
                response.raise_for_status()

            return response.content.decode("utf-8-sig")

        except GitHubError:
            raise

        except (
            httpx.RequestError,
            httpx.HTTPStatusError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            logger.warning(
                "Failed to download README file: %s",
                path,
            )
            raise GitHubError(
                "Failed to download README content."
            ) from exc
