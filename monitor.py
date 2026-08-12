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



def heading_level(tag_name: str) -> int | None:
    if re.fullmatch(r"h[1-6]", tag_name):
        return int(tag_name[1])
    return None




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
) -> tuple[str, list[tuple[str, str]], str]:
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
    items: list[tuple[str, str]] = []
    raw_parts = [title]

    for node in title_node.find_all_next(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]
    ):
        text = clean_text(node.get_text(" ", strip=True))
        if not text:
            continue

        if node is not title_node and is_patch_title(text):
            break

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

    if not items:
        raise RuntimeError("최신 패치 본문을 찾지 못했습니다.")

    digest = hashlib.sha256(
        "\n".join(raw_parts).encode("utf-8")
    ).hexdigest()
    return title, items, digest


def fetch_latest_patch(
) -> tuple[str, list[tuple[str, str]], str, str]:
    errors: list[str] = []

    for url in candidate_urls():
        try:
            html = fetch_html(url)
            title, items, digest = parse_latest_patch(html)
            print(f"패치 발견: {title} ({url})")
            return title, items, digest, url
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
                "username": "오버워치 패치 알림",
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
        "parser": "monthly_all_patch_v1",
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

    title, items, digest, source_url = fetch_latest_patch()
    state = load_state()
    previous_hash = state.get("hash", "")

    if previous_hash == digest:
        print(f"변경 없음: {title}")
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
        else "새 패치 또는 본문 수정 감지"
    )
    print(f"{change_type}: {title} / {len(messages)}개 메시지 전송")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())