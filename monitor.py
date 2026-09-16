from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag
from PIL import Image, ImageDraw, ImageFont


# ============================================================
# 기본 설정
# ============================================================

# 1순위: 넥슨 한국 공식 패치노트
NEXON_LIST_URL = "https://overwatch.nexon.com/news/patchnotes"

# 2순위: Blizzard 한국 공식 패치노트
BLIZZARD_BASE_URL = "https://overwatch.blizzard.com/ko-kr/news/patch-notes/"

STATE_FILE = Path("state.json")

MESSAGE_LIMIT = 1900

# 텍스트 메시지에만 적용됩니다.
# 이미지는 개수 제한 없이 10장씩 계속 나눠 전송합니다.
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

SUMMARY_CARD_WIDTH = 900
SUMMARY_CARD_HEIGHT = 1150
SUMMARY_CARD_MARGIN = 58
SUMMARY_CARD_VERSION = 1

# 카드 한 장에 다 안 들어가면 자동으로 다음 장을 생성합니다.
SUMMARY_MAX_CHANGE_LINES_PER_HERO = 8

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
    "cooldown",
    "시전 시간",
    "시전시간",
    "지연 시간",
    "지연시간",
    "충전 시간",
    "충전시간",
    "후딜",
    "선딜",
    "분산도",
    "탄 퍼짐",
    "퍼짐",
    "반동",
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
    "투사체 속도",
    "투사체속도",
    "발사 속도",
    "발사속도",
    "탄창",
    "탄약",
    "범위",
)

CHANGE_NUMBER_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(%|초|m|M|미터|)?\s*(?:→|->|에서)\s*"
    r"(-?\d+(?:\.\d+)?)",
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

def extract_nexon_article_links(
    list_html: str,
) -> list[str]:
    soup = BeautifulSoup(
        list_html,
        "html.parser",
    )

    links: list[str] = []
    seen: set[str] = set()

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

        if not NEXON_ARTICLE_HREF_RE.search(
            href
        ):
            continue

        url = urljoin(
            NEXON_LIST_URL,
            href,
        )

        if url in seen:
            continue

        seen.add(
            url
        )

        links.append(
            url
        )

        if (
            len(links)
            >= NEXON_MAX_ARTICLES
        ):
            break

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


def parse_nexon_article(
    html: str,
    source_url: str,
) -> dict | None:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    area = (
        soup.find("article")
        or soup.find("main")
        or soup
    )

    title_node = find_patch_title_node(
        area
    )

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

    if not date_key:
        return None

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
                node.name,
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
                    node.name,
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

    if len(text) > 220:
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
        before = float(
            match.group(1)
        )

        after = float(
            match.group(3)
        )

        if after > before:
            return 1

        if after < before:
            return -1

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
    normalized = clean_text(text).lower()
    direction = _extract_numeric_direction(
        normalized
    )

    lower_is_better = any(
        keyword in normalized
        for keyword in LOWER_IS_BETTER_KEYWORDS
    )

    higher_is_better = any(
        keyword in normalized
        for keyword in HIGHER_IS_BETTER_KEYWORDS
    )

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
    if (
        "상향" in normalized
        or "강화" in normalized
    ):
        return "buff"

    if (
        "하향" in normalized
        or "약화" in normalized
    ):
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

    heroes: dict[
        tuple[str, str],
        list[str],
    ] = {}

    for tag_name, raw_text in patch.items:
        text = clean_text(
            raw_text
        )

        if not text:
            continue

        is_heading = tag_name in {
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }

        if is_heading:
            role = _role_from_heading(
                text
            )

            if role:
                current_role = role
                current_hero = None
                continue

            if _is_generic_section(
                text
            ):
                # 역할 자체는 유지하되 영웅은 종료
                current_hero = None
                continue

            # 역할 아래의 짧은 제목은 영웅명으로 취급
            if (
                current_role
                and 1 <= len(text) <= 36
            ):
                current_hero = text

                heroes.setdefault(
                    (
                        current_role,
                        current_hero,
                    ),
                    [],
                )

            continue

        if (
            current_role
            and current_hero
            and _looks_like_change_line(text)
        ):
            key = (
                current_role,
                current_hero,
            )

            lines = heroes.setdefault(
                key,
                [],
            )

            if (
                text not in lines
            ):
                lines.append(
                    text
                )

    result: list[dict] = []

    for (
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
        )

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
                "changes": changes[
                    :SUMMARY_MAX_CHANGE_LINES_PER_HERO
                ],
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

    for candidate in candidates:
        if Path(
            candidate
        ).exists():
            return candidate

    # 마지막 fallback. 한글 폰트가 아니면 카드 생성은 중단합니다.
    raise RuntimeError(
        "Noto Sans CJK 폰트를 찾지 못했습니다. "
        "GitHub Actions에서 fonts-noto-cjk 설치 단계가 필요합니다."
    )


def _font(
    size: int,
    bold: bool = False,
) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        _find_font_path(
            bold
        ),
        size=size,
    )


def _draw_hex_background(
    draw: ImageDraw.ImageDraw,
) -> None:
    # 아주 옅은 벌집 패턴
    outline = (
        232,
        238,
        238,
    )

    radius = 48
    x_step = 72
    y_step = 84

    for row, y in enumerate(
        range(
            110,
            SUMMARY_CARD_HEIGHT,
            y_step,
        )
    ):
        offset = (
            0
            if row % 2 == 0
            else x_step // 2
        )

        for x in range(
            -20 + offset,
            SUMMARY_CARD_WIDTH,
            x_step,
        ):
            points = []

            for angle in (
                0,
                60,
                120,
                180,
                240,
                300,
            ):
                import math

                rad = math.radians(
                    angle
                )

                points.append(
                    (
                        x
                        + radius
                        * math.cos(rad),
                        y
                        + radius
                        * math.sin(rad),
                    )
                )

            draw.line(
                points
                + [
                    points[0]
                ],
                fill=outline,
                width=2,
            )


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """
    한글도 띄어쓰기 단위로 감싸고,
    너무 긴 토큰은 글자 단위로 추가 분리합니다.
    """
    words = text.split()

    if not words:
        return []

    lines: list[str] = []
    current = ""

    for word in words:
        candidate = (
            f"{current} {word}".strip()
        )

        width = draw.textbbox(
            (0, 0),
            candidate,
            font=font,
        )[2]

        if width <= max_width:
            current = candidate
            continue

        if current:
            lines.append(
                current
            )

        # 단일 단어도 너무 긴 경우 글자 단위 분할
        if (
            draw.textbbox(
                (0, 0),
                word,
                font=font,
            )[2]
            > max_width
        ):
            part = ""

            for char in word:
                c = part + char

                if (
                    draw.textbbox(
                        (0, 0),
                        c,
                        font=font,
                    )[2]
                    <= max_width
                ):
                    part = c

                else:
                    if part:
                        lines.append(
                            part
                        )

                    part = char

            current = part

        else:
            current = word

    if current:
        lines.append(
            current
        )

    return lines


SUMMARY_STYLE = {
    "buff": {
        "title": "상향",
        "accent": (
            79,
            187,
            151,
        ),
        "symbol": "↑",
    },
    "nerf": {
        "title": "하향",
        "accent": (
            191,
            54,
            88,
        ),
        "symbol": "↓",
    },
    "adjust": {
        "title": "조정",
        "accent": (
            221,
            120,
            29,
        ),
        "symbol": "↕",
    },
    "summary": {
        "title": "핵심 요약",
        "accent": (
            79,
            150,
            194,
        ),
        "symbol": "◆",
    },
}


def _estimate_hero_height(
    draw: ImageDraw.ImageDraw,
    entry: dict,
    body_font: ImageFont.FreeTypeFont,
) -> int:
    max_width = (
        SUMMARY_CARD_WIDTH
        - SUMMARY_CARD_MARGIN * 2
        - 255
    )

    line_count = 0

    for change in entry[
        "changes"
    ]:
        wrapped = _wrap_text(
            draw,
            change,
            body_font,
            max_width,
        )

        line_count += max(
            1,
            len(
                wrapped
            ),
        )

    return max(
        92,
        36
        + line_count * 35,
    )


def _paginate_summary_entries(
    category: str,
    entries: list[dict],
) -> list[list[dict]]:
    """
    실제 렌더링 높이에 맞춰 자동 페이지 분리.
    """
    canvas = Image.new(
        "RGB",
        (
            SUMMARY_CARD_WIDTH,
            SUMMARY_CARD_HEIGHT,
        ),
        "white",
    )

    draw = ImageDraw.Draw(
        canvas
    )

    body_font = _font(
        27,
        False,
    )

    available = (
        SUMMARY_CARD_HEIGHT
        - 225
    )

    pages: list[
        list[dict]
    ] = []

    current: list[dict] = []
    used = 0
    previous_role = None

    for entry in entries:
        height = _estimate_hero_height(
            draw,
            entry,
            body_font,
        )

        if (
            entry["role"]
            != previous_role
        ):
            height += 52

        if (
            current
            and used + height
            > available
        ):
            pages.append(
                current
            )

            current = []
            used = 0
            previous_role = None

            height = (
                _estimate_hero_height(
                    draw,
                    entry,
                    body_font,
                )
                + 52
            )

        current.append(
            entry
        )

        used += height
        previous_role = entry[
            "role"
        ]

    if current:
        pages.append(
            current
        )

    return pages


def _render_balance_card(
    patch: Patch,
    category: str,
    entries: list[dict],
    page_number: int,
    total_pages: int,
    output_path: Path,
) -> None:
    style = SUMMARY_STYLE[
        category
    ]

    image = Image.new(
        "RGB",
        (
            SUMMARY_CARD_WIDTH,
            SUMMARY_CARD_HEIGHT,
        ),
        (
            248,
            250,
            250,
        ),
    )

    draw = ImageDraw.Draw(
        image
    )

    _draw_hex_background(
        draw
    )

    accent = style[
        "accent"
    ]

    dark = (
        50,
        59,
        65,
    )

    # 상단 장식
    draw.rectangle(
        (
            0,
            0,
            SUMMARY_CARD_WIDTH,
            12,
        ),
        fill=accent,
    )

    header_font = _font(
        64,
        True,
    )

    symbol_font = _font(
        58,
        True,
    )

    role_font = _font(
        31,
        True,
    )

    hero_font = _font(
        27,
        True,
    )

    body_font = _font(
        27,
        False,
    )

    small_font = _font(
        21,
        False,
    )

    # 카테고리 아이콘
    draw.rounded_rectangle(
        (
            SUMMARY_CARD_MARGIN,
            70,
            SUMMARY_CARD_MARGIN + 92,
            162,
        ),
        radius=18,
        fill=accent,
    )

    symbol = style[
        "symbol"
    ]

    symbol_box = draw.textbbox(
        (0, 0),
        symbol,
        font=symbol_font,
    )

    sw = (
        symbol_box[2]
        - symbol_box[0]
    )

    sh = (
        symbol_box[3]
        - symbol_box[1]
    )

    draw.text(
        (
            SUMMARY_CARD_MARGIN
            + 46
            - sw / 2,
            116
            - sh / 2
            - 6,
        ),
        symbol,
        font=symbol_font,
        fill="white",
    )

    draw.text(
        (
            SUMMARY_CARD_MARGIN
            + 112,
            73,
        ),
        style["title"],
        font=header_font,
        fill=(
            24,
            27,
            29,
        ),
    )

    if total_pages > 1:
        draw.text(
            (
                SUMMARY_CARD_WIDTH
                - SUMMARY_CARD_MARGIN
                - 95,
                126,
            ),
            f"{page_number}/{total_pages}",
            font=small_font,
            fill=(
                110,
                115,
                118,
            ),
            anchor="ra",
        )

    y = 205
    current_role = None

    for entry in entries:
        role = entry[
            "role"
        ]

        if role != current_role:
            # 역할 라벨
            draw.rounded_rectangle(
                (
                    SUMMARY_CARD_MARGIN,
                    y,
                    SUMMARY_CARD_WIDTH
                    - SUMMARY_CARD_MARGIN,
                    y + 45,
                ),
                radius=12,
                fill=(
                    232,
                    236,
                    238,
                ),
            )

            draw.text(
                (
                    SUMMARY_CARD_MARGIN
                    + 18,
                    y + 6,
                ),
                role,
                font=role_font,
                fill=dark,
            )

            y += 58
            current_role = role

        block_height = _estimate_hero_height(
            draw,
            entry,
            body_font,
        )

        draw.rounded_rectangle(
            (
                SUMMARY_CARD_MARGIN,
                y,
                SUMMARY_CARD_WIDTH
                - SUMMARY_CARD_MARGIN,
                y + block_height,
            ),
            radius=18,
            fill=dark,
        )

        # 영웅 이름 배지
        badge_x = (
            SUMMARY_CARD_MARGIN
            + 25
        )

        badge_y = y + 25

        badge_w = 205

        draw.rounded_rectangle(
            (
                badge_x,
                badge_y,
                badge_x + badge_w,
                badge_y + 46,
            ),
            radius=7,
            fill=accent,
        )

        hero_name = entry[
            "hero"
        ]

        draw.text(
            (
                badge_x
                + badge_w / 2,
                badge_y + 23,
            ),
            hero_name,
            font=hero_font,
            fill="white",
            anchor="mm",
        )

        text_x = (
            badge_x
            + badge_w
            + 25
        )

        text_y = y + 24

        max_width = (
            SUMMARY_CARD_WIDTH
            - SUMMARY_CARD_MARGIN
            - text_x
            - 20
        )

        for change in entry[
            "changes"
        ]:
            wrapped = _wrap_text(
                draw,
                change,
                body_font,
                max_width,
            )

            if not wrapped:
                continue

            for index, line in enumerate(
                wrapped
            ):
                prefix = (
                    "• "
                    if index == 0
                    else "  "
                )

                draw.text(
                    (
                        text_x,
                        text_y,
                    ),
                    prefix + line,
                    font=body_font,
                    fill=(
                        245,
                        247,
                        248,
                    ),
                )

                text_y += 35

        y += (
            block_height
            + 12
        )

    draw.text(
        (
            SUMMARY_CARD_WIDTH / 2,
            SUMMARY_CARD_HEIGHT - 42,
        ),
        "OVERWATCH · 자동 요약",
        font=small_font,
        fill=(
            100,
            108,
            112,
        ),
        anchor="mm",
    )

    image.save(
        output_path,
        format="PNG",
        optimize=True,
    )


def _render_generic_card(
    patch: Patch,
    items: list[str],
    output_path: Path,
) -> None:
    style = SUMMARY_STYLE[
        "summary"
    ]

    image = Image.new(
        "RGB",
        (
            SUMMARY_CARD_WIDTH,
            SUMMARY_CARD_HEIGHT,
        ),
        (
            248,
            250,
            250,
        ),
    )

    draw = ImageDraw.Draw(
        image
    )

    _draw_hex_background(
        draw
    )

    accent = style[
        "accent"
    ]

    dark = (
        50,
        59,
        65,
    )

    header_font = _font(
        57,
        True,
    )

    body_font = _font(
        28,
        False,
    )

    small_font = _font(
        21,
        False,
    )

    draw.rectangle(
        (
            0,
            0,
            SUMMARY_CARD_WIDTH,
            12,
        ),
        fill=accent,
    )

    draw.rounded_rectangle(
        (
            SUMMARY_CARD_MARGIN,
            70,
            SUMMARY_CARD_MARGIN + 92,
            162,
        ),
        radius=18,
        fill=accent,
    )

    draw.text(
        (
            SUMMARY_CARD_MARGIN
            + 46,
            116,
        ),
        "◆",
        font=_font(
            45,
            True,
        ),
        fill="white",
        anchor="mm",
    )

    draw.text(
        (
            SUMMARY_CARD_MARGIN
            + 112,
            80,
        ),
        "핵심 요약",
        font=header_font,
        fill=(
            24,
            27,
            29,
        ),
    )

    y = 205

    draw.rounded_rectangle(
        (
            SUMMARY_CARD_MARGIN,
            y,
            SUMMARY_CARD_WIDTH
            - SUMMARY_CARD_MARGIN,
            SUMMARY_CARD_HEIGHT
            - 85,
        ),
        radius=20,
        fill=dark,
    )

    y += 35

    max_width = (
        SUMMARY_CARD_WIDTH
        - SUMMARY_CARD_MARGIN * 2
        - 70
    )

    for item in items:
        wrapped = _wrap_text(
            draw,
            item,
            body_font,
            max_width,
        )

        needed = (
            max(
                1,
                len(
                    wrapped
                ),
            )
            * 39
            + 18
        )

        if (
            y + needed
            > SUMMARY_CARD_HEIGHT - 120
        ):
            break

        for index, line in enumerate(
            wrapped
        ):
            draw.text(
                (
                    SUMMARY_CARD_MARGIN
                    + 35,
                    y,
                ),
                (
                    "• "
                    if index == 0
                    else "  "
                )
                + line,
                font=body_font,
                fill=(
                    245,
                    247,
                    248,
                ),
            )

            y += 39

        y += 14

    draw.text(
        (
            SUMMARY_CARD_WIDTH / 2,
            SUMMARY_CARD_HEIGHT - 42,
        ),
        "OVERWATCH · 자동 요약",
        font=small_font,
        fill=(
            100,
            108,
            112,
        ),
        anchor="mm",
    )

    image.save(
        output_path,
        format="PNG",
        optimize=True,
    )


def generate_summary_cards(
    patch: Patch,
    output_dir: Path,
) -> list[Path]:
    """
    상향 → 하향 → 조정 순으로 카드 생성.
    해당 분류가 없으면 만들지 않습니다.

    영웅 밸런스 구조를 찾지 못하면 '핵심 요약' 카드 1장을 생성합니다.
    """
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    balance = extract_balance_summary(
        patch
    )

    paths: list[Path] = []

    category_order = (
        "buff",
        "nerf",
        "adjust",
    )

    if balance:
        for category in category_order:
            category_entries = [
                entry
                for entry in balance
                if entry[
                    "category"
                ] == category
            ]

            if not category_entries:
                continue

            pages = _paginate_summary_entries(
                category,
                category_entries,
            )

            for page_index, entries in enumerate(
                pages,
                start=1,
            ):
                path = (
                    output_dir
                    / (
                        f"{patch.patch_id.replace('#', '-')}"
                        f"-summary-{category}-{page_index}.png"
                    )
                )

                _render_balance_card(
                    patch,
                    category,
                    entries,
                    page_index,
                    len(
                        pages
                    ),
                    path,
                )

                paths.append(
                    path
                )

    if not paths:
        generic_items = extract_generic_summary(
            patch
        )

        if generic_items:
            path = (
                output_dir
                / (
                    f"{patch.patch_id.replace('#', '-')}"
                    "-summary.png"
                )
            )

            _render_generic_card(
                patch,
                generic_items,
                path,
            )

            paths.append(
                path
            )

    return paths


def send_summary_cards(
    webhook_url: str,
    patch: Patch,
) -> list[str]:
    """
    원본 패치 메시지 전송이 끝난 뒤 호출됩니다.
    카드 한 장을 Discord 메시지 하나로 보내므로
    모바일에서도 작게 뭉개지지 않고 크게 보입니다.
    """
    with tempfile.TemporaryDirectory(
        prefix="ow-summary-"
    ) as temp_dir:
        paths = generate_summary_cards(
            patch,
            Path(
                temp_dir
            ),
        )

        if not paths:
            print(
                "요약 카드로 만들 항목 없음"
            )

            return []

        endpoint = (
            webhook_base_url(
                webhook_url
            )
            + "?wait=true"
        )

        message_ids: list[str] = []

        total = len(
            paths
        )

        for index, path in enumerate(
            paths,
            start=1,
        ):
            payload_json = json.dumps(
                {
                    "username": "오버워치 패치 요약",
                    "content": (
                        f"**자동 요약 카드 "
                        f"[{index}/{total}]**"
                    ),
                    "allowed_mentions": {
                        "parse": []
                    },
                },
                ensure_ascii=False,
            )

            with path.open(
                "rb"
            ) as file_handle:
                response = requests.post(
                    endpoint,
                    data={
                        "payload_json": payload_json
                    },
                    files={
                        "files[0]": (
                            path.name,
                            file_handle,
                            "image/png",
                        )
                    },
                    timeout=60,
                )

            response.raise_for_status()

            data = response.json()

            message_id = str(
                data.get(
                    "id",
                    "",
                )
            ).strip()

            if not message_id:
                raise RuntimeError(
                    "Discord가 요약 카드 message_id를 반환하지 않았습니다."
                )

            message_ids.append(
                message_id
            )

            time.sleep(
                1
            )

        return message_ids


def refresh_summary_cards(
    webhook_url: str,
    patch: Patch,
    old_summary_message_ids: list[str],
) -> list[str]:
    """
    새 요약을 먼저 올린 뒤 기존 요약을 삭제합니다.
    새 요약 생성/전송 실패 시 기존 요약이 남아 있도록 하는 안전장치입니다.
    """
    new_ids = send_summary_cards(
        webhook_url,
        patch,
    )

    for message_id in old_summary_message_ids:
        try:
            delete_discord_message(
                webhook_url,
                str(
                    message_id
                ),
            )

            time.sleep(
                0.35
            )

        except requests.RequestException as exc:
            print(
                f"기존 요약 메시지 삭제 실패 "
                f"({message_id}): {exc}"
            )

    return new_ids


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

        elif tag_name == "p":
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


def chunks_of(
    values: list[str],
    size: int,
) -> list[list[str]]:
    return [
        values[index:index + size]
        for index in range(
            0,
            len(values),
            size,
        )
    ]


def build_discord_payloads(
    patch: Patch,
) -> list[dict]:
    """
    텍스트 + 패치 본문 공식 이미지를 전부 Discord에 보냅니다.

    Discord는 한 메시지에 Embed 최대 10개이므로
    이미지가 23장이면 10 + 10 + 3으로 자동 분할됩니다.

    이미지 개수 자체에는 별도 제한을 두지 않습니다.
    """
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

    image_groups = chunks_of(
        patch.images,
        DISCORD_EMBEDS_PER_MESSAGE,
    )

    total_images = len(
        patch.images
    )

    image_position = 0

    for group in image_groups:
        first = (
            image_position + 1
        )

        last = (
            image_position
            + len(group)
        )

        payloads.append(
            {
                "content": (
                    f"**패치 이미지 "
                    f"{first}-{last}/{total_images}**"
                ),
                "embeds": [
                    {
                        "image": {
                            "url": image_url
                        }
                    }
                    for image_url in group
                ],
            }
        )

        image_position = last

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
) -> list[str]:
    base = webhook_base_url(
        webhook_url
    )

    endpoint = (
        base
        + "?wait=true"
    )

    message_ids: list[str] = []

    for payload in decorate_payloads(
        payloads
    ):
        response = requests.post(
            endpoint,
            json={
                "username": "오버워치 패치 알림",
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

        data = response.json()

        message_id = str(
            data.get(
                "id",
                "",
            )
        ).strip()

        if not message_id:
            raise RuntimeError(
                "Discord가 message_id를 반환하지 않았습니다."
            )

        message_ids.append(
            message_id
        )

        time.sleep(1)

    return message_ids


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
    response = requests.patch(
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
    response = requests.delete(
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
) -> list[str]:
    """
    텍스트와 이미지가 추가/삭제돼 메시지 개수가 달라져도
    기존 Discord 메시지 묶음을 새 패치 내용과 일치시킵니다.
    """
    old_ids = [
        str(item)
        for item in old_message_ids
        if str(item).strip()
    ]

    payloads = decorate_payloads(
        new_payloads
    )

    final_ids: list[str] = []

    shared = min(
        len(old_ids),
        len(payloads),
    )

    # 기존 메시지 수정
    for index in range(
        shared
    ):
        edit_discord_message(
            webhook_url,
            old_ids[index],
            payloads[index],
        )

        final_ids.append(
            old_ids[index]
        )

        time.sleep(0.5)

    # 새 메시지가 더 많으면 추가
    if (
        len(payloads)
        > len(old_ids)
    ):
        endpoint = (
            webhook_base_url(
                webhook_url
            )
            + "?wait=true"
        )

        for payload in payloads[
            len(old_ids):
        ]:
            response = requests.post(
                endpoint,
                json={
                    "username": "오버워치 패치 알림",
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

            data = response.json()

            message_id = str(
                data.get(
                    "id",
                    "",
                )
            ).strip()

            if not message_id:
                raise RuntimeError(
                    "Discord가 추가 메시지의 message_id를 반환하지 않았습니다."
                )

            final_ids.append(
                message_id
            )

            time.sleep(1)

    # 기존 메시지가 더 많으면 삭제
    elif (
        len(old_ids)
        > len(payloads)
    ):
        for message_id in old_ids[
            len(payloads):
        ]:
            delete_discord_message(
                webhook_url,
                message_id,
            )

            time.sleep(0.5)

    return final_ids


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
        "summary_card_version": SUMMARY_CARD_VERSION,
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

    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


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

def process_patch(
    patch: Patch,
    state: dict,
    webhook_url: str,
) -> str:
    records: dict = state.setdefault(
        "patches",
        {},
    )

    record = records.get(
        patch.patch_id
    )

    print(
        f"\n[{patch.source_name.upper()} / {patch.patch_id}] "
        f"{patch.title} / 이미지 {len(patch.images)}장"
    )

    language = check_korean_patch(
        patch.items
    )

    print(
        f"언어 판별: {language.reason} "
        f"({describe_language(language)})"
    )

    # 이미 다른 공식 소스에서 같은 패치를 보낸 경우 중복 전송 방지
    if record is None:
        duplicate = find_cross_source_duplicate(
            patch,
            records,
        )

        if duplicate is not None:
            original_id, original_record = duplicate

            alias = make_record(
                patch,
                "duplicate_source",
            )

            alias[
                "duplicate_of"
            ] = original_id

            alias[
                "discord_message_ids"
            ] = []

            records[
                patch.patch_id
            ] = alias

            print(
                f"다른 공식 소스의 동일 패치로 판단 "
                f"→ 중복 전송 안 함 ({original_id})"
            )

            return "duplicate_source"

    # 이미 중복 소스로 판정된 기록
    if (
        record
        and record.get(
            "status"
        ) == "duplicate_source"
    ):
        update_seen_record(
            record,
            patch,
            update_hashes=True,
        )

        print(
            "이미 다른 공식 소스와 중복 처리됨 → 전송 안 함"
        )

        return "duplicate_source"

    # --------------------------------------------------------
    # 이미 전송한 패치
    # --------------------------------------------------------
    if (
        record
        and record.get(
            "status"
        ) == "sent"
    ):
        # 구버전 state에는 image_hash가 없을 수 있습니다.
        # 새 버전 적용만으로 과거 패치를 대량 수정하지 않도록
        # 첫 확인에서는 현재 이미지 상태만 기준선으로 기록합니다.
        old_image_hash = record.get(
            "image_hash"
        )

        if old_image_hash is None:
            record[
                "image_hash"
            ] = patch.image_hash

            record[
                "image_count"
            ] = len(
                patch.images
            )

            image_changed = False

        else:
            image_changed = (
                old_image_hash
                != patch.image_hash
            )

        text_changed = (
            record.get(
                "body_hash"
            )
            != patch.body_hash
        )

        if (
            not text_changed
            and not image_changed
        ):
            update_seen_record(
                record,
                patch,
                update_hashes=False,
            )

            print(
                "이미 전송 완료 → 본문/이미지 변경 없음"
            )

            return "already_sent"

        print(
            f"기존 패치 변경 감지 "
            f"(본문={text_changed}, 이미지={image_changed})"
        )

        if not language.is_korean:
            record[
                "pending_body_hash"
            ] = patch.body_hash

            record[
                "pending_image_hash"
            ] = patch.image_hash

            update_seen_record(
                record,
                patch,
                update_hashes=False,
            )

            print(
                "수정본이 영어 또는 불확실 "
                "→ 기존 Discord 메시지 유지"
            )

            return "pending_korean"

        old_message_ids = record.get(
            "discord_message_ids",
            [],
        )

        if not isinstance(
            old_message_ids,
            list,
        ):
            old_message_ids = []

        if not old_message_ids:
            update_seen_record(
                record,
                patch,
                update_hashes=True,
            )

            record[
                "last_uneditable_change_utc"
            ] = datetime.now(
                timezone.utc
            ).isoformat()

            print(
                "변경 확인 / 기존 Discord message_id 없음 "
                "→ 중복 전송 없이 수정 생략"
            )

            return (
                "update_skipped_no_message_id"
            )

        payloads = build_discord_payloads(
            patch
        )

        final_ids = sync_discord_messages(
            webhook_url,
            old_message_ids,
            payloads,
        )

        update_seen_record(
            record,
            patch,
            update_hashes=True,
        )

        record[
            "discord_message_ids"
        ] = final_ids

        old_summary_ids = record.get(
            "summary_message_ids",
            [],
        )

        if not isinstance(
            old_summary_ids,
            list,
        ):
            old_summary_ids = []

        # 본문 수정 시 요약 카드도 새 내용으로 갱신
        summary_ids = refresh_summary_cards(
            webhook_url,
            patch,
            old_summary_ids,
        )

        record[
            "summary_message_ids"
        ] = summary_ids

        record[
            "summary_card_version"
        ] = SUMMARY_CARD_VERSION

        record[
            "last_edited_at_utc"
        ] = datetime.now(
            timezone.utc
        ).isoformat()

        record.pop(
            "pending_body_hash",
            None,
        )

        record.pop(
            "pending_image_hash",
            None,
        )

        print(
            f"기존 Discord 메시지 수정 완료 "
            f"({len(final_ids)}개 / 이미지 {len(patch.images)}장 / "
            f"요약 카드 {len(summary_ids)}장)"
        )

        return "updated"

    # --------------------------------------------------------
    # 아직 전송하지 않은 패치
    # --------------------------------------------------------
    if not language.is_korean:
        if record is None:
            record = make_record(
                patch,
                "pending_korean",
            )

            records[
                patch.patch_id
            ] = record

        else:
            update_seen_record(
                record,
                patch,
                update_hashes=True,
            )

            record[
                "status"
            ] = (
                "pending_korean"
            )

        record[
            "language_reason"
        ] = language.reason

        print(
            "영문 또는 불확실 "
            "→ Discord 전송 안 함 / 한국어판 대기"
        )

        return "pending_korean"

    # 한국어 패치 최초 전송
    payloads = build_discord_payloads(
        patch
    )

    message_ids = send_to_discord(
        webhook_url,
        payloads,
    )

    # 원본 패치노트 전송 완료 후 바로 아래에 자동 요약 카드 전송
    summary_message_ids = send_summary_cards(
        webhook_url,
        patch,
    )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    if record is None:
        record = make_record(
            patch,
            "sent",
        )

        records[
            patch.patch_id
        ] = record

    else:
        update_seen_record(
            record,
            patch,
            update_hashes=True,
        )

        record[
            "status"
        ] = "sent"

        record[
            "sent_at_utc"
        ] = now

    record[
        "discord_message_ids"
    ] = message_ids

    record[
        "summary_message_ids"
    ] = summary_message_ids

    record[
        "summary_card_version"
    ] = SUMMARY_CARD_VERSION

    record[
        "language_reason"
    ] = language.reason

    record[
        "sent_source"
    ] = patch.source_name

    print(
        f"한국어 패치 → Discord 전송 완료 "
        f"({len(message_ids)}개 원본 메시지 / "
        f"공식 이미지 {len(patch.images)}장 / "
        f"요약 카드 {len(summary_message_ids)}장 / ID 저장)"
    )

    return "sent"


# ============================================================
# main
# ============================================================

def main() -> int:
    webhook_url = os.getenv(
        "DISCORD_WEBHOOK_URL",
        "",
    ).strip()

    if not webhook_url:
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
