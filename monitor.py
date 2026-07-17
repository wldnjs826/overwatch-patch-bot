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
    "Mozilla/5.0 (compatible; OverwatchPatchDiscordMonitor/1.1; "
    "+https://github.com/)"
)


# 스타디움이 아닌 큰 구역으로 판단할 때 사용하는 표제어입니다.
NORMAL_SECTION_PATTERN = re.compile(
    r"^(?:"
    r"일반(?:\s*업데이트)?|"
    r"일반\s*모드|"
    r"버그\s*수정|"
    r"영웅(?:\s*밸런스)?\s*업데이트|"
    r"돌격|공격|지원|"
    r"핵심\s*게임(?:\s*업데이트)?|"
    r"경쟁전(?:\s*업데이트)?|"
    r"전장(?:\s*업데이트)?|"
    r"빠른\s*대전|자유\s*역할|역할\s*고정|"
    r"6대6|아케이드|미스터리\s*영웅|"
    r"시스템(?:\s*업데이트)?|UI(?:\s*업데이트)?"
    r")(?:\s*[:：-].*)?$",
    re.IGNORECASE,
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


def is_stadium_patch_title(text: str) -> bool:
    lowered = text.lower()
    return "스타디움" in text or "stadium" in lowered


def heading_level(tag_name: str) -> int | None:
    if re.fullmatch(r"h[1-6]", tag_name):
        return int(tag_name[1])
    return None


def is_stadium_section_title(tag_name: str, text: str) -> bool:
    """스타디움 구역의 시작 표제인지 판단합니다.

    일반 문장 안에 '스타디움'이 들어간 경우까지 잘못 제외하지 않도록
    제목 태그 또는 짧은 문단 표제만 대상으로 합니다.
    """
    if tag_name == "li" or len(text) > 60:
        return False

    lowered = text.lower()
    contains_stadium = "스타디움" in text or "stadium" in lowered
    if not contains_stadium:
        return False

    if heading_level(tag_name) is not None:
        return True

    if tag_name != "p":
        return False

    compact = re.sub(r"\s+", "", text).lower()
    # 짧은 표제 형태만 허용합니다.
    return (
        compact == "스타디움"
        or compact.startswith("스타디움업데이트")
        or compact.startswith("스타디움영웅")
        or compact.startswith("스타디움버그")
        or compact.startswith("스타디움밸런스")
        or compact.endswith("스타디움업데이트")
        or compact.endswith("스타디움버그수정")
        or compact.startswith("stadium")
    )


def is_normal_paragraph_section_title(text: str) -> bool:
    if len(text) > 50:
        return False
    return bool(NORMAL_SECTION_PATTERN.fullmatch(text.strip()))


def parse_latest_patch(
    html: str,
) -> tuple[str, list[tuple[str, str]], str, bool]:
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
    stadium_only_title = is_stadium_patch_title(title)

    items: list[tuple[str, str]] = []
    raw_parts = [title]
    filtered_stadium = False
    skipping_stadium = stadium_only_title
    stadium_heading_level: int | None = None

    if stadium_only_title:
        filtered_stadium = True

    for node in title_node.find_all_next(["h3", "h4", "h5", "h6", "p", "li"]):
        # 다음 패치 노트가 시작되면 종료합니다.
        if node.name == "h3":
            break

        text = clean_text(node.get_text(" ", strip=True))
        if not text or text in {"위로 이동", "Top"}:
            continue

        if stadium_only_title:
            # 제목 자체가 스타디움 전용 패치라면 전체를 무시합니다.
            continue

        if not skipping_stadium and is_stadium_section_title(node.name, text):
            skipping_stadium = True
            filtered_stadium = True
            stadium_heading_level = heading_level(node.name)
            continue

        if skipping_stadium:
            current_level = heading_level(node.name)

            if stadium_heading_level is not None:
                # 제목 태그로 시작된 스타디움 구역은 같은 단계 또는 상위 단계의
                # 다음 비스타디움 제목이 나오면 끝납니다.
                if (
                    current_level is not None
                    and current_level <= stadium_heading_level
                    and not is_stadium_section_title(node.name, text)
                ):
                    skipping_stadium = False
                    stadium_heading_level = None
                else:
                    continue
            else:
                # '스타디움'이 짧은 p 표제로 표시된 구조에서는 다음 큰 제목(h4)
                # 또는 '일반/버그 수정/영웅 업데이트' 같은 p 표제에서 빠져나옵니다.
                if (
                    (node.name == "h4" and not is_stadium_section_title(node.name, text))
                    or (node.name == "p" and is_normal_paragraph_section_title(text))
                ):
                    skipping_stadium = False
                else:
                    continue

        # 부모/자식 태그에서 같은 문장이 연속 중복되는 경우 제거
        if raw_parts and raw_parts[-1] == text:
            continue

        raw_parts.append(text)
        items.append((node.name, text))

    if not items and not filtered_stadium:
        raise RuntimeError("최신 일반 모드 패치 본문을 찾지 못했습니다.")

    # 스타디움 내용은 해시에서도 제외합니다.
    # 따라서 스타디움 항목만 수정된 경우 디스코드에 다시 올라가지 않습니다.
    digest_source = raw_parts if items else [title, "[STADIUM_ONLY_SKIPPED]"]
    digest = hashlib.sha256("\n".join(digest_source).encode("utf-8")).hexdigest()
    return title, items, digest, filtered_stadium


def format_summary(title: str, items: Iterable[tuple[str, str]]) -> list[str]:
    lines = [
        f"# {title}",
        "※ 스타디움 관련 내용 제외",
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


def save_state(title: str, digest: str) -> None:
    state = {
        "title": title,
        "hash": digest,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "filter": "exclude_stadium_v1",
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
    title, items, digest, filtered_stadium = parse_latest_patch(html)
    state = load_state()
    previous_hash = state.get("hash", "")

    if previous_hash == digest:
        print(f"변경 없음: {title}")
        return 0

    # 최신 패치가 스타디움 전용이면 기록만 갱신하고 디스코드에는 보내지 않습니다.
    if not items and filtered_stadium:
        save_state(title, digest)
        print(f"스타디움 전용 패치 제외: {title}")
        return 0

    if not previous_hash and not SEND_ON_FIRST_RUN:
        save_state(title, digest)
        print(f"최초 상태만 저장: {title}")
        return 0

    lines = format_summary(title, items)
    messages = split_messages(lines)
    send_to_discord(webhook_url, messages)
    save_state(title, digest)

    change_type = "최초 전송" if not previous_hash else "새 일반 패치 또는 일반 본문 수정 감지"
    print(f"{change_type}: {title} / {len(messages)}개 메시지 전송")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
