from services.repository_presenter import format_repository_card, format_repository_date


def test_repository_date_handles_valid_and_invalid_values():
    assert format_repository_date("2025-01-02T03:04:05Z") == "Jan 02, 2025"
    assert format_repository_date("not-a-date") == "Unknown"
    assert format_repository_date(None) == "Unknown"


def test_repository_card_escapes_untrusted_html_fields():
    card = format_repository_card(
        "owner/repo",
        {
            "full_name": "owner/<script>alert(1)</script>",
            "description": "<img src=x onerror=alert(1)>",
            "html_url": 'https://github.com/owner/repo" onmouseover="alert(1)',
            "stars": 12,
            "forks": 3,
            "open_issues": 1,
            "watchers": 4,
            "updated_at": "not-a-date",
        },
    )

    assert "<script>" not in card
    assert "<img" not in card
    assert "&lt;script&gt;" in card
    assert "onerror=alert(1)" in card
    assert ' onmouseover="alert(1)' not in card
