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
# Korean university sites often link through JavaScript:
#   onclick="goPage('/sub/faculty.do')"  href="javascript:location.href='/x'"
JS_URL_RE = re.compile(r"""['"]((?:https?://|/)[^'"\s]{2,200})['"]""")
# College sites usually live on a subdomain; trying these directly works even
# when the main portal's menu is built by JavaScript.
COLLEGE_SUBDOMAINS = ["pharm", "pharmacy", "medicine", "med", "medi", "bio", "biology", "life",
                      "lifesci", "biomed", "bms", "cls", "gsm", "vet"]
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|svg|ico|webp|hwp|hwpx|docx?|xlsx?|pptx?|zip|mp4|avi|css|js|woff2?|ttf|xml|rss|json)$", re.I)


@dataclass
class FoundPage:
    url: str
    title: str
    trail: list[str]
    faculty_count: int


@dataclass
class CrawlStats:
    fetched: int = 0
    errors: dict = field(default_factory=dict)
    robots_blocked: int = 0
    faculty_like_checked: int = 0

    def summary(self) -> str:
        err = ", ".join(f"{k} x{v}" for k, v in sorted(self.errors.items(), key=lambda kv: -kv[1])[:3])
        parts = [f"{self.fetched} pages fetched", f"{self.faculty_like_checked} faculty-like pages checked"]
        if self.robots_blocked:
            parts.append(f"{self.robots_blocked} blocked by robots.txt")
        if err:
            parts.append(f"errors: {err}")
        return "; ".join(parts)


def start_urls(domain: str) -> list[str]:
    domain = domain.casefold().removeprefix("www.")
    return ([f"https://www.{domain}/", f"https://{domain}/"]
            + [f"https://{sub}.{domain}/" for sub in COLLEGE_SUBDOMAINS])


def _page_links(soup: BeautifulSoup, base: str) -> list[tuple[str, str]]:
    """(url, text) for anchors, JavaScript links, frames and meta refresh."""
    out: list[tuple[str, str]] = []
    js_attrs = ("onclick", "data-href", "data-url", "data-link")
    for tag in soup.find_all(lambda t: t.has_attr("href") or any(t.has_attr(k) for k in js_attrs)):
        href = str(tag.get("href", "") or "").strip()
        text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True) or str(tag.get("title", ""))).strip()[:60]
        if tag.name in ("a", "area") and href and not href.lower().startswith(("javascript:", "#", "mailto:", "tel:")):
            out.append((urljoin(base, href), text))
            continue
        js = " ".join(str(tag.get(k, "")) for k in js_attrs)
        if href.lower().startswith("javascript:"):
            js += " " + href
        for m in JS_URL_RE.finditer(js):
            out.append((urljoin(base, m.group(1)), text))
    for frame in soup.find_all(["iframe", "frame"], src=True):
        out.append((urljoin(base, str(frame["src"])), "frame"))
    for meta in soup.find_all("meta", attrs={"http-equiv": re.compile("refresh", re.I)}):
        m = re.search(r"url\s*=\s*['\"]?([^'\";]+)", str(meta.get("content", "")), re.I)
        if m:
            out.append((urljoin(base, m.group(1).strip()), "redirect"))
    return out


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
        self.stats = CrawlStats()
        queue: list[_Item] = []
        seen: set[str] = set()
        # The first two start URLs are the homepage (www / bare); the rest are
        # guessed college subdomains, tried after it. Many of those do not
        # exist, so their failures are expected, not errors worth reporting.
        optional = {_normalize(u) for u in start_urls[2:]} | {_normalize(start_urls[1])} if len(start_urls) > 1 else set()
        for i, url in enumerate(start_urls):
            guessed = i >= 2
            heapq.heappush(queue, _Item(0.5 if guessed else 0, url, 1 if guessed else 0, (), False))
            seen.add(_normalize(url))

        found: list[FoundPage] = []
        fetched = 0
        while queue and fetched < self.page_limit and len(found) < MAX_SOURCES_PER_UNIVERSITY:
            item = heapq.heappop(queue)
            if not self._allowed(item.url):
                self.stats.robots_blocked += 1
                continue
            try:
                html = self.fetch(item.url)
            except Exception as exc:
                if _normalize(item.url) in optional:
                    continue
                kind = type(exc).__name__
                self.stats.errors[kind] = self.stats.errors.get(kind, 0) + 1
                continue
            fetched += 1
            self.stats.fetched += 1
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
                self.stats.faculty_like_checked += 1
                count = self.faculty_counter(html, item.url)
                if count >= MIN_FACULTY:
                    found.append(FoundPage(item.url, title, list(item.trail), count))
                    # Its links are mostly per-professor detail pages: do not
                    # spend the page budget on them.
                    continue

            if item.depth >= self.max_depth:
                continue
            for url, text in _page_links(soup, item.url):
                if not url.startswith("http") or SKIP_EXT.search(urlparse(url).path):
                    continue
                if not _same_site(url, domain):
                    continue
                key = _normalize(url)
                if key in seen:
                    continue
                score, bio = link_score(text, url, page_bio)
                if text in ("frame", "redirect"):
                    score, bio = max(score, 2), page_bio  # same page, just embedded
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
