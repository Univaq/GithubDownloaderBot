"""Presentation formatting for GitHub repository metadata."""

import html
from datetime import datetime


def format_repository_date(value: str | None) -> str:
    if not value:
        return "Unknown"

    try:
        date = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        return date.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return "Unknown"

def format_repository_card(
    full_name: str,
    repository: dict,
) -> str:
    name = html.escape(
        repository.get("full_name") or full_name
    )
    description = html.escape(
        repository.get("description") or "No description available."
    )
    language = html.escape(
        repository.get("language") or "Not specified"
    )
    branch = html.escape(
        repository.get("default_branch") or "Unknown"
    )
    url = html.escape(
        repository.get("html_url")
        or f"https://github.com/{full_name}",
        quote=True,
    )

    stars = repository.get(
        "stars",
        repository.get("stargazers_count", 0),
    ) or 0
    forks = repository.get(
        "forks",
        repository.get("forks_count", 0),
    ) or 0
    issues = repository.get(
        "open_issues",
        repository.get("open_issues_count", 0),
    ) or 0
    watchers = repository.get(
        "watchers",
        repository.get("subscribers_count", 0),
    ) or 0

    updated = format_repository_date(
        repository.get("updated_at")
    )

    license_info = repository.get("license")

    if isinstance(license_info, dict):
        license_name = (
            license_info.get("spdx_id")
            or license_info.get("name")
            or "Not specified"
        )
    elif isinstance(license_info, str):
        license_name = license_info
    else:
        license_name = "Not specified"

    license_name = html.escape(license_name)

    status = "Archived" if repository.get("archived") else "Active"

    if repository.get("fork"):
        status += " · Fork"

    return (
        f"📦 <b>{name}</b>\n\n"
        f"<i>{description}</i>\n\n"
        f"⭐ <b>Stars:</b> {stars:,}\n"
        f"🍴 <b>Forks:</b> {forks:,}\n"
        f"👀 <b>Watchers:</b> {watchers:,}\n"
        f"🐛 <b>Open issues:</b> {issues:,}\n\n"
        f"💻 <b>Language:</b> {language}\n"
        f"🌿 <b>Default branch:</b> <code>{branch}</code>\n"
        f"📜 <b>License:</b> {license_name}\n"
        f"🕒 <b>Last updated:</b> {updated}\n"
        f"📌 <b>Status:</b> {html.escape(status)}\n\n"
        f'<a href="{url}">View on GitHub ↗</a>\n\n'
        f"<b>What would you like to explore?</b>"
    )
