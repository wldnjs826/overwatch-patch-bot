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

PATCH_URL = "https://overwatch.blizzard.com/ko-kr/news/patch-notes/"
STATE_FILE = Path("state.json")
MESSAGE_LIMIT = 1900
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "8"))
SEND_ON_FIRST_RUN = os.getenv("SEND_ON_FIRST_RUN", "true").lower() == "true"

USER_AGENT = (
    "Mozilla/5.0 (compatible; OverwatchPatchDiscordMonitor/1.0; "
    "+https://github.com/)"
)


def clean_text(value: str) -> str:
    value = value.replace("\u200b", "")
    return re.sub(r"\s+", " ", value).strip()


def fetch_patch_page() -> str:
    response = requests.get(
        PATCH_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def is_patch_title(text: str) -> bool:
    lowered = text.lower()
    return (
        ("패치 노트" in text or "patch notes" in lowered)
        and text.strip() not in {"패치 노트", "Patch Notes"}
    )


def parse_latest_patch(html: str) -> tuple[str, list[tuple[str, str]], str]:
    soup = BeautifulSoup(html, "html.parser")
    area = soup.find("main") or soup

    title_node: Tag | None = None
    for tag in area.find_all(["h2", "h3"]):
        text = clean_text(tag.get_text(" ", strip=True))
        if is_patch_title(text):
            title_node = tag
            break

    if title_node is None:
        raise RuntimeError("최신 패치 제목을 찾지 못했습니다. 블리자드 페이지 구조를 확인하세요.")

    title = clean_text(title_node.get_text(" ", strip=True))
    items: list[tuple[str, str]] = []
    raw_parts = [title]

    for node in title_node.find_all_next(["h3", "h4", "h5", "h6", "p", "li"]):
        if node.name == "h3":
            break

        text = clean_text(node.get_text(" ", strip=True))
        if not text or text in {"위로 이동", "Top"}:
            continue

        # 부모/자식 태그에서 같은 문장이 연속 중복되는 경우 제거
        if raw_parts and raw_parts[-1] == text:
            continue

        raw_parts.append(text)
        items.append((node.name, text))

    if len(raw_parts) < 2:
        raise RuntimeError("최신 패치 본문을 찾지 못했습니다.")

    digest = hashlib.sha256("\n".join(raw_parts).encode("utf-8")).hexdigest()
    return title, items, digest


def format_summary(title: str, items: Iterable[tuple[str, str]]) -> list[str]:
    lines = [
        f"# {title}",
        f"<{PATCH_URL}>",
        "",
    ]

    previous = ""
    for tag_name, text in items:
        if text == previous:
            continue
        previous = text

        if tag_name == "h4":
            line = f"## {text}"
        elif tag_name == "h5":
            line = f"### {text}"
        elif tag_name == "h6":
            line = f"**{text}**"
        elif tag_name == "li":
            line = f"- {text}"
        elif tag_name == "p":
            # 긴 개발자 설명은 제외하고 역할군·영웅·기술명 등 짧은 표제만 남김
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
            f"전체 내용: <{PATCH_URL}>"
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


def save_state(title: str, digest: str) -> None:
    state = {
        "title": title,
        "hash": digest,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
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

    html = fetch_patch_page()
    title, items, digest = parse_latest_patch(html)
    state = load_state()
    previous_hash = state.get("hash", "")

    if previous_hash == digest:
        print(f"변경 없음: {title}")
        return 0

    if not previous_hash and not SEND_ON_FIRST_RUN:
        save_state(title, digest)
        print(f"최초 상태만 저장: {title}")
        return 0

    lines = format_summary(title, items)
    messages = split_messages(lines)
    send_to_discord(webhook_url, messages)
    save_state(title, digest)

    change_type = "최초 전송" if not previous_hash else "새 패치 또는 본문 수정 감지"
    print(f"{change_type}: {title} / {len(messages)}개 메시지 전송")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
