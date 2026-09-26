"""Small, auditable helpers for discovering changing official URLs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin


@dataclass(frozen=True)
class DiscoveredLink:
    url: str
    text: str = ""


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[DiscoveredLink] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._href = dict(attrs).get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.links.append(DiscoveredLink(self._href, " ".join("".join(self._text).split())))
            self._href = None
            self._text = []


def discover_links(html: str, base_url: str, *, text_pattern: str | None = None, href_pattern: str | None = None) -> list[DiscoveredLink]:
    parser = _LinkParser()
    parser.feed(html)
    text_re = re.compile(text_pattern, re.I) if text_pattern else None
    href_re = re.compile(href_pattern, re.I) if href_pattern else None
    return [
        DiscoveredLink(urljoin(base_url, item.url), item.text)
        for item in parser.links
        if (not text_re or text_re.search(item.text)) and (not href_re or href_re.search(item.url))
    ]


def discover_mof_statistical_links(html: str, base_url: str = "https://gks.mof.gov.cn/tongjishuju/") -> list[DiscoveredLink]:
    """Find MOF fiscal-data articles and PDF attachments from the statistics list."""
    return discover_links(html, base_url, text_pattern=r"财政收支|政府收支|融资|债务")


def discover_customs_statistical_links(html: str, base_url: str = "https://www.customs.gov.cn/") -> list[DiscoveredLink]:
    """Find likely monthly trade-data entries when the customs page is reachable."""
    return discover_links(html, base_url, text_pattern=r"进出口|进出口总值|海关统计")
