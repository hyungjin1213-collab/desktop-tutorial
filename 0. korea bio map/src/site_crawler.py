"""Find bio / medicine / pharmacy faculty-list pages by walking a university's own site.

No search API needed. Starting from the homepage, links are followed in order
of how promising their text is (약학대학, 의과대학, 생명과학 … then 교수진,
교수소개 …), staying on the university's domain. A page counts as a faculty
list only if the faculty scraper actually extracts at least MIN_FACULTY
professors from it, so a page titled "교수진" with no people on it is ignored.
"""
from __future__ import annotations

import heapq
import os
import re
import time
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

CRAWL_PAGE_LIMIT = int(os.getenv("CRAWL_PAGE_LIMIT", "120"))
CRAWL_MAX_DEPTH = int(os.getenv("CRAWL_MAX_DEPTH", "4"))
CRAWL_DELAY_SECONDS = float(os.getenv("CRAWL_DELAY_SECONDS", "0.5"))
MAX_SOURCES_PER_UNIVERSITY = int(os.getenv("MAX_SOURCES_PER_UNIVERSITY", "40"))
MIN_FACULTY = 3
USER_AGENT = "Mozilla/5.0 (compatible; AboutBioFacultyCollector/2.1)"

BIO_LINK_WORDS = [
    "약학", "약대", "제약", "의과대학", "의학과", "의학전문대학원", "의과학", "의생명", "의예",
    "생명과학", "생명공학", "생명시스템", "생명정보", "생물", "생화학", "분자", "바이오", "융합생명",
    "뇌과학", "신경과학", "유전", "면역", "수의", "기초의학", "임상의학",
    "pharm", "medicine", "medical", "bio", "life science", "neuro",
]
NON_BIO_LINK_WORDS = [
    "간호", "경영", "경제", "인문", "자유전공", "사회과학", "체육", "스포츠", "음악", "미술", "법학", "행정",
    "국어", "영어영문", "사범", "호텔", "관광", "디자인", "건축", "치의", "치과", "한의",
    "입학", "admission", "장학", "취업", "도서관", "library", "병원 예약", "진료", "기부", "채용",
    "공지", "notice", "뉴스", "news", "게시판", "board", "행사", "event", "login", "로그인",
    "english", "中文", "日本語",
]
FACULTY_LINK_WORDS = ["교수진", "교수소개", "교수 소개", "전임교수", "교원", "교수", "faculty", "professor", "people"]
FACULTY_EXCLUDE_WORDS = ["보직", "겸임", "명예", "초빙", "퇴임", "emeritus", "adjunct", "visiting"]
NAV_WORDS = ["대학", "대학원", "학과", "학부", "전공", "교실", "college", "school", "department", "학사", "조직"]
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|hwp|hwpx|docx?|xlsx?|pptx?|zip|mp4|avi)$", re.I)


@dataclass
class FoundPage:
    url: str
    title: str
    trail: list[str]
    faculty_count: int


@dataclass(order=True)
class _Item:
    priority: float
    url: str = field(compare=False)
    depth: int = field(compare=False)
    trail: tuple = field(compare=False)
    bio_context: bool = field(compare=False)


def _has(text: str, words: list[str]) -> bool:
    low = (text or "").casefold()
    return any(w.casefold() in low for w in words)


def _same_site(url: str, domain: str) -> bool:
    host = urlparse(url).netloc.casefold().split(":")[0].removeprefix("www.")
    return host == domain or host.endswith("." + domain)


def _normalize(url: str) -> str:
    url, _ = urldefrag(url)
    return url.rstrip("/")


def link_score(text: str, url: str, bio_context: bool) -> tuple[float, bool]:
    """(score, is_bio) for a link; score <= 0 means do not follow."""
    hay = f"{text} {urlparse(url).netloc} {urlparse(url).path}"
    if _has(text, NON_BIO_LINK_WORDS) or _has(text, FACULTY_EXCLUDE_WORDS):
        return 0, False
    bio = _has(hay, BIO_LINK_WORDS)
    faculty = _has(text, FACULTY_LINK_WORDS) and not _has(text, FACULTY_EXCLUDE_WORDS)
    score = 0.0
    if bio:
        score += 3
    if faculty and (bio or bio_context):
        score += 5
    elif faculty:
        score += 1
    if _has(text, NAV_WORDS):
        score += 1
    return score, bio or bio_context


class SiteCrawler:
    def __init__(self, fetch, faculty_counter, page_limit: int = CRAWL_PAGE_LIMIT,
                 max_depth: int = CRAWL_MAX_DEPTH, delay: float = CRAWL_DELAY_SECONDS,
                 respect_robots: bool = True):
        """fetch(url) -> html; faculty_counter(html, url) -> number of professors on the page."""
        self.fetch = fetch
        self.faculty_counter = faculty_counter
        self.page_limit = page_limit
        self.max_depth = max_depth
        self.delay = delay
        self.respect_robots = respect_robots
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                text = self.fetch(base + "/robots.txt")
                rp.parse(text.splitlines())
            except Exception:
                rp = None  # no robots.txt: allowed
            self._robots[base] = rp
        rp = self._robots[base]
        return rp is None or rp.can_fetch(USER_AGENT, url)

    def crawl(self, domain: str, start_urls: list[str]) -> list[FoundPage]:
        domain = domain.casefold().removeprefix("www.")
        queue: list[_Item] = []
        seen: set[str] = set()
        for url in start_urls:
            heapq.heappush(queue, _Item(0, url, 0, (), False))
            seen.add(_normalize(url))

        found: list[FoundPage] = []
        fetched = 0
        while queue and fetched < self.page_limit and len(found) < MAX_SOURCES_PER_UNIVERSITY:
            item = heapq.heappop(queue)
            if not self._allowed(item.url):
                continue
            try:
                html = self.fetch(item.url)
            except Exception:
                continue
            fetched += 1
            if self.delay:
                time.sleep(self.delay)
            if not html or "<" not in html[:2000]:
                continue

            soup = BeautifulSoup(html, "html.parser")
            title = re.sub(r"\s+", " ", soup.title.get_text(" ", strip=True) if soup.title else "").strip()
            page_bio = item.bio_context or _has(f"{title} {item.url}", BIO_LINK_WORDS)

            last = item.trail[-1] if item.trail else ""
            looks_faculty = _has(f"{last} {title}", FACULTY_LINK_WORDS) and not _has(
                f"{last} {title}", FACULTY_EXCLUDE_WORDS)
            if page_bio and looks_faculty and not _has(title, NON_BIO_LINK_WORDS):
                count = self.faculty_counter(html, item.url)
                if count >= MIN_FACULTY:
                    found.append(FoundPage(item.url, title, list(item.trail), count))

            if item.depth >= self.max_depth:
                continue
            for a in soup.find_all("a", href=True):
                href = str(a.get("href", "")).strip()
                if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                    continue
                url = urljoin(item.url, href)
                if not url.startswith("http") or SKIP_EXT.search(urlparse(url).path):
                    continue
                if not _same_site(url, domain):
                    continue
                key = _normalize(url)
                if key in seen:
                    continue
                text = re.sub(r"\s+", " ", a.get_text(" ", strip=True) or str(a.get("title", ""))).strip()[:60]
                score, bio = link_score(text, url, page_bio)
                if score <= 0:
                    continue
                seen.add(key)
                # Higher score first; shallower first among equals.
                heapq.heappush(queue, _Item(-score + 0.1 * (item.depth + 1), url, item.depth + 1,
                                            item.trail + (text,), bio))
        return found


def department_label(page: FoundPage, university_ko: str = "") -> str:
    """Best department name: the last bio-looking link text on the path, else the title."""
    for text in reversed(page.trail):
        if _has(text, BIO_LINK_WORDS) and not _has(text, FACULTY_LINK_WORDS):
            return text[:60]
    parts = [p.strip() for p in re.split(r"[|>\-–·:]", page.title) if p.strip()]
    keep = [p for p in parts if not _has(p, FACULTY_LINK_WORDS) and (not university_ko or university_ko not in p)]
    return (keep or parts or [page.title or page.url])[0][:60]
