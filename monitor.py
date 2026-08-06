from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://overwatch.blizzard.com/ko-kr/news/patch-notes/"
STATE_FILE = Path("state.json")
MESSAGE_LIMIT = 1900
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "8"))
SEND_ON_FIRST_RUN = os.getenv("SEND_ON_FIRST_RUN", "true").lower() == "true"

# 일반 브라우저에 가까운 헤더를 사용합니다.
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
    r"20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"
)
ENGLISH_DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{1,2},\s+20\d{2}",
    re.IGNORECASE,
)

NORMAL_SECTION_PATTERN = re.compile(
    r"^(?:"
    r"일반(?:\s*업데이트)?|"
    r"일반\s*모드|"
    r"버그\s*수정|"
    r"영웅(?:\s*밸런스)?(?:\s*업데이트)?|"
    r"돌격|공격|지원|"
    r"핵심\s*게임(?:\s*업데이트)?|"
    r"경쟁전(?:\s*업데이트)?|"
    r"전장(?:\s*업데이트)?|"
    r"빠른\s*대전|자유\s*역할|역할\s*고정|"
    r"6대6|아케이드|미스터리\s*영웅|"
    r"시스템(?:\s*업데이트)?|UI(?:\s*업데이트)?|"
    r"General(?:\s*Updates?)?|Bug\s*Fixes?|Hero(?:\s*Updates?)?|"
    r"Tank|Damage|Support|Maps?|Competitive(?:\s*Play)?(?:\s*Updates?)?"
    r")(?:\s*[:：-].*)?$",
    re.IGNORECASE,
)


def clean_text(value: str) -> str:
    value = value.replace("\u200b", "")
    return re.sub(r"\s+", " ", value).strip()


def shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + offset
    return index // 12, index % 12 + 1


def candidate_urls() -> list[str]:
    now = datetime.now(timezone.utc)
    urls: list[str] = []

    # 현재 달부터 최근 4개월의 월별 페이지를 먼저 확인합니다.
    for offset in range(0, -4, -1):
        year, month = shift_month(now.year, now.month, offset)
        urls.append(f"{BASE_URL}live/{year}/{month:02d}/")

    # 월별 페이지에서 못 찾을 때만 메인 페이지를 마지막으로 확인합니다.
    urls.append(BASE_URL)
    return urls


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


def contains_patch_date(text: str) -> bool:
    return bool(KOREAN_DATE_RE.search(text) or ENGLISH_DATE_RE.search(text))


def is_patch_title(text: str) -> bool:
    lowered = text.lower()
    has_patch_words = "패치 노트" in text or "patch notes" in lowered
    return has_patch_words and contains_patch_date(text)


def is_stadium_patch_title(text: str) -> bool:
    lowered = text.lower()
    return "스타디움" in text or "stadium" in lowered


def heading_level(tag_name: str) -> int | None:
    if re.fullmatch(r"h[1-6]", tag_name):
        return int(tag_name[1])
    return None


def is_stadium_section_title(tag_name: str, text: str) -> bool:
    if tag_name == "li" or len(text) > 70:
        return False

    lowered = text.lower()
    if "스타디움" not in text and "stadium" not in lowered:
        return False

    if heading_level(tag_name) is not None:
        return True

    if tag_name != "p":
        return False

    compact = re.sub(r"\s+", "", text).lower()
    return (
        compact == "스타디움"
        or compact == "stadium"
        or compact.startswith("스타디움업데이트")
        or compact.startswith("스타디움영웅")
        or compact.startswith("스타디움버그")
        or compact.startswith("스타디움밸런스")
        or compact.startswith("stadiumupdates")
        or compact.startswith("stadiumbug")
        or compact.startswith("stadiumhero")
    )


def is_normal_paragraph_section_title(text: str) -> bool:
    if len(text) > 60:
        return False
    return bool(NORMAL_SECTION_PATTERN.fullmatch(text.strip()))


def find_title_node(soup: BeautifulSoup) -> Tag | None:
    area = soup.find("main") or soup

    # Blizzard 페이지의 제목 단계가 바뀌어도 찾을 수 있게 h1~h6 전체를 검사합니다.
    for tag in area.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        text = clean_text(tag.get_text(" ", strip=True))
        if is_patch_title(text):
            return tag

    return None


def parse_latest_patch(
    html: str,
) -> tuple[str, list[tuple[str, str]], str, bool]:
    soup = BeautifulSoup(html, "html.parser")
    title_node = find_title_node(soup)

    if title_node is None:
        headings = [
            clean_text(tag.get_text(" ", strip=True))
            for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])[:12]
        ]
        preview = " | ".join(filter(None, headings)) or "(제목 태그 없음)"
        raise RuntimeError(
            "패치 제목을 찾지 못했습니다. 확인된 제목: " + preview
        )

    title = clean_text(title_node.get_text(" ", strip=True))
    title_level = heading_level(title_node.name) or 3
    stadium_only_title = is_stadium_patch_title(title)

    items: list[tuple[str, str]] = []
    raw_parts = [title]
    filtered_stadium = stadium_only_title
    skipping_stadium = stadium_only_title
    stadium_heading_level: int | None = None

    for node in title_node.find_all_next(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]
    ):
        text = clean_text(node.get_text(" ", strip=True))
        if not text:
            continue

        # 다음 날짜의 패치 제목이 시작되면 현재 패치 수집을 끝냅니다.
        if node is not title_node and is_patch_title(text):
            break

        # 현재 제목보다 상위 단계의 페이지 영역으로 넘어가면 끝냅니다.
        current_level = heading_level(node.name)
        if (
            node is not title_node
            and current_level is not None
            and current_level < title_level
        ):
            break

        if text in {
            "위로 이동",
            "Top",
            "Top of post",
            "패치 노트의 처음으로 돌아가기",
        }:
            continue

        if stadium_only_title:
            continue

        if not skipping_stadium and is_stadium_section_title(node.name, text):
            skipping_stadium = True
            filtered_stadium = True
            stadium_heading_level = current_level
            continue

        if skipping_stadium:
            if stadium_heading_level is not None:
                # 스타디움 큰 제목(h4 등) 아래의 영웅/기술 제목은 계속 제외합니다.
                # 같은 단계 또는 상위 단계라도 일반 구역으로 인식되는 제목에서만 종료합니다.
                if (
                    current_level is not None
                    and current_level <= stadium_heading_level
                    and (
                        is_normal_paragraph_section_title(text)
                        or (
                            "스타디움" not in text
                            and "stadium" not in text.lower()
                            and current_level < stadium_heading_level
                        )
                    )
                ):
                    skipping_stadium = False
                    stadium_heading_level = None
                else:
                    continue
            else:
                # p 태그의 '스타디움'에서 시작한 경우 다음 일반 구역 표제까지 제외합니다.
                if (
                    (node.name == "p" and is_normal_paragraph_section_title(text))
                    or (
                        current_level is not None
                        and is_normal_paragraph_section_title(text)
                    )
                ):
                    skipping_stadium = False
                else:
                    continue

        # 페이지 하단의 안내·포럼 링크 구역은 제외합니다.
        lowered = text.lower()
        if text in {"패치 노트", "Live Patch Notes"}:
            continue
        if "general discussion forum" in lowered:
            break
        if "기술 지원 토론장" in text or "버그 제보 토론장" in text:
            break

        if raw_parts and raw_parts[-1] == text:
            continue

        raw_parts.append(text)
        items.append((node.name, text))

    if not items and not filtered_stadium:
        raise RuntimeError("최신 일반 모드 패치 본문을 찾지 못했습니다.")

    digest_source = raw_parts if items else [title, "[STADIUM_ONLY_SKIPPED]"]
    digest = hashlib.sha256(
        "\n".join(digest_source).encode("utf-8")
    ).hexdigest()
    return title, items, digest, filtered_stadium


def fetch_latest_patch(
) -> tuple[str, list[tuple[str, str]], str, bool, str]:
    errors: list[str] = []

    for url in candidate_urls():
        try:
            html = fetch_html(url)
            title, items, digest, filtered = parse_latest_patch(html)
            print(f"패치 발견: {title} ({url})")
            return title, items, digest, filtered, url
        except (requests.RequestException, RuntimeError) as exc:
            message = f"{url}: {exc}"
            errors.append(message)
            print("건너뜀:", message)

    raise RuntimeError(
        "최근 월별 페이지와 메인 페이지에서 패치를 찾지 못했습니다.\n"
        + "\n".join(errors)
    )


def format_summary(
    title: str,
    items: Iterable[tuple[str, str]],
    source_url: str,
) -> list[str]:
    lines = [
        f"# {title}",
        "※ 스타디움 관련 내용 제외",
        f"<{source_url}>",
        "",
    ]

    previous = ""
    for tag_name, text in items:
        if text == previous:
            continue
        previous = text

        if tag_name in {"h1", "h2", "h3", "h4"}:
            line = f"## {text}"
        elif tag_name == "h5":
            line = f"### {text}"
        elif tag_name == "h6":
            line = f"**{text}**"
        elif tag_name == "li":
            line = f"- {text}"
        elif tag_name == "p":
            # 긴 개발자 설명은 제외하고 역할군·영웅·기술명 등 짧은 표제만 남깁니다.
            if len(text) > 100:
                continue
            line = f"**{text}**"
        else:
            continue

        if line not in lines[-3:]:
            lines.append(line)

    return lines


def split_messages(lines: list[str]) -> list[str]:
    chunks: list[str] = []
    current = ""

    for line in lines:
        candidate = f"{current}\n{line}".strip() if current else line
        if len(candidate) <= MESSAGE_LIMIT:
            current = candidate
            continue

        if current:
            chunks.append(current)
        current = line[:MESSAGE_LIMIT]

    if current:
        chunks.append(current)

    if len(chunks) > MAX_MESSAGES:
        chunks = chunks[:MAX_MESSAGES]
        suffix = (
            "\n\n※ 패치 내용이 길어 일부만 표시했습니다. "
            f"전체 내용: <{BASE_URL}>"
        )
        chunks[-1] = chunks[-1][:(MESSAGE_LIMIT - len(suffix))] + suffix

    return chunks


def send_to_discord(webhook_url: str, messages: list[str]) -> None:
    endpoint = webhook_url.rstrip("/") + "?wait=true"

    for index, message in enumerate(messages, start=1):
        if len(messages) > 1:
            message = f"**[{index}/{len(messages)}]**\n{message}"

        response = requests.post(
            endpoint,
            json={
                "username": "오버워치 일반 패치 알림",
                "content": message,
                "allowed_mentions": {"parse": []},
            },
            timeout=30,
        )
        response.raise_for_status()
        time.sleep(1)


def load_state() -> dict[str, str]:
    if not STATE_FILE.exists():
        return {}

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(title: str, digest: str, source_url: str) -> None:
    state = {
        "title": title,
        "hash": digest,
        "source_url": source_url,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "filter": "exclude_stadium_monthly_v2",
    }
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL 환경 변수가 없습니다.", file=sys.stderr)
        return 2

    title, items, digest, filtered_stadium, source_url = fetch_latest_patch()
    state = load_state()
    previous_hash = state.get("hash", "")

    if previous_hash == digest:
        print(f"변경 없음: {title}")
        return 0

    if not items and filtered_stadium:
        save_state(title, digest, source_url)
        print(f"스타디움 전용 패치 제외: {title}")
        return 0

    if not previous_hash and not SEND_ON_FIRST_RUN:
        save_state(title, digest, source_url)
        print(f"최초 상태만 저장: {title}")
        return 0

    lines = format_summary(title, items, source_url)
    messages = split_messages(lines)
    send_to_discord(webhook_url, messages)
    save_state(title, digest, source_url)

    change_type = (
        "최초 전송"
        if not previous_hash
        else "새 일반 패치 또는 일반 본문 수정 감지"
    )
    print(f"{change_type}: {title} / {len(messages)}개 메시지 전송")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
