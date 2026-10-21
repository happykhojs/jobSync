"""
HTML formatting for job descriptions/requirements, matching the website's format:
    <p>Intro</p><p><strong>Key Responsibilities</strong></p><ul><li><p>Item</p></li></ul>

Only p, strong, ul, ol, li and br are kept; everything else is unwrapped and all attributes dropped.
"""
from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup, NavigableString

ALLOWED = {"p", "strong", "ul", "ol", "li", "br"}
RENAME = {"b": "strong"}
DROP = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "img", "video", "audio"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def looks_like_html(text: str) -> bool:
    return bool(re.search(r"<(p|ul|ol|li|strong|br|div|h[1-6])\b", text or "", re.I))


def sanitize_html(value: str) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    for tag in soup.find_all(DROP):
        tag.decompose()
    for tag in soup.find_all(True):
        name = tag.name.lower()
        if name in HEADING_TAGS:
            # Headings become bold paragraphs, the way the site styles section titles.
            tag.name = "p"
            tag.attrs = {}
            inner = soup.new_tag("strong")
            inner.extend(list(tag.contents))
            tag.append(inner)
            continue
        if name in RENAME:
            tag.name = RENAME[name]
        if tag.name not in ALLOWED:
            tag.unwrap()
            continue
        tag.attrs = {}
    # Every list item holds a paragraph, like the site's editor produces.
    for li in soup.find_all("li"):
        if not any(getattr(c, "name", None) in ("p", "ul", "ol") for c in li.contents):
            p = soup.new_tag("p")
            p.extend(list(li.contents))
            li.append(p)
    # Drop empty paragraphs / list items.
    for tag in soup.find_all(["p", "li", "strong"]):
        if not tag.get_text(strip=True) and not tag.find(["ul", "ol"]):
            tag.decompose()
    out = str(soup)
    out = re.sub(r"\s*\n\s*", "", out)
    return out.strip()


def _is_heading(line: str) -> bool:
    return len(line) <= 70 and (line.endswith(":") or not re.search(r"[.!?]$", line)) and len(line.split()) <= 9


def text_to_html(text: str) -> str:
    """Convert plain text (paragraphs, headings, bullet lines) into the site's HTML format."""
    out: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if items:
            out.append("<ul>" + "".join(f"<li><p>{html.escape(i)}</p></li>" for i in items) + "</ul>")
            items.clear()

    seen_heading = False
    for raw in (text or "").split("\n"):
        line = re.sub(r"^\s*(?:[•●▪◦‣\-–—]|\d{1,2}[.)])\s*", "", raw)
        line = re.sub(r"\*{1,2}|_{2}|#{1,6}\s*", "", line).strip()  # markdown leftovers in source text
        if not line:
            continue
        if _is_heading(line):
            flush()
            out.append(f"<p><strong>{html.escape(line.rstrip(':').strip())}</strong></p>")
            seen_heading = True
        elif seen_heading:
            items.append(line)
        else:
            out.append(f"<p>{html.escape(line)}</p>")
    flush()
    return "".join(out)


def to_site_html(value: str) -> str:
    if not value:
        return ""
    return sanitize_html(value) if looks_like_html(value) else text_to_html(value)


def html_to_text(value: str) -> str:
    """Plain text for keyword matching / model input."""
    soup = BeautifulSoup(value or "", "html.parser")
    for li in soup.find_all("li"):
        li.insert_before(NavigableString("\n"))
    return re.sub(r"\n{2,}", "\n", soup.get_text("\n", strip=True))
