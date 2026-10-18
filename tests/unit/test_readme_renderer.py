from services.readme_renderer import (
    TELEGRAM_MESSAGE_LIMIT,
    clean_readme_content,
    format_markdown_inline,
    split_readme_preview,
)


def test_clean_readme_removes_images_html_and_comments():
    cleaned = clean_readme_content(
        "Intro<!-- private -->\n<img src='x'>\nText<br><b>bold</b> ![logo](https://example.com/logo.png)"
    )

    assert "private" not in cleaned
    assert "img" not in cleaned
    assert "logo" not in cleaned
    assert "Text" in cleaned
    assert "bold" in cleaned


def test_inline_markdown_escapes_html_and_rejects_non_http_links():
    rendered = format_markdown_inline(
        '<script>alert(1)</script> [safe](https://example.com) [bad](javascript:alert(1))'
    )

    assert "&lt;script&gt;" in rendered
    assert '<a href="https://example.com">safe</a>' in rendered
    assert "javascript:" not in rendered
    assert "bad" in rendered


def test_readme_preview_splits_large_code_blocks_under_telegram_limit():
    source = "```text\n" + ("x" * 4000) + "\n```"

    messages = split_readme_preview(source)

    assert len(messages) >= 2
    assert all(len(message) <= TELEGRAM_MESSAGE_LIMIT for message in messages)
    assert all(message.startswith("<pre>") and message.endswith("</pre>") for message in messages)
