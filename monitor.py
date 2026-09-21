from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag
from summary_text import compact_change
from summary_cards import render_cards


# ============================================================
# 기본 설정
# ============================================================

# 1순위: 넥슨 한국 공식 패치노트
NEXON_LIST_URL = "https://overwatch.nexon.com/news/patchnotes"

# 2순위: Blizzard 한국 공식 패치노트
BLIZZARD_BASE_URL = "https://overwatch.blizzard.com/ko-kr/news/patch-notes/"

STATE_FILE = Path("state.json")

MESSAGE_LIMIT = 1900

# 텍스트 메시지에만 적용됩니다. 자동 요약 카드는 별도로 전송합니다.
# 패치 본문에서 수집한 공식 이미지는 Discord에 전송하지 않습니다.
MAX_TEXT_MESSAGES = int(os.getenv("MAX_TEXT_MESSAGES", "20"))

SEND_ON_FIRST_RUN = os.getenv("SEND_ON_FIRST_RUN", "true").lower() == "true"

# 넥슨 목록에서 최근 게시물 몇 개를 상세 확인할지
NEXON_MAX_ARTICLES = int(os.getenv("NEXON_MAX_ARTICLES", "20"))

# Blizzard는 현재 달 + 이전 몇 개월을 볼지
MONTH_LOOKBACK = int(os.getenv("MONTH_LOOKBACK", "4"))

# Discord 한 메시지의 Embed 최대 개수
DISCORD_EMBEDS_PER_MESSAGE = 10


# ============================================================
# 자동 요약 카드 설정
# ============================================================

SUMMARY_CARD_VERSION = 3

# 패치에 영웅 밸런스 변경이 없을 때 만드는 일반 핵심 요약의 최대 항목 수.
SUMMARY_GENERIC_MAX_ITEMS = 16

ROLE_ALIASES = {
    "돌격": "돌격",
    "tank": "돌격",
    "공격": "공격",
    "damage": "공격",
    "지원": "지원",
    "support": "지원",
}

GENERIC_SECTION_WORDS = {
    "일반",
    "일반 업데이트",
    "핫픽스",
    "핫픽스 업데이트",
    "핫픽스 패치",
    "버그 수정",
    "영웅 업데이트",
    "영웅 밸런스 업데이트",
    "스타디움",
    "스타디움 업데이트",
    "경쟁전",
    "경쟁전 업데이트",
    "시스템",
    "시스템 업데이트",
    "전장",
    "전장 업데이트",
    "핵심 게임 업데이트",
    "general",
    "general updates",
    "hotfix",
    "hotfix update",
    "bug fixes",
    "hero updates",
    "stadium",
    "stadium updates",
    "competitive",
    "system",
    "maps",
}

# 값이 작아질수록 일반적으로 유리한 항목
LOWER_IS_BETTER_KEYWORDS = (
    "재사용 대기",
    "쿨다운",
    "소모",
    "궁극기 비용",
    "cooldown",
    "시전 시간",
    "시전시간",
    "지연 시간",
    "지연시간",
    "회복 시간",
    "충전 시간",
    "충전시간",
    "후딜",
    "선딜",
    "분산도",
    "탄 퍼짐",
    "퍼짐",
    "반동",
    "폭발 지연",
    "재장전 시간",
    "재장전시간",
    "변신 지속 시간",
    "휘두르기 지속 시간",
    "연속 공격 지속 시간",
)

# 값이 커질수록 일반적으로 유리한 항목
HIGHER_IS_BETTER_KEYWORDS = (
    "생명력",
    "방어력",
    "보호막",
    "내구도",
    "피해",
    "공격력",
    "치유",
    "회복",
    "사거리",
    "이동 속도",
    "이동속도",
    "추가 속도",
    "추가속도",
    "투사체 속도",
    "투사체속도",
    "발사 속도",
    "발사속도",
    "탄창",
    "탄약",
    "범위",
    "재생률",
    "재생 속도",
    "배치 거리",
    "획득 거리",
    "투사체 크기",
    "공격 속도",
    "충전량",
    "화살 개수",
    "기술 위력",
)

CHANGE_NUMBER_RE = re.compile(
    r"(-?\d+(?:,\d{3})*(?:\.\d+)?)\s*(%p|%|밀리초|초|m/s|m|미터/초|미터|발|개|회|배)?\s*(?:→|->|에서)\s*"
    r"(-?\d+(?:,\d{3})*(?:\.\d+)?)\s*(%p|%|밀리초|초|m/s|m|미터/초|미터|발|개|회|배)?",
    re.IGNORECASE,
)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.5",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

KOREAN_DATE_RE = re.compile(
    r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"
)

ENGLISH_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})",
    re.IGNORECASE,
)

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

RELATIVE_TIME_RE = re.compile(
    r"^\d+\s*(?:초|분|시간|일|주|개월|년)\s*전$"
)

DOT_DATE_RE = re.compile(
    r"^20\d{2}[./-]\d{1,2}[./-]\d{1,2}$"
)

IMAGE_TEXT_RE = re.compile(
    r"^Image(?::.*)?$",
    re.IGNORECASE,
)

NEXON_ARTICLE_HREF_RE = re.compile(
    r"^/news/patchnotes/\d+(?:/|$)"
)


@dataclass
class Patch:
    title: str
    date_key: str
    same_day_index: int
    patch_id: str
    items: list[tuple[str, str]]
    images: list[str]
    body_hash: str
    image_hash: str
    signature_text: str
    source_url: str
    source_name: str


@dataclass
class LanguageCheck:
    is_korean: bool
    hangul_count: int
    latin_count: int
    hangul_ratio: float
    korean_lines: int
    total_lines: int
    reason: str


# ============================================================
# 공통 유틸
# ============================================================

def clean_text(value: str) -> str:
    value = value.replace("\u200b", "")
    value = value.replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def fetch_html(url: str) -> str:
    response = requests.get(
        url,
        headers=REQUEST_HEADERS,
        timeout=30,
        allow_redirects=True,
    )

    print(
        f"페이지 확인: {url} -> HTTP {response.status_code}, "
        f"{len(response.text)} bytes"
    )

    response.raise_for_status()
    return response.text


def extract_date_key(text: str) -> str:
    ko = KOREAN_DATE_RE.search(text)
    if ko:
        year, month, day = map(int, ko.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"

    en = ENGLISH_DATE_RE.search(text)
    if en:
        month_name, day, year = en.groups()
        month = MONTHS[month_name.lower()]
        return f"{int(year):04d}-{month:02d}-{int(day):02d}"

    return ""


def is_patch_title(text: str) -> bool:
    lowered = text.lower()

    return (
        ("패치 노트" in text or "patch notes" in lowered)
        and bool(extract_date_key(text))
    )


def heading_level(tag_name: str) -> int | None:
    if re.fullmatch(r"h[1-6]", tag_name):
        return int(tag_name[1])
    return None


def shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + offset
    return index // 12, index % 12 + 1


def candidate_blizzard_urls() -> list[str]:
    now = datetime.now(timezone.utc)
    urls: list[str] = []

    for offset in range(0, -MONTH_LOOKBACK, -1):
        year, month = shift_month(now.year, now.month, offset)

        urls.append(
            f"{BLIZZARD_BASE_URL}live/{year}/{month:02d}/"
        )

    return urls


def is_descendant_of(
    node: Tag,
    area: Tag | BeautifulSoup,
) -> bool:
    if isinstance(area, BeautifulSoup):
        return True

    return (
        node is area
        or area in node.parents
    )


# ============================================================
# 이미지 처리
# ============================================================

def choose_srcset_url(srcset: str) -> str:
    """
    srcset에서 마지막(보통 가장 큰) 이미지를 선택합니다.
    """
    candidates: list[str] = []

    for part in srcset.split(","):
        value = part.strip()

        if not value:
            continue

        url = value.split()[0].strip()

        if url:
            candidates.append(url)

    return (
        candidates[-1]
        if candidates
        else ""
    )


def extract_image_url(
    img: Tag,
    base_url: str,
) -> str:
    """
    lazy-load 속성까지 포함하여 실제 이미지 주소를 찾습니다.
    """

    width = str(
        img.get("width", "")
    ).strip()

    height = str(
        img.get("height", "")
    ).strip()

    # 1x1 추적 픽셀 방지
    if width.isdigit() and height.isdigit():
        if int(width) <= 2 and int(height) <= 2:
            return ""

    candidate = ""

    for attr in (
        "data-src",
        "data-original",
        "data-lazy-src",
        "data-image",
        "src",
    ):
        value = str(
            img.get(attr, "")
        ).strip()

        if value:
            candidate = value
            break

    if not candidate:
        for attr in (
            "data-srcset",
            "srcset",
        ):
            value = str(
                img.get(attr, "")
            ).strip()

            if value:
                candidate = choose_srcset_url(
                    value
                )
                break

    if not candidate:
        return ""

    if candidate.startswith("data:"):
        return ""

    absolute = urljoin(
        base_url,
        candidate,
    )

    parts = urlsplit(
        absolute
    )

    if parts.scheme not in {
        "http",
        "https",
    }:
        return ""

    lowered_path = parts.path.lower()

    # 사이트 UI에서 흔한 장식 이미지만 제외합니다.
    # hero/ability icon은 살리기 위해 "icon" 자체는 제외 조건에 넣지 않습니다.
    blocked_markers = (
        "favicon",
        "/logo",
        "logo.",
        "social-share",
        "share-icon",
        "tracking",
        "pixel.gif",
    )

    if any(
        marker in lowered_path
        for marker in blocked_markers
    ):
        return ""

    # Discord Embed는 SVG 표시가 안정적이지 않아 제외합니다.
    if lowered_path.endswith(".svg"):
        return ""

    return absolute


def canonical_image_key(
    image_url: str,
) -> str:
    """
    크기 조정/캐시용 query가 달라졌다고 이미지 변경으로 오인하지 않도록
    scheme + host + path만 비교에 사용합니다.
    """
    parts = urlsplit(
        image_url
    )

    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            "",
            "",
        )
    )


def dedupe_images(
    images: list[str],
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for image_url in images:
        key = canonical_image_key(
            image_url
        )

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)
        result.append(
            image_url
        )

    return result


def build_image_hash(
    images: list[str],
) -> str:
    keys = [
        canonical_image_key(url)
        for url in images
    ]

    return hashlib.sha256(
        "\n".join(keys).encode("utf-8")
    ).hexdigest()


# ============================================================
# 본문 hash / 중복 식별
# ============================================================

def build_body_hash(
    title: str,
    items: list[tuple[str, str]],
) -> str:
    parts = [title]
    parts.extend(
        text
        for _, text in items
    )

    return hashlib.sha256(
        "\n".join(parts).encode("utf-8")
    ).hexdigest()


def normalize_signature_text(
    value: str,
) -> str:
    value = value.lower()

    value = KOREAN_DATE_RE.sub(
        "<date>",
        value,
    )

    value = ENGLISH_DATE_RE.sub(
        "<date>",
        value,
    )

    value = re.sub(
        r"\d+(?:\.\d+)?%?",
        "<n>",
        value,
    )

    value = re.sub(
        r"[^a-z0-9가-힣<>]+",
        " ",
        value,
    )

    return clean_text(
        value
    )


def build_signature_text(
    items: list[tuple[str, str]],
) -> str:
    """
    Blizzard ↔ Nexon 중복 감지용.
    제목은 번역/브랜드명이 달라질 수 있어 본문 위주로 비교합니다.
    """
    parts: list[str] = []

    for _, text in items[:80]:
        normalized = normalize_signature_text(
            text
        )

        if normalized:
            parts.append(
                normalized
            )

    return " | ".join(
        parts
    )[:12000]


def assign_patch_ids(
    raw_patches: list[dict],
) -> list[Patch]:
    """
    raw_patches는 최신 -> 오래된 순서라고 가정합니다.

    같은 날짜 패치가 여러 개면 아래쪽(오래된 것)을 #01로 두어
    같은 날 새 글이 위에 추가돼도 기존 patch_id가 유지됩니다.
    """
    totals = Counter(
        item["date_key"]
        for item in raw_patches
    )

    seen_from_top: Counter[str] = Counter()

    result: list[Patch] = []

    for item in raw_patches:
        date_key = item["date_key"]

        seen_from_top[date_key] += 1

        same_day_index = (
            totals[date_key]
            - seen_from_top[date_key]
            + 1
        )

        patch_id = (
            f"{date_key}"
            f"#{same_day_index:02d}"
        )

        images = dedupe_images(
            item.get(
                "images",
                [],
            )
        )

        result.append(
            Patch(
                title=item["title"],
                date_key=date_key,
                same_day_index=same_day_index,
                patch_id=patch_id,
                items=item["items"],
                images=images,
                body_hash=item["body_hash"],
                image_hash=build_image_hash(
                    images
                ),
                signature_text=build_signature_text(
                    item["items"]
                ),
                source_url=item["source_url"],
                source_name=item["source_name"],
            )
        )

    return result


# ============================================================
# 한국어 여부 판별
# ============================================================

def check_korean_patch(
    items: list[tuple[str, str]],
) -> LanguageCheck:
    texts = [
        clean_text(text)
        for _, text in items
        if clean_text(text)
    ]

    joined = "\n".join(texts)

    hangul_count = len(
        re.findall(
            r"[가-힣]",
            joined,
        )
    )

    latin_count = len(
        re.findall(
            r"[A-Za-z]",
            joined,
        )
    )

    alpha_count = (
        hangul_count
        + latin_count
    )

    meaningful_lines = [
        text
        for text in texts
        if len(
            re.findall(
                r"[가-힣A-Za-z]",
                text,
            )
        ) >= 3
    ]

    korean_lines = sum(
        1
        for text in meaningful_lines
        if re.search(
            r"[가-힣]",
            text,
        )
    )

    total_lines = len(
        meaningful_lines
    )

    hangul_ratio = (
        hangul_count / alpha_count
        if alpha_count
        else 0.0
    )

    if alpha_count < 10:
        return LanguageCheck(
            False,
            hangul_count,
            latin_count,
            hangul_ratio,
            korean_lines,
            total_lines,
            "본문이 너무 짧아 언어 판별 보류",
        )

    if (
        hangul_count >= 8
        and hangul_ratio >= 0.50
    ):
        return LanguageCheck(
            True,
            hangul_count,
            latin_count,
            hangul_ratio,
            korean_lines,
            total_lines,
            "한국어 본문으로 판별",
        )

    if (
        hangul_count >= 20
        and hangul_ratio >= 0.30
        and korean_lines >= 2
    ):
        return LanguageCheck(
            True,
            hangul_count,
            latin_count,
            hangul_ratio,
            korean_lines,
            total_lines,
            "한국어 본문으로 판별",
        )

    return LanguageCheck(
        False,
        hangul_count,
        latin_count,
        hangul_ratio,
        korean_lines,
        total_lines,
        "영문 또는 한국어 여부 불확실",
    )


def describe_language(
    result: LanguageCheck,
) -> str:
    return (
        f"한글={result.hangul_count}, "
        f"영문={result.latin_count}, "
        f"한글비율={result.hangul_ratio:.1%}, "
        f"한국어줄={result.korean_lines}/{result.total_lines}"
    )


# ============================================================
# 넥슨 1순위 소스
# ============================================================

def nexon_payload_articles(soup: BeautifulSoup) -> list[dict]:
    """Read identifiers from Nuxt's indexed JSON table without executing JS.

    The list's summary is truncated; patch text must come from the detail page.
    """
    script = soup.find("script", id="__NUXT_DATA__")
    if script is None:
        return []
    try:
        table = json.loads(script.get_text())
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(table, list):
        return []

    def scalar(reference: object) -> object:
        if type(reference) is int and 0 <= reference < len(table):
            value = table[reference]
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
        return None

    articles = []
    for entry in table:
        if not isinstance(entry, dict) or "newsNo" not in entry:
            continue
        article = {
            key: scalar(entry.get(key))
            for key in ("newsNo", "categoryId", "slug")
        }
        if (
            article["categoryId"] == 2
            and type(article["newsNo"]) is int
            and article["newsNo"] > 0
        ):
            articles.append(article)
    return articles


def extract_nexon_article_links(
    list_html: str,
) -> list[str]:
    soup = BeautifulSoup(
        list_html,
        "html.parser",
    )

    links: list[str] = []
    seen: set[str] = set()

    def add_link(href: str) -> None:
        parts = urlsplit(urljoin(NEXON_LIST_URL, href))
        if parts.netloc != urlsplit(NEXON_LIST_URL).netloc:
            return
        if not NEXON_ARTICLE_HREF_RE.search(parts.path):
            return
        # Numeric and slug routes can both point to the same article.
        article_id = parts.path.split("/")[3]
        if article_id not in seen and len(links) < NEXON_MAX_ARTICLES:
            seen.add(article_id)
            links.append(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        href = str(
            anchor.get(
                "href",
                "",
            )
        ).strip()

        add_link(href)

    # Current list cards are clickable divs. Their routes live in the hydration
    # table alongside unrelated news and events, which categoryId filters out.
    for article in nexon_payload_articles(soup):
        href = f"/news/patchnotes/{article['newsNo']}"
        if isinstance(article["slug"], str) and article["slug"]:
            href += "/" + quote(article["slug"], safe="")
        add_link(href)

    return links


def find_patch_title_node(
    area: Tag | BeautifulSoup,
) -> Tag | None:
    for tag in area.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        ]
    ):
        text = clean_text(
            tag.get_text(
                " ",
                strip=True,
            )
        )

        if is_patch_title(
            text
        ):
            return tag

    for tag in area.find_all(
        [
            "strong",
            "p",
            "div",
            "span",
        ]
    ):
        text = clean_text(
            tag.get_text(
                " ",
                strip=True,
            )
        )

        if (
            10 <= len(text) <= 140
            and is_patch_title(text)
        ):
            return tag

    return None


def is_nexon_metadata_text(
    text: str,
) -> bool:
    if not text:
        return True

    if text in {
        "news",
        "PATCHNOTE",
        "공지사항",
        "패치노트",
        "이벤트",
        "넥슨공지",
        "공유하기",
    }:
        return True

    if RELATIVE_TIME_RE.fullmatch(
        text
    ):
        return True

    if DOT_DATE_RE.fullmatch(
        text
    ):
        return True

    if IMAGE_TEXT_RE.fullmatch(
        text
    ):
        return True

    return False


def is_nexon_stop_text(
    text: str,
) -> bool:
    lowered = text.lower()

    if text in {
        "목록",
        "위로 이동",
        "Top",
        "Back to top",
    }:
        return True

    if (
        text.startswith(
            "이전글"
        )
        or text.startswith(
            "다음글"
        )
    ):
        return True

    if (
        "general discussion forum"
        in lowered
    ):
        return True

    return False


def is_developer_note(node: Tag) -> bool:
    """Preserve commentary in the original body, but mark it for summary exclusion."""
    return any(
        "PatchNotes-dev" in ancestor.get("class", [])
        for ancestor in (node, *node.parents)
        if isinstance(ancestor, Tag)
    )


def parse_nexon_article(
    html: str,
    source_url: str,
) -> dict | None:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    detail = soup.select_one(".news-detail")
    area = (
        detail
        or soup.find("article")
        or soup.find("main")
        or soup
    )

    title_node = area.select_one(".news-head .title") or find_patch_title_node(area)

    if title_node is None:
        return None

    title = clean_text(
        title_node.get_text(
            " ",
            strip=True,
        )
    )

    date_key = extract_date_key(
        title
    )

    if not date_key or not is_patch_title(title):
        return None

    items: list[
        tuple[str, str]
    ] = []

    images: list[str] = []
    raw_seen: list[str] = []

    node_names = [
        "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "img", "div",
    ]
    body = area.select_one(".news-body")
    if detail is not None and body is None:
        return None
    nodes = (
        body.find_all(node_names)
        if body is not None
        else title_node.find_all_next(node_names)
    )

    for node in nodes:
        if node is title_node:
            continue

        if not is_descendant_of(
            node,
            area,
        ):
            break

        tag_name = node.name
        if tag_name == "div":
            if "PatchNotesAbilityUpdate-name" not in node.get("class", []):
                continue
            tag_name = "h6"

        # A paragraph nested in an li is already represented by that list item.
        if tag_name == "p" and node.find_parent("li") is not None:
            continue

        if node.name == "img":
            image_url = extract_image_url(
                node,
                source_url,
            )

            if image_url:
                images.append(
                    image_url
                )

            continue

        text_node = node
        if node.name == "li" and node.find(["ul", "ol"]) is not None:
            # Keep the parent's label; child list items are visited separately.
            text_node = BeautifulSoup(str(node), "html.parser")
            for nested_list in text_node.find_all(["ul", "ol"]):
                nested_list.decompose()

        text = clean_text(
            text_node.get_text(
                " ",
                strip=True,
            )
        )

        if not text:
            continue

        if is_patch_title(
            text
        ):
            break

        if is_nexon_stop_text(
            text
        ):
            break

        if (
            text in {
                "패치 노트",
                "Live Patch Notes",
            }
            and items
        ):
            break

        if is_nexon_metadata_text(
            text
        ):
            continue

        if (
            raw_seen
            and raw_seen[-1] == text
        ):
            continue

        raw_seen.append(
            text
        )

        items.append(
            (
                "developer" if is_developer_note(node) else tag_name,
                text,
            )
        )

    if not items:
        return None

    images = dedupe_images(
        images
    )

    return {
        "title": title,
        "date_key": date_key,
        "items": items,
        "images": images,
        "body_hash": build_body_hash(
            title,
            items,
        ),
        "source_url": source_url,
        "source_name": "nexon",
    }


def fetch_nexon_patches() -> list[Patch]:
    print(
        "\n===== 1순위: 넥슨 공식 패치노트 확인 ====="
    )

    list_html = fetch_html(
        NEXON_LIST_URL
    )

    links = extract_nexon_article_links(
        list_html
    )

    if not links:
        raise RuntimeError(
            "넥슨 패치노트 목록에서 게시물 링크를 찾지 못했습니다."
        )

    print(
        f"넥슨 최근 게시물 링크 {len(links)}개 확인"
    )

    raw_patches: list[dict] = []

    for index, url in enumerate(
        links,
        start=1,
    ):
        try:
            html = fetch_html(
                url
            )

            raw = parse_nexon_article(
                html,
                url,
            )

            if raw is None:
                print(
                    f"[NEXON {index}] 패치 본문 파싱 실패 → 건너뜀"
                )

                continue

            print(
                f"[NEXON {index}] {raw['title']} "
                f"/ 이미지 {len(raw.get('images', []))}장"
            )

            raw_patches.append(
                raw
            )

        except requests.RequestException as exc:
            print(
                f"[NEXON {index}] 요청 실패: {exc}"
            )

    if not raw_patches:
        raise RuntimeError(
            "넥슨에서 파싱 가능한 패치노트를 찾지 못했습니다."
        )

    return assign_patch_ids(
        raw_patches
    )


# ============================================================
# Blizzard 2순위 소스
# ============================================================

def parse_blizzard_page(
    html: str,
    source_url: str,
) -> list[dict]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    area = (
        soup.find("main")
        or soup
    )

    title_nodes: list[Tag] = []

    for tag in area.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        ]
    ):
        text = clean_text(
            tag.get_text(
                " ",
                strip=True,
            )
        )

        if is_patch_title(
            text
        ):
            title_nodes.append(
                tag
            )

    raw_patches: list[dict] = []

    for title_node in title_nodes:
        title = clean_text(
            title_node.get_text(
                " ",
                strip=True,
            )
        )

        date_key = extract_date_key(
            title
        )

        if not date_key:
            continue

        title_level = (
            heading_level(
                title_node.name
            )
            or 3
        )

        items: list[
            tuple[str, str]
        ] = []

        images: list[str] = []
        raw_seen: list[str] = []

        for node in title_node.find_all_next(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "p",
                "li",
                "img",
            ]
        ):
            if node is title_node:
                continue

            if not is_descendant_of(
                node,
                area,
            ):
                break

            if node.name == "img":
                image_url = extract_image_url(
                    node,
                    source_url,
                )

                if image_url:
                    images.append(
                        image_url
                    )

                continue

            text = clean_text(
                node.get_text(
                    " ",
                    strip=True,
                )
            )

            if not text:
                continue

            if is_patch_title(
                text
            ):
                break

            current_level = heading_level(
                node.name
            )

            if (
                current_level is not None
                and current_level < title_level
            ):
                break

            lowered = text.lower()

            if text in {
                "위로 이동",
                "Top",
                "Top of post",
                "Back to top",
                "패치 노트의 처음으로 돌아가기",
            }:
                continue

            if (
                "general discussion forum"
                in lowered
            ):
                break

            if (
                "bug report forum"
                in lowered
            ):
                break

            if (
                "기술 지원 토론장"
                in text
                or "버그 제보 토론장"
                in text
            ):
                break

            if (
                text
                in {
                    "패치 노트",
                    "Live Patch Notes",
                }
                and items
            ):
                break

            if IMAGE_TEXT_RE.fullmatch(
                text
            ):
                continue

            if (
                raw_seen
                and raw_seen[-1] == text
            ):
                continue

            raw_seen.append(
                text
            )

            items.append(
                (
                    "developer" if is_developer_note(node) else node.name,
                    text,
                )
            )

        if not items:
            continue

        images = dedupe_images(
            images
        )

        raw_patches.append(
            {
                "title": title,
                "date_key": date_key,
                "items": items,
                "images": images,
                "body_hash": build_body_hash(
                    title,
                    items,
                ),
                "source_url": source_url,
                "source_name": "blizzard",
            }
        )

    return raw_patches


def fetch_blizzard_patches() -> list[Patch]:
    print(
        "\n===== 2순위: Blizzard 한국 패치노트 확인 ====="
    )

    raw_all: list[dict] = []
    seen_raw: set[
        tuple[str, str]
    ] = set()

    errors: list[str] = []

    for url in candidate_blizzard_urls():
        try:
            html = fetch_html(
                url
            )

            raws = parse_blizzard_page(
                html,
                url,
            )

            print(
                f"Blizzard 패치 블록 {len(raws)}개: {url}"
            )

            for raw in raws:
                dedupe_key = (
                    raw["title"],
                    raw["body_hash"],
                )

                if (
                    dedupe_key
                    in seen_raw
                ):
                    continue

                seen_raw.add(
                    dedupe_key
                )

                raw_all.append(
                    raw
                )

        except requests.RequestException as exc:
            errors.append(
                f"{url}: {exc}"
            )

            print(
                f"Blizzard 요청 실패: {url}: {exc}"
            )

    if not raw_all:
        try:
            html = fetch_html(
                BLIZZARD_BASE_URL
            )

            raw_all.extend(
                parse_blizzard_page(
                    html,
                    BLIZZARD_BASE_URL,
                )
            )

        except requests.RequestException as exc:
            errors.append(
                f"{BLIZZARD_BASE_URL}: {exc}"
            )

    if not raw_all:
        raise RuntimeError(
            "Blizzard 패치노트를 찾지 못했습니다.\n"
            + "\n".join(
                errors
            )
        )

    patches = assign_patch_ids(
        raw_all
    )

    for patch in patches:
        print(
            f"[BLIZZARD] {patch.patch_id} "
            f"/ 이미지 {len(patch.images)}장"
        )

    return patches


# ============================================================
# 두 소스 중복 제거
# ============================================================

def choose_patches(
    nexon_patches: list[Patch],
    blizzard_patches: list[Patch],
) -> list[Patch]:
    """
    중복 방지 정책:

    1. 넥슨이 정상 동작하면 넥슨을 한국어 패치의 기준 소스로 사용.
    2. Blizzard 패치는 '넥슨 최신 날짜보다 더 최신 날짜'일 때만 보조 추적.
    3. 같은 날짜 또는 과거 날짜의 Blizzard 패치는 넥슨과 겹칠 가능성이
       있으므로 전송 후보에서 제외.
    4. 넥슨 자체가 실패했을 때만 Blizzard가 단독 소스로 동작.

    이 정책으로 같은 패치가 NEXON + BLIZZARD 두 번 올라가는 것을 막습니다.
    """

    if not nexon_patches:
        print(
            "넥슨 데이터 없음 → Blizzard 단독 보조 모드"
        )

        return sorted(
            blizzard_patches,
            key=lambda patch: (
                patch.date_key,
                patch.same_day_index,
            ),
        )

    selected: dict[
        str,
        Patch,
    ] = {
        patch.patch_id: patch
        for patch in nexon_patches
    }

    latest_nexon_date = max(
        patch.date_key
        for patch in nexon_patches
    )

    print(
        f"넥슨 최신 패치 날짜: {latest_nexon_date}"
    )

    for patch in blizzard_patches:
        # 같은 날짜 및 과거는 전부 NEXON에 맡김.
        if (
            patch.date_key
            <= latest_nexon_date
        ):
            print(
                f"[BLIZZARD 중복/과거 제외] "
                f"{patch.patch_id} {patch.title}"
            )

            continue

        selected[
            patch.patch_id
        ] = patch

        print(
            f"[BLIZZARD 최신 보조 채택] "
            f"{patch.patch_id} {patch.title}"
        )

    return sorted(
        selected.values(),
        key=lambda patch: (
            patch.date_key,
            patch.same_day_index,
        ),
    )


def fetch_recent_patches() -> list[Patch]:
    nexon_patches: list[Patch] = []
    blizzard_patches: list[Patch] = []

    nexon_error: Exception | None = None
    blizzard_error: Exception | None = None

    try:
        nexon_patches = fetch_nexon_patches()

    except (
        requests.RequestException,
        RuntimeError,
    ) as exc:
        nexon_error = exc

        print(
            f"넥슨 소스 실패: {exc}"
        )

    try:
        blizzard_patches = fetch_blizzard_patches()

    except (
        requests.RequestException,
        RuntimeError,
    ) as exc:
        blizzard_error = exc

        print(
            f"Blizzard 소스 실패: {exc}"
        )

    if (
        not nexon_patches
        and not blizzard_patches
    ):
        raise RuntimeError(
            "넥슨과 Blizzard 두 소스 모두 패치 확인에 실패했습니다.\n"
            f"NEXON: {nexon_error}\n"
            f"BLIZZARD: {blizzard_error}"
        )

    patches = choose_patches(
        nexon_patches,
        blizzard_patches,
    )

    print(
        f"\n최종 추적 대상 패치: {len(patches)}개"
    )

    for patch in patches:
        print(
            f"  - [{patch.source_name.upper()}] "
            f"{patch.patch_id} "
            f"/ 이미지 {len(patch.images)}장 "
            f"/ {patch.title}"
        )

    return patches



# ============================================================
# 자동 요약 카드 생성
# ============================================================

def _normalize_heading(value: str) -> str:
    return clean_text(value).lower().strip(" :：-–—")


def _is_generic_section(value: str) -> bool:
    normalized = _normalize_heading(value)

    if normalized in GENERIC_SECTION_WORDS:
        return True

    generic_fragments = (
        "패치 노트",
        "patch notes",
        "업데이트",
        "update",
        "버그 수정",
        "bug fix",
    )

    return any(
        fragment in normalized
        for fragment in generic_fragments
    ) and len(normalized) < 40


def _role_from_heading(value: str) -> str | None:
    normalized = _normalize_heading(value)

    for key, role in ROLE_ALIASES.items():
        if normalized == key:
            return role

    return None


def _looks_like_change_line(value: str) -> bool:
    text = clean_text(value)

    if not text:
        return False

    if text.startswith(("개발자의 의견", "개발자 의견", "Developer Comments")):
        return False

    markers = (
        "→",
        "->",
        "증가",
        "감소",
        "증가했습니다",
        "감소했습니다",
        "상향",
        "하향",
        "재사용 대기",
        "지속 시간",
        "지속시간",
        "공격력",
        "피해",
        "생명력",
        "방어력",
        "치유",
        "사거리",
        "속도",
        "범위",
        "추가",
        "제거",
        "변경",
        "수정",
        "시각 효과",
    )

    return any(
        marker in text
        for marker in markers
    )


def _extract_numeric_direction(text: str) -> int:
    """
    반환:
      1  -> 값 증가
     -1  -> 값 감소
      0  -> 숫자 방향 판별 불가
    """
    match = CHANGE_NUMBER_RE.search(
        text
    )

    if match:
        units = {"m": "미터", "m/s": "미터/초"}
        before_unit = units.get(match.group(2), match.group(2))
        after_unit = units.get(match.group(4), match.group(4))
        if before_unit and after_unit and before_unit != after_unit:
            # Do not compare raw magnitudes across units (e.g. 1s -> 500ms).
            return 0
        before = float(
            match.group(1).replace(",", "")
        )

        after = float(
            match.group(3).replace(",", "")
        )

        if after > before:
            return 1

        if after < before:
            return -1
        return 0

    # 'A에서 B로 증가/감소'처럼 정규식이 안 잡히는 문장 보조
    if "증가" in text:
        return 1

    if "감소" in text:
        return -1

    return 0


def classify_change_line(text: str) -> str:
    """
    buff / nerf / adjust

    유료 AI 없이 규칙 기반으로 판단합니다.
    애매한 변화는 무리하게 상향/하향으로 단정하지 않고 '조정'으로 보냅니다.
    """
    context = clean_text(text).lower()
    normalized = context
    # Ability names are context, not evidence of a buff (e.g. '강화 사격:').
    normalized = normalized.rsplit(":", 1)[-1].strip()
    if re.search(r"(?:증가|감소|상향|하향|강화|약화).{0,12}(?:않|아니|못)", normalized):
        return "adjust"
    if len(CHANGE_NUMBER_RE.findall(normalized)) > 1:
        # Multiple metrics can have opposite benefits; retain a neutral label.
        return "adjust"
    # '사거리 증가가 75%에서 40%로 감소' is one change, not two directions.
    direction_verbs = re.findall(r"(?:증가|감소)(?:했|하였|하|되었|됩|되)", normalized)
    if len(direction_verbs) > 1:
        return "adjust"
    direction = _extract_numeric_direction(
        normalized
    )

    numeric = re.search(r"[-+]?\d", normalized)
    metric = normalized[:numeric.start()] if numeric else normalized

    # Presentation-only changes have no numeric combat benefit. Keep their row
    # visible, without overriding a hero's otherwise clear buff/nerf category.
    if re.search(r"시각 효과|음향|효과음|카메라|1인칭.*애니메이션", normalized):
        if not re.search(r"공격력|피해|치유|재사용 대기|생명력|비용|탄약|재생률", normalized):
            return "neutral"

    if re.search(r"최대 분산도에 도달하기까지의 탄환 수", metric):
        return "buff" if direction > 0 else "nerf" if direction < 0 else "adjust"

    # A longer attack animation is a cost; a longer shield/drone/invulnerability
    # effect is a benefit. Unknown duration contexts remain 'adjust'.
    if "지속 시간" in metric and not any(key in metric for key in LOWER_IS_BETTER_KEYWORDS):
        if re.search(r"방벽|보호막|무적|앵커 드론|망령화|파워 매트릭스|시야 이탈", context):
            return "buff" if direction > 0 else "nerf" if direction < 0 else "adjust"

    # More reduction of a cost is beneficial, unlike increasing the cost itself.
    cost_reduction = re.search(r"(?:재사용 대기시간|궁극기 (?:충전 )?비용)\s*감소(?:량|율)?(?:이|가)?\s*$", metric)
    if cost_reduction:
        return "buff" if direction > 0 else "nerf" if direction < 0 else "adjust"

    lower_is_better = any(
        keyword in metric
        for keyword in LOWER_IS_BETTER_KEYWORDS
    )

    # '회복 시간' is a cost, while bare '회복' is a benefit.
    higher_context = metric
    for keyword in LOWER_IS_BETTER_KEYWORDS:
        higher_context = higher_context.replace(keyword, " ")

    higher_is_better = any(
        keyword in higher_context
        for keyword in HIGHER_IS_BETTER_KEYWORDS
    )

    # '분산도의 범위' describes spread, not beneficial ability range.
    if re.search(r"분산도(?:의)? 범위", metric):
        higher_is_better = False
    if lower_is_better and (higher_is_better or re.search(r"감소(?:량|율| 효과| 비율)", metric)):
        return "adjust"

    if direction != 0:
        if lower_is_better:
            return (
                "buff"
                if direction < 0
                else "nerf"
            )

        if higher_is_better:
            return (
                "buff"
                if direction > 0
                else "nerf"
            )

    # 명시적인 표현이 있는 경우
    if re.search(r"(?:상향|강화)(?:되었습니다|됩니다|했습니다|합니다|됨|함)(?=$|[\s.!?])", normalized):
        return "buff"

    if re.search(r"(?:하향|약화)(?:되었습니다|됩니다|했습니다|합니다|됨|함)(?=$|[\s.!?])", normalized):
        return "nerf"

    return "adjust"


def extract_balance_summary(
    patch: Patch,
) -> list[dict]:
    """
    Patch.items의 제목 계층을 이용해
    역할 -> 영웅 -> 변경 문장 구조를 만듭니다.
    """
    current_role: str | None = None
    current_hero: str | None = None
    current_ability: str | None = None
    hero_level: int | None = None
    in_hero_section = False
    current_mode: str | None = "일반전"
    heroes: dict[tuple[str, str, str], list[str]] = {}

    for tag_name, raw_text in patch.items:
        text = clean_text(raw_text)
        if not text:
            continue
        if tag_name == "developer":
            continue
        level = heading_level(tag_name)
        if level is not None:
            role = _role_from_heading(text)
            if role:
                if current_mode is None:
                    continue
                current_role = role
                current_hero = current_ability = None
                hero_level = None
                in_hero_section = True
                continue
            if _is_generic_section(text):
                current_role = current_hero = current_ability = None
                hero_level = None
                if "스타디움" in text or "stadium" in text.lower():
                    current_mode = "스타디움"
                elif "영웅" in text or "hero" in text.lower():
                    current_mode = "일반전"
                else:
                    current_mode = None
                in_hero_section = current_mode is not None
                continue
            if current_hero and hero_level is not None and level > hero_level:
                current_ability = text
                continue
            # Nexon hotfixes can omit role headings but retain h5 hero names.
            if in_hero_section and 1 <= len(text) <= 36 and (
                current_role is not None or level == 5
            ):
                current_hero = text
                current_ability = None
                hero_level = level
                heroes.setdefault((current_mode, current_role or "영웅", current_hero), [])
            else:
                current_hero = current_ability = None
                hero_level = None
            continue
        if current_hero and tag_name in {"p", "li"} and len(text) <= 70 and re.search(r"[-–].*(?:특전|파워|아이템)$", text):
            current_ability = text
            continue
        # Structured hero list items are changes even without words like
        # increase/decrease (restorations, conditional effects, new mechanics).
        if current_hero and (_looks_like_change_line(text) or (
                tag_name == "li" and text not in {"기술 조정", "변경 사항"})):
            line = f"{current_ability}: {text}" if current_ability else text
            lines = heroes.setdefault((current_mode, current_role or "영웅", current_hero), [])
            if line not in lines:
                lines.append(line)

    result: list[dict] = []

    for (
        mode,
        role,
        hero,
    ), changes in heroes.items():
        if not changes:
            continue

        classifications = [
            classify_change_line(
                line
            )
            for line in changes
        ]

        unique_classes = set(
            classifications
        ) - {"neutral"}

        if unique_classes == {
            "buff"
        }:
            category = "buff"

        elif unique_classes == {
            "nerf"
        }:
            category = "nerf"

        else:
            category = "adjust"

        result.append(
            {
                "role": role,
                "hero": hero,
                "mode": mode,
                "changes": changes,
                "category": category,
            }
        )

    return result


def extract_generic_summary(
    patch: Patch,
) -> list[str]:
    """
    영웅 밸런스가 아닌 패치도 완전히 빈 요약이 되지 않도록
    짧은 핵심 변경 문장을 추출합니다.
    """
    result: list[str] = []

    for tag_name, raw_text in patch.items:
        text = clean_text(
            raw_text
        )

        if not text:
            continue

        if tag_name not in {
            "li",
            "p",
        }:
            continue

        if len(text) > 180:
            continue

        if text in result:
            continue

        # 너무 일반적인 안내 문구는 제외
        lowered = text.lower()

        if any(
            marker in lowered
            for marker in (
                "리플레이 코드는",
                "replay codes",
                "패치입니다",
            )
        ):
            continue

        result.append(
            text
        )

        if (
            len(result)
            >= SUMMARY_GENERIC_MAX_ITEMS
        ):
            break

    return result


def _find_font_path(
    bold: bool,
) -> str:
    candidates = (
        [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Bold.otf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        ]
        if bold
        else
        [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        ]
    )

    windows_fonts = Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts"
    candidates.append(str(windows_fonts / ("malgunbd.ttf" if bold else "malgun.ttf")))
    candidates.append("/System/Library/Fonts/AppleSDGothicNeo.ttc")

    for candidate in candidates:
        if Path(
            candidate
        ).exists():
            return candidate

    # 마지막 fallback. 한글 폰트가 아니면 카드 생성은 중단합니다.
    raise RuntimeError(
        "한글 폰트를 찾지 못했습니다. "
        "Linux에서는 fonts-noto-cjk, Windows에서는 맑은 고딕이 필요합니다."
    )


def prepare_card_data(patch: Patch) -> tuple[list[dict], list[dict]]:
    entries = []
    for entry in extract_balance_summary(patch):
        changes = [
            {**compact_change(line), "category": classify_change_line(line)}
            for line in entry["changes"]
        ]
        entries.append({**entry, "changes": changes})
    general = []
    if not entries:
        general = [
            {**compact_change(line), "category": "general"}
            for line in extract_generic_summary(patch)
        ]
    return entries, general


def generate_summary_cards(patch: Patch, output_dir: Path) -> list[Path]:
    entries, general = prepare_card_data(patch)
    return render_cards(
        patch_id=patch.patch_id,
        title=patch.title,
        date_key=patch.date_key,
        entries=entries,
        general_changes=general,
        output_dir=output_dir,
        font_path=_find_font_path,
    )


def send_summary_cards(
    webhook_url: str,
    patch: Patch,
    old_message_ids: list[str] | None = None,
    on_progress: Callable[[list[str]], None] | None = None,
) -> list[str]:
    """Update cards in place and checkpoint each acknowledged upload."""
    message_ids = list(old_message_ids or [])
    with tempfile.TemporaryDirectory(prefix="ow-summary-") as temp_dir:
        paths = generate_summary_cards(patch, Path(temp_dir))
        for index, path in enumerate(paths):
            payload = {
                "content": f"**자동 요약 카드 [{index + 1}/{len(paths)}]**",
                "allowed_mentions": {"parse": []},
                "attachments": [{"id": 0, "filename": path.name}],
            }
            existing = index < len(message_ids)
            endpoint = (discord_message_url(webhook_url, message_ids[index])
                        if existing else webhook_base_url(webhook_url) + "?wait=true")
            with path.open("rb") as file_handle:
                response = discord_request(requests.patch if existing else requests.post,
                    endpoint,
                    data={"payload_json": json.dumps(payload, ensure_ascii=False)},
                    files={"files[0]": (path.name, file_handle, "image/png")},
                    timeout=60,
                )
                if existing and response.status_code == 404:
                    file_handle.seek(0)
                    response = discord_request(requests.post,
                        webhook_base_url(webhook_url) + "?wait=true",
                        data={"payload_json": json.dumps(payload, ensure_ascii=False)},
                        files={"files[0]": (path.name, file_handle, "image/png")},
                        timeout=60,
                    )
            response.raise_for_status()
            message_id = str(response.json().get("id", "")).strip()
            if not message_id:
                raise RuntimeError("Discord가 요약 카드 message_id를 반환하지 않았습니다.")
            if existing:
                message_ids[index] = message_id
            else:
                message_ids.append(message_id)
            if on_progress:
                on_progress(message_ids.copy())
            time.sleep(1)

        while len(message_ids) > len(paths):
            delete_discord_message(webhook_url, message_ids[-1])
            message_ids.pop()
            if on_progress:
                on_progress(message_ids.copy())
        return message_ids


def refresh_summary_cards(
    webhook_url: str,
    patch: Patch,
    old_summary_message_ids: list[str],
    on_progress: Callable[[list[str]], None] | None = None,
) -> list[str]:
    return send_summary_cards(webhook_url, patch, old_summary_message_ids, on_progress)


# ============================================================
# Discord 텍스트 + 이미지 Payload 생성
# ============================================================


def format_summary(
    patch: Patch,
) -> list[str]:
    source_label = (
        "넥슨 공식"
        if patch.source_name == "nexon"
        else "Blizzard 공식"
    )

    lines = [
        f"# {patch.title}",
        f"출처: {source_label}",
        f"<{patch.source_url}>",
        "",
    ]

    previous = ""

    for tag_name, text in patch.items:
        if text == previous:
            continue

        previous = text

        if tag_name in {
            "h1",
            "h2",
            "h3",
            "h4",
        }:
            line = (
                f"## {text}"
            )

        elif tag_name == "h5":
            line = (
                f"### {text}"
            )

        elif tag_name == "h6":
            line = (
                f"**{text}**"
            )

        elif tag_name == "li":
            line = (
                f"- {text}"
            )

        elif tag_name in {"p", "developer"}:
            line = text

        else:
            continue

        if (
            not lines
            or line != lines[-1]
        ):
            lines.append(
                line
            )

    return lines


def split_text_messages(
    lines: list[str],
) -> list[str]:
    chunks: list[str] = []
    current = ""

    for line in lines:
        remaining = line

        while (
            len(remaining)
            > MESSAGE_LIMIT
        ):
            piece = remaining[
                :MESSAGE_LIMIT
            ]

            if current:
                chunks.append(
                    current
                )
                current = ""

            chunks.append(
                piece
            )

            remaining = remaining[
                MESSAGE_LIMIT:
            ]

        candidate = (
            f"{current}\n{remaining}".strip()
            if current
            else remaining
        )

        if (
            len(candidate)
            <= MESSAGE_LIMIT
        ):
            current = candidate

            continue

        if current:
            chunks.append(
                current
            )

        current = remaining

    if current:
        chunks.append(
            current
        )

    if (
        len(chunks)
        > MAX_TEXT_MESSAGES
    ):
        chunks = chunks[
            :MAX_TEXT_MESSAGES
        ]

        suffix = (
            "\n\n※ 본문이 매우 길어 일부 텍스트만 표시했습니다. "
            "전체 내용은 공식 링크에서 확인하세요."
        )

        chunks[-1] = (
            chunks[-1][
                :(
                    MESSAGE_LIMIT
                    - len(suffix)
                )
            ]
            + suffix
        )

    return chunks


def build_discord_payloads(
    patch: Patch,
) -> list[dict]:
    """제목·공식 링크·본문만 전송합니다. 자동 요약 카드는 별도 생성합니다."""
    payloads: list[dict] = []

    text_lines = format_summary(
        patch
    )

    for chunk in split_text_messages(
        text_lines
    ):
        payloads.append(
            {
                "content": chunk,
                "embeds": [],
            }
        )

    if not payloads:
        payloads.append(
            {
                "content": (
                    f"# {patch.title}\n"
                    f"<{patch.source_url}>"
                ),
                "embeds": [],
            }
        )

    return payloads


def decorate_payloads(
    payloads: list[dict],
) -> list[dict]:
    total = len(
        payloads
    )

    decorated: list[dict] = []

    for index, payload in enumerate(
        payloads,
        start=1,
    ):
        content = str(
            payload.get(
                "content",
                "",
            )
        )

        embeds = list(
            payload.get(
                "embeds",
                [],
            )
        )

        if total > 1:
            prefix = (
                f"**[{index}/{total}]**\n"
            )

            content = (
                prefix
                + content[
                    :(
                        MESSAGE_LIMIT
                        - len(prefix)
                    )
                ]
            )

        else:
            content = content[
                :MESSAGE_LIMIT
            ]

        decorated.append(
            {
                "content": content,
                "embeds": embeds[
                    :DISCORD_EMBEDS_PER_MESSAGE
                ],
            }
        )

    return decorated


# ============================================================
# Discord 전송 / 수정 / 삭제
# ============================================================

def discord_request(request, url: str, **kwargs):
    """Retry confirmed rate-limit rejections only, preserving multipart bytes."""
    streams = [(part[1], part[1].tell()) for part in kwargs.get("files", {}).values()]
    for attempt in range(5):
        for stream, position in streams:
            stream.seek(position)
        response = request(url, **kwargs)
        if response.status_code != 429 or attempt == 4:
            return response
        try:
            body = response.json()
        except ValueError:
            body = {}
        candidates = [response.headers.get("Retry-After"),
                      body.get("retry_after") if isinstance(body, dict) else None]
        delays = []
        for candidate in candidates:
            try:
                delay = float(candidate)
            except (ValueError, TypeError):
                continue
            if math.isfinite(delay) and delay >= 0:
                delays.append(delay)
        delay = max(delays) if delays else 2 ** attempt
        delay = max(delay, 0.1)
        response.close()
        print(f"Discord 요청 제한 → {delay:g}초 대기 후 재시도 ({attempt + 1}/4)")
        time.sleep(delay)


def webhook_base_url(
    webhook_url: str,
) -> str:
    parts = urlsplit(
        webhook_url.strip()
    )

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path.rstrip("/"),
            "",
            "",
        )
    )


def send_to_discord(
    webhook_url: str,
    payloads: list[dict],
    on_progress: Callable[[list[str]], None] | None = None,
) -> list[str]:
    return sync_discord_messages(webhook_url, [], payloads, on_progress)


def discord_message_url(
    webhook_url: str,
    message_id: str,
) -> str:
    return (
        webhook_base_url(
            webhook_url
        )
        + f"/messages/{message_id}"
    )


def edit_discord_message(
    webhook_url: str,
    message_id: str,
    payload: dict,
) -> None:
    response = discord_request(requests.patch,
        discord_message_url(
            webhook_url,
            message_id,
        ),
        json={
            "content": payload[
                "content"
            ],
            "embeds": payload[
                "embeds"
            ],
            "allowed_mentions": {
                "parse": []
            },
        },
        timeout=30,
    )

    response.raise_for_status()


def delete_discord_message(
    webhook_url: str,
    message_id: str,
) -> None:
    response = discord_request(requests.delete,
        discord_message_url(
            webhook_url,
            message_id,
        ),
        timeout=30,
    )

    if response.status_code == 404:
        return

    response.raise_for_status()


def sync_discord_messages(
    webhook_url: str,
    old_message_ids: list[str],
    new_payloads: list[dict],
    on_progress: Callable[[list[str]], None] | None = None,
) -> list[str]:
    """Retry edits safely and retain every acknowledged new message ID."""
    message_ids = [str(item) for item in old_message_ids if str(item).strip()]
    payloads = decorate_payloads(new_payloads)
    for index, payload in enumerate(payloads):
        existing = index < len(message_ids)
        if existing:
            try:
                edit_discord_message(webhook_url, message_ids[index], payload)
                time.sleep(0.5)
                continue
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code != 404:
                    raise
        response = discord_request(requests.post,
            webhook_base_url(webhook_url) + "?wait=true",
            json={
                "username": "오버워치 패치 알림",
                "content": payload["content"],
                "embeds": payload["embeds"],
                "allowed_mentions": {"parse": []},
            },
            timeout=30,
        )
        response.raise_for_status()
        message_id = str(response.json().get("id", "")).strip()
        if not message_id:
            raise RuntimeError("Discord가 message_id를 반환하지 않았습니다.")
        if existing:
            message_ids[index] = message_id
        else:
            message_ids.append(message_id)
        if on_progress:
            on_progress(message_ids.copy())
        time.sleep(1)

    while len(message_ids) > len(payloads):
        delete_discord_message(webhook_url, message_ids[-1])
        message_ids.pop()
        if on_progress:
            on_progress(message_ids.copy())
        time.sleep(0.5)
    return message_ids


# ============================================================
# state.json
# ============================================================


def empty_state() -> dict:
    return {
        "version": 8,
        "patches": {},
    }


def load_state() -> dict:
    if not STATE_FILE.exists():
        return empty_state()

    try:
        data = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            data,
            dict,
        ):
            return empty_state()

        data.setdefault(
            "patches",
            {},
        )

        if not isinstance(
            data["patches"],
            dict,
        ):
            data["patches"] = {}

        for patch_id, record in data[
            "patches"
        ].items():
            if not isinstance(
                record,
                dict,
            ):
                continue

            record.setdefault(
                "patch_id",
                patch_id,
            )

            record.setdefault(
                "discord_message_ids",
                [],
            )

            record.setdefault(
                "summary_message_ids",
                [],
            )

            record.setdefault(
                "summary_card_version",
                0,
            )

        return data

    except (
        json.JSONDecodeError,
        OSError,
    ):
        return empty_state()


def make_record(
    patch: Patch,
    status: str,
) -> dict:
    now = datetime.now(
        timezone.utc
    ).isoformat()

    record = {
        "patch_id": patch.patch_id,
        "date_key": patch.date_key,
        "same_day_index": patch.same_day_index,
        "title": patch.title,
        "body_hash": patch.body_hash,
        "image_hash": patch.image_hash,
        "image_count": len(
            patch.images
        ),
        "signature_text": patch.signature_text,
        "source_url": patch.source_url,
        "source_name": patch.source_name,
        "first_seen_source": patch.source_name,
        "status": status,
        "discord_message_ids": [],
        "summary_message_ids": [],
        "summary_card_version": 0,
        "first_seen_utc": now,
        "last_seen_utc": now,
    }

    if status == "sent":
        record[
            "sent_at_utc"
        ] = now

    return record


def save_state(
    state: dict,
) -> None:
    state["version"] = 8

    state[
        "updated_at_utc"
    ] = datetime.now(
        timezone.utc
    ).isoformat()

    patches = state.get(
        "patches",
        {},
    )

    if not isinstance(
        patches,
        dict,
    ):
        patches = {}

    records = [
        record
        for record in patches.values()
        if isinstance(
            record,
            dict,
        )
        and record.get(
            "patch_id"
        )
    ]

    records.sort(
        key=lambda record: (
            record.get(
                "date_key",
                "",
            ),
            int(
                record.get(
                    "same_day_index",
                    0,
                )
                or 0
            ),
        )
    )

    records = records[
        -250:
    ]

    state["patches"] = {
        record["patch_id"]: record
        for record in records
    }

    temporary_path = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    try:
        temporary_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        os.replace(temporary_path, STATE_FILE)
    finally:
        temporary_path.unlink(missing_ok=True)



def migrate_legacy_state(
    state: dict,
    patches: list[Patch],
) -> bool:
    if state.get(
        "patches"
    ):
        return False

    old_title = str(
        state.get(
            "title",
            "",
        )
    )

    old_hash = str(
        state.get(
            "hash",
            "",
        )
    )

    if (
        not old_title
        and not old_hash
    ):
        return False

    old_date = extract_date_key(
        old_title
    )

    state[
        "patches"
    ] = {}

    migrated = False

    if old_date:
        for patch in patches:
            if (
                patch.date_key
                <= old_date
            ):
                record = make_record(
                    patch,
                    "sent",
                )

                record[
                    "migration"
                ] = (
                    "legacy_baseline"
                )

                state[
                    "patches"
                ][
                    patch.patch_id
                ] = record

                migrated = True

    elif old_hash:
        for patch in patches:
            if (
                patch.body_hash
                == old_hash
            ):
                record = make_record(
                    patch,
                    "sent",
                )

                record[
                    "migration"
                ] = (
                    "legacy_hash_match"
                )

                state[
                    "patches"
                ][
                    patch.patch_id
                ] = record

                migrated = True

    return migrated


def initialize_fresh_state(
    state: dict,
    patches: list[Patch],
) -> None:
    records = state.setdefault(
        "patches",
        {},
    )

    if records:
        return

    if not patches:
        return

    newest_date = max(
        patch.date_key
        for patch in patches
    )

    for patch in patches:
        if (
            patch.date_key
            < newest_date
            or not SEND_ON_FIRST_RUN
        ):
            record = make_record(
                patch,
                "sent",
            )

            record[
                "migration"
            ] = (
                "fresh_install_baseline"
            )

            records[
                patch.patch_id
            ] = record


def update_seen_record(
    record: dict,
    patch: Patch,
    *,
    update_hashes: bool = True,
) -> None:
    record[
        "title"
    ] = patch.title

    if update_hashes:
        record[
            "body_hash"
        ] = patch.body_hash

        record[
            "image_hash"
        ] = patch.image_hash

        record[
            "image_count"
        ] = len(
            patch.images
        )

    record[
        "signature_text"
    ] = patch.signature_text

    record[
        "source_url"
    ] = patch.source_url

    record[
        "source_name"
    ] = patch.source_name

    record[
        "last_seen_utc"
    ] = datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# NEXON ↔ BLIZZARD 추가 중복 안전장치
# ============================================================

def date_distance_days(
    left: str,
    right: str,
) -> int:
    try:
        left_dt = datetime.strptime(
            left,
            "%Y-%m-%d",
        )

        right_dt = datetime.strptime(
            right,
            "%Y-%m-%d",
        )

        return abs(
            (
                left_dt
                - right_dt
            ).days
        )

    except ValueError:
        return 999


def find_cross_source_duplicate(
    patch: Patch,
    records: dict,
) -> tuple[str, dict] | None:
    """
    넥슨 장애 중 Blizzard로 먼저 전송된 뒤,
    넥슨이 하루 차이 날짜로 같은 한국어 내용을 올리는 예외 상황을 방지합니다.

    - 서로 다른 소스
    - 날짜 차이 0~1일
    - 본문 구조/내용 유사도 매우 높음

    조건에서만 중복으로 판단합니다.
    """
    if not patch.signature_text:
        return None

    for other_id, record in records.items():
        if not isinstance(
            record,
            dict,
        ):
            continue

        if record.get(
            "status"
        ) != "sent":
            continue

        other_source = str(
            record.get(
                "source_name",
                "",
            )
        )

        if (
            not other_source
            or other_source
            == patch.source_name
        ):
            continue

        other_date = str(
            record.get(
                "date_key",
                "",
            )
        )

        if (
            date_distance_days(
                patch.date_key,
                other_date,
            )
            > 1
        ):
            continue

        other_signature = str(
            record.get(
                "signature_text",
                "",
            )
        )

        if not other_signature:
            continue

        similarity = SequenceMatcher(
            None,
            patch.signature_text,
            other_signature,
        ).ratio()

        if similarity >= 0.94:
            return (
                other_id,
                record,
            )

    return None


# ============================================================
# 패치 처리
# ============================================================

def summary_is_current(record: dict, patch: Patch) -> bool:
    return (
        record.get("summary_card_version", 0) == SUMMARY_CARD_VERSION
        and record.get("summary_body_hash") == patch.body_hash
        and (bool(record.get("summary_message_ids")) or record.get("summary_empty") is True)
    )


def process_patch(patch: Patch, state: dict, webhook_url: str) -> str:
    records = state.setdefault("patches", {})
    record = records.get(patch.patch_id)
    language = check_korean_patch(patch.items)
    print(f"\n[{patch.source_name.upper()} / {patch.patch_id}] {patch.title}")
    print(f"언어 판별: {language.reason} ({describe_language(language)})")

    if record is None:
        duplicate = find_cross_source_duplicate(patch, records)
        if duplicate is not None:
            original_id, _ = duplicate
            record = make_record(patch, "duplicate_source")
            record["duplicate_of"] = original_id
            records[patch.patch_id] = record
            print(f"다른 공식 소스에서 전송한 패치 → 중복 제외 ({original_id})")
            return "duplicate_source"

    if record and record.get("status") == "duplicate_source":
        update_seen_record(record, patch)
        return "duplicate_source"

    was_sent = bool(record and record.get("status") == "sent")
    if not language.is_korean:
        if record is None:
            record = make_record(patch, "pending_korean")
            records[patch.patch_id] = record
        else:
            # Do not discard a completed/partial Korean delivery while English is shown.
            update_seen_record(record, patch, update_hashes=False)
        record["language_reason"] = language.reason
        record["pending_body_hash"] = patch.body_hash
        record["pending_image_hash"] = patch.image_hash
        print("영문 또는 불확실 → Discord 전송 안 함 / 한국어판 대기")
        return "pending_korean"

    if record is None:
        record = make_record(patch, "sending")
        records[patch.patch_id] = record

    # Source images are metadata only; changing one must not resend text/cards.
    changed = record.get("body_hash") != patch.body_hash
    # Old code consumed an update without actually delivering it. Recover it once.
    recover_skipped = bool(record.get("last_uneditable_change_utc"))
    text_needed = not was_sent or changed or recover_skipped
    # A fresh installation deliberately baselines old posts; do not backfill those.
    fresh_baseline = record.get("migration") == "fresh_install_baseline"
    cards_needed = not summary_is_current(record, patch) and not (fresh_baseline and not text_needed)

    def checkpoint(field: str, ids: list[str]) -> None:
        record[field] = ids
        save_state(state)

    if text_needed:
        if was_sent and not record.get("discord_message_ids"):
            print("기존 메시지 ID 없음 → 수정본을 한 번 새로 전송하고 ID 저장")
        record["status"] = "sending"
        # An interrupted edit must resume even if the source reverts to the old hash.
        save_state(state)
        message_ids = sync_discord_messages(
            webhook_url,
            record.get("discord_message_ids", []),
            build_discord_payloads(patch),
            lambda ids: checkpoint("discord_message_ids", ids),
        )
        record["discord_message_ids"] = message_ids
        update_seen_record(record, patch)
        record["status"] = "sent"
        record.setdefault("sent_at_utc", datetime.now(timezone.utc).isoformat())
        record["last_edited_at_utc"] = datetime.now(timezone.utc).isoformat()
        record["sent_source"] = patch.source_name
        record.pop("last_uneditable_change_utc", None)
        record.pop("migration", None)
        # Commit the text before card generation can fail.
        save_state(state)
    else:
        update_seen_record(record, patch, update_hashes=False)

    if cards_needed:
        summary_ids = refresh_summary_cards(
            webhook_url, patch, record.get("summary_message_ids", []),
            lambda ids: checkpoint("summary_message_ids", ids),
        )
        record["summary_message_ids"] = summary_ids
        record["summary_card_version"] = SUMMARY_CARD_VERSION
        record["summary_body_hash"] = patch.body_hash
        record["summary_empty"] = not summary_ids
        save_state(state)

    record["language_reason"] = language.reason
    record.pop("pending_body_hash", None)
    record.pop("pending_image_hash", None)
    if text_needed:
        return "updated" if was_sent else "sent"
    if cards_needed:
        print("기존 패치 요약 카드 보완 완료")
        return "updated"
    print("이미 전송 완료 → 변경 없음")
    return "already_sent"


def preview_patches(patches: list[Patch], state: dict) -> None:
    """Read-only diagnostics: no Discord calls, no state migration or writes."""
    print("\n===== DRY_RUN: Discord 전송 및 state.json 저장 없음 =====")
    records = state.get("patches", {})
    for patch in patches:
        record = records.get(patch.patch_id, {})
        if not check_korean_patch(patch.items).is_korean:
            action = "한국어 대기"
        elif record.get("status") == "duplicate_source" or (
            not record and find_cross_source_duplicate(patch, records)
        ):
            action = "다른 소스와 중복"
        elif record.get("status") != "sent":
            action = "신규/미완료 전송 대상"
        elif (record.get("body_hash") != patch.body_hash
              or record.get("last_uneditable_change_utc")):
            action = "기존 메시지 수정/ID 없는 수정본 복구 대상"
        elif (record.get("migration") != "fresh_install_baseline"
              and not summary_is_current(record, patch)):
            action = "요약 카드 보완 대상"
        else:
            action = "변경 없음"
        print(f"{patch.patch_id}: {action} / {patch.title}")


# ============================================================
# main
# ============================================================


def main() -> int:
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    webhook_url = os.getenv(
        "DISCORD_WEBHOOK_URL",
        "",
    ).strip()

    if not webhook_url and not dry_run:
        print(
            "DISCORD_WEBHOOK_URL 환경 변수가 없습니다.",
            file=sys.stderr,
        )

        return 2

    try:
        patches = fetch_recent_patches()

    except (
        requests.RequestException,
        RuntimeError,
    ) as exc:
        print(
            f"패치 확인 실패: {exc}",
            file=sys.stderr,
        )

        return 1

    state = load_state()
    if dry_run:
        preview_patches(patches, state)
        return 0

    migrated = migrate_legacy_state(
        state,
        patches,
    )

    if migrated:
        print(
            "구버전 state.json 이관 완료"
        )

        save_state(
            state
        )

    initialize_fresh_state(
        state,
        patches,
    )

    sent_count = 0
    updated_count = 0
    pending_count = 0
    already_count = 0
    skipped_update_count = 0
    duplicate_count = 0

    try:
        for patch in patches:
            result = process_patch(
                patch,
                state,
                webhook_url,
            )

            if result == "sent":
                sent_count += 1
                save_state(
                    state
                )

            elif result == "updated":
                updated_count += 1
                save_state(
                    state
                )

            elif result == "pending_korean":
                pending_count += 1
                save_state(
                    state
                )

            elif result == "already_sent":
                already_count += 1

            elif (
                result
                == "update_skipped_no_message_id"
            ):
                skipped_update_count += 1

                save_state(
                    state
                )

            elif result == "duplicate_source":
                duplicate_count += 1

                save_state(
                    state
                )

    except (
        requests.RequestException,
        RuntimeError,
    ) as exc:
        print(
            f"Discord 처리 실패: {exc}",
            file=sys.stderr,
        )

        return 1

    save_state(
        state
    )

    print(
        "\n===== 실행 결과 ====="
    )

    print(
        f"새로 전송: {sent_count}"
    )

    print(
        f"기존 메시지 수정: {updated_count}"
    )

    print(
        f"한국어 대기: {pending_count}"
    )

    print(
        f"이미 전송됨: {already_count}"
    )

    print(
        f"NEXON/BLIZZARD 중복 차단: {duplicate_count}"
    )

    print(
        f"메시지 ID 없음으로 수정 생략: {skipped_update_count}"
    )

    if (
        sent_count == 0
        and updated_count == 0
    ):
        print(
            "새로 전송하거나 수정할 한국어 패치 없음"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
