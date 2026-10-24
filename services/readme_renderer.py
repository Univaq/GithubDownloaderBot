"""Safe formatting helpers for rendering GitHub README content in Telegram."""

import html
import re

TELEGRAM_MESSAGE_LIMIT = 3500


def clean_readme_content(content: str) -> str:
    """Remove decorative elements and clean README Markdown."""
    content = re.sub(
        r"<!--.*?-->",
        "",
        content,
        flags=re.DOTALL,
    )

    content = re.sub(
        r"<img\b[^>]*>",
        "",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r"<svg\b[^>]*>.*?</svg\s*>",
        "",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )

    content = re.sub(
        r"!\[[^\]]*\]\([^)]*\)",
        "",
        content,
    )
    content = re.sub(
        r"!\[[^\]]*\]\[[^\]]*\]",
        "",
        content,
    )

    content = re.sub(
        r"\[\s*\]\([^)]*\)",
        "",
        content,
    )

    content = re.sub(
        r"<br\s*/?>",
        "\n",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r"</(p|div|h[1-6]|li|tr|section)\s*>",
        "\n",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(r"<[^>]+>", "", content)

    content = re.sub(
        r"^\s*\[[^\]]+\]:\s*\S+.*$",
        "",
        content,
        flags=re.MULTILINE,
    )

    content = re.sub(r"[ \t]+\n", "\n", content)
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content.strip()

def format_markdown_inline(text: str) -> str:
    pattern = re.compile(
        r"!\[([^\]]*)\]\([^)]*\)"
        r"|\[([^\]]+)\]\(([^)\s]+)(?:\s+[\"'][^)]*[\"'])?\)"
        r"|`([^`\n]+)`"
        r"|\*\*(.+?)\*\*"
        r"|__(.+?)__"
        r"|(?<!\*)\*([^*\n]+)\*(?!\*)"
        r"|(?<!_)_([^_\n]+)_(?!_)"
    )

    parts = []
    position = 0

    for match in pattern.finditer(text):
        parts.append(html.escape(text[position:match.start()]))
        groups = match.groups()

        if groups[0] is not None:
            pass
        elif groups[1] is not None:
            label = groups[1]
            url = groups[2]

            if url.startswith(("https://", "http://")):
                safe_url = html.escape(url, quote=True)
                safe_label = html.escape(label)
                parts.append(f'<a href="{safe_url}">{safe_label}</a>')
            else:
                parts.append(html.escape(label))
        elif groups[3] is not None:
            parts.append(f"<code>{html.escape(groups[3])}</code>")
        elif groups[4] is not None:
            parts.append(f"<b>{html.escape(groups[4])}</b>")
        elif groups[5] is not None:
            parts.append(f"<b>{html.escape(groups[5])}</b>")
        elif groups[6] is not None:
            parts.append(f"<i>{html.escape(groups[6])}</i>")
        elif groups[7] is not None:
            parts.append(f"<i>{html.escape(groups[7])}</i>")

        position = match.end()

    parts.append(html.escape(text[position:]))
    return "".join(parts)

def split_readme_preview(content: str) -> list[str]:
    blocks = []
    paragraph = []
    code_lines = []
    in_code = False
    code_marker = None

    def flush_paragraph():
        if paragraph:
            text = " ".join(line.strip() for line in paragraph)
            if text:
                blocks.append(format_markdown_inline(text))
            paragraph.clear()

    def add_code_chunks(source_lines):
        current = []

        for line in source_lines:
            candidate = "\n".join(current + [line])

            if current and len(candidate) > TELEGRAM_MESSAGE_LIMIT - 20:
                blocks.append(
                    "<pre>"
                    + html.escape("\n".join(current))
                    + "</pre>"
                )
                current = [line]
            else:
                current.append(line)

        if current:
            blocks.append(
                "<pre>"
                + html.escape("\n".join(current))
                + "</pre>"
            )

    for line in content.splitlines():
        stripped = line.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]

            if not in_code:
                flush_paragraph()
                in_code = True
                code_marker = marker
                code_lines = []
            elif marker == code_marker:
                add_code_chunks(code_lines)
                code_lines = []
                in_code = False
                code_marker = None

            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            flush_paragraph()
            continue

        heading = re.match(
            r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$",
            line,
        )

        if heading:
            flush_paragraph()
            blocks.append(
                "<b>"
                + format_markdown_inline(heading.group(1))
                + "</b>"
            )
            continue

        if re.match(r"^\s*([-*_]\s*){3,}$", line):
            flush_paragraph()
            blocks.append("──────────")
            continue

        list_item = re.match(r"^\s*[-*+]\s+(.+)$", line)
        numbered_item = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        quote = re.match(r"^\s*>\s?(.*)$", line)

        if list_item:
            flush_paragraph()
            blocks.append("• " + format_markdown_inline(list_item.group(1)))
        elif numbered_item:
            flush_paragraph()
            blocks.append(format_markdown_inline(line.strip()))
        elif quote:
            flush_paragraph()
            blocks.append(
                "│ " + format_markdown_inline(quote.group(1))
            )
        else:
            paragraph.append(line)

    flush_paragraph()

    if in_code:
        add_code_chunks(code_lines)

    messages = []
    current = ""

    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block

        if current and len(candidate) > TELEGRAM_MESSAGE_LIMIT:
            messages.append(current)
            current = block
        else:
            current = candidate

    if current:
        messages.append(current)

    return messages or ["<i>This README is empty.</i>"]
