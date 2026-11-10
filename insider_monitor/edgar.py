from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter, Retry

ATOM = "{http://www.w3.org/2005/Atom}"
ACCESSION_RE = re.compile(r"(\d{10}-\d{2}-\d{6})")
HREF_XML_RE = re.compile(r"""href=['"]([^'"]+\.xml)['"]""", re.I)
FEED_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4"
            "&company=&dateb=&owner=include&start={start}&count={count}&output=atom")


@dataclass(frozen=True)
class FeedEntry:
    accession: str
    title: str
    index_url: str
    updated: str


def parse_feed(xml_bytes: bytes) -> list[FeedEntry]:
    """Form 4 entries from an EDGAR 'latest filings' Atom feed.

    EDGAR's type filter is a prefix match (it also returns 424B2, 425, ...), and
    each filing is listed once per filer (issuer + reporting owner), so we keep
    only titles starting '4 - ' / '4/A - ' and de-duplicate by accession number.
    """
    root = ET.fromstring(xml_bytes)
    entries, seen = [], set()
    for e in root.findall(f"{ATOM}entry"):
        title = (e.findtext(f"{ATOM}title") or "").strip()
        if not title.startswith(("4 - ", "4/A - ")):
            continue
        link = e.find(f"{ATOM}link")
        href = link.get("href") if link is not None else ""
        m = ACCESSION_RE.search(href or "") or ACCESSION_RE.search(e.findtext(f"{ATOM}id") or "")
        if not (href and m) or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        entries.append(FeedEntry(m.group(1), title, href,
                                 (e.findtext(f"{ATOM}updated") or "").strip()))
    return entries


def pick_xml_link(index_html: str) -> str | None:
    """Raw Form 4 XML on a filing index page.

    The index lists both the raw XML and an XSLT-rendered HTML view whose path
    contains '/xsl...'; the rendered one is not parseable, so skip it.
    """
    for href in HREF_XML_RE.findall(index_html):
        if "/xsl" in href.lower():
            continue
        return urljoin("https://www.sec.gov", href)
    return None


class EdgarClient:
    """Polite SEC client: identifying User-Agent, <10 req/s, retries with backoff."""

    def __init__(self, user_agent: str, min_interval: float = 0.15):
        self.min_interval = min_interval
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent,
                                     "Accept-Encoding": "gzip, deflate"})
        retries = Retry(total=3, backoff_factor=1.5,
                        status_forcelist=(429, 500, 502, 503, 504),
                        allowed_methods=("GET",))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def _get(self, url: str) -> requests.Response:
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        return resp

    def feed_page(self, start: int = 0, count: int = 100) -> list[FeedEntry]:
        return parse_feed(self._get(FEED_URL.format(start=start, count=count)).content)

    def form4_xml(self, index_url: str) -> bytes | None:
        link = pick_xml_link(self._get(index_url).text)
        return self._get(link).content if link else None
