from __future__ import annotations

import html
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


@dataclass(frozen=True)
class PaperResult:
    title: str
    authors: list[str]
    summary: str
    published: str
    updated: str
    url: str
    pdf_url: str | None


class ResearchSearch:
    async def search_arxiv(self, query: str, max_results: int = 8) -> list[PaperResult]:
        params = {
            "search_query": f"all:{query}",
            "start": "0",
            "max_results": str(max(1, min(max_results, 25))),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
        return parse_arxiv_feed(response.text)


def parse_arxiv_feed(feed_xml: str) -> list[PaperResult]:
    root = ET.fromstring(feed_xml)
    papers: list[PaperResult] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title = _clean(entry.findtext("atom:title", default="", namespaces=ATOM_NS))
        summary = _clean(entry.findtext("atom:summary", default="", namespaces=ATOM_NS))
        published = entry.findtext("atom:published", default="", namespaces=ATOM_NS)
        updated = entry.findtext("atom:updated", default="", namespaces=ATOM_NS)
        url = entry.findtext("atom:id", default="", namespaces=ATOM_NS)
        authors = [
            _clean(author.findtext("atom:name", default="", namespaces=ATOM_NS))
            for author in entry.findall("atom:author", ATOM_NS)
        ]
        pdf_url = None
        for link in entry.findall("atom:link", ATOM_NS):
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href")
                break
        papers.append(
            PaperResult(
                title=title,
                authors=[author for author in authors if author],
                summary=summary,
                published=published,
                updated=updated,
                url=url,
                pdf_url=pdf_url,
            )
        )
    return papers


def _clean(value: str) -> str:
    return " ".join(html.unescape(value).split())
