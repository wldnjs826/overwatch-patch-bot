from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag


# ============================================================
# 기본 설정
# ============================================================

BASE_URL = "https://overwatch.blizzard.com/ko-kr/news/patch-notes/"
STATE_FILE = Path("state.json")

MESSAGE_LIMIT = 1900
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "12"))
SEND_ON_FIRST_RUN = os.getenv("SEND_ON_FIRST_RUN", "true").lower() == "true"

# 현재 달 + 이전 3개월
MONTH_LOOKBACK = int(os.getenv("MONTH_LOOKBACK", "4"))

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


@dataclass
class Patch:
    title: str
    date_key: str
    same_day_index: int
    patch_id: str
    items: list[tuple[str, str]]
    body_hash: str
    source_url: str


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
# 텍스트 / 날짜 유틸
# ============================================================

def clean_text(value: str) -> str:
    value = value.replace("\u200b", "")
    return re.sub(r"\s+", " ", value).strip()


def shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + offset
    return index // 12, index % 12 + 1


def candidate_monthly_urls() -> list[str]:
    now = datetime.now(timezone.utc)
    urls: list[str] = []

    for offset in range(0, -MONTH_LOOKBACK, -1):
        year, month = shift_month(now.year, now.month, offset)
        urls.append(f"{BASE_URL}live/{year}/{month:02d}/")

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

    has_patch_words = (
        "패치 노트" in text
        or "patch notes" in lowered
    )

    return has_patch_words and bool(extract_date_key(text))


def heading_level(tag_name: str) -> int | None:
    if re.fullmatch(r"h[1-6]", tag_name):
        return int(tag_name[1])
    return None


# ============================================================
# 패치 본문 언어 판별
# ============================================================

def check_korean_patch(items: list[tuple[str, str]]) -> LanguageCheck:
    """
    제목이 아니라 실제 패치 본문을 검사합니다.

    한국어 페이지에 영어 본문이 먼저 올라오는 경우를 막기 위해
    한글/영문 문자 비율과 한글이 포함된 본문 줄 수를 함께 봅니다.

    판별이 애매하면 보내지 않는 쪽으로 동작합니다.
    """

    texts = [
        clean_text(text)
        for _, text in items
        if clean_text(text)
    ]

    joined = "\n".join(texts)

    hangul_count = len(re.findall(r"[가-힣]", joined))
    latin_count = len(re.findall(r"[A-Za-z]", joined))
    alpha_count = hangul_count + latin_count

    meaningful_lines = [
        text
        for text in texts
        if len(re.findall(r"[가-힣A-Za-z]", text)) >= 3
    ]

    korean_lines = sum(
        1
        for text in meaningful_lines
        if re.search(r"[가-힣]", text)
    )

    total_lines = len(meaningful_lines)
    hangul_ratio = (
        hangul_count / alpha_count
        if alpha_count
        else 0.0
    )

    # 본문이 너무 짧으면 안전하게 대기
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

    # 짧은 한국어 핫픽스도 잡을 수 있게:
    # 한글 8자 이상 + 문자 중 한글 비율 50% 이상
    if hangul_count >= 8 and hangul_ratio >= 0.50:
        return LanguageCheck(
            True,
            hangul_count,
            latin_count,
            hangul_ratio,
            korean_lines,
            total_lines,
            "한국어 본문으로 판별",
        )

    # 영웅명/기술명 등이 영어인 긴 한국어 패치:
    # 한글 20자 이상 + 한글 비율 30% 이상 + 한국어 줄 2개 이상
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


def is_korean_patch(items: list[tuple[str, str]]) -> bool:
    return check_korean_patch(items).is_korean


# ============================================================
# HTML 패치 블록 파싱
# ============================================================

def parse_patch_blocks(
    html: str,
    source_url: str,
) -> list[Patch]:
    """
    한 페이지 안의 패치 제목을 전부 찾습니다.

    Blizzard 패치 페이지는 최신 글이 위쪽에 추가되는 구조를 전제로,
    같은 날짜 패치의 번호는 '아래쪽(오래된 것)부터 1, 2, 3...'으로
    부여합니다.

    예:
      같은 날짜에 기존 패치 2개
        위: 새 패치  -> #2
        아래: 구 패치 -> #1

      같은 날 새 글이 맨 위에 추가되면
        새 글 -> #3
        기존 -> #2
        기존 -> #1

    따라서 같은 날짜에 패치가 추가돼도 기존 patch_id가 유지됩니다.
    """

    soup = BeautifulSoup(html, "html.parser")
    area = soup.find("main") or soup

    title_nodes: list[Tag] = []

    for tag in area.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6"]
    ):
        text = clean_text(tag.get_text(" ", strip=True))

        if is_patch_title(text):
            title_nodes.append(tag)

    if not title_nodes:
        return []

    raw_patches: list[dict] = []

    for title_node in title_nodes:
        title = clean_text(
            title_node.get_text(" ", strip=True)
        )

        date_key = extract_date_key(title)

        if not date_key:
            continue

        title_level = heading_level(title_node.name) or 3

        items: list[tuple[str, str]] = []
        raw_parts = [title]

        for node in title_node.find_all_next(
            ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]
        ):
            if node is title_node:
                continue

            text = clean_text(
                node.get_text(" ", strip=True)
            )

            if not text:
                continue

            # 다음 날짜 패치 제목이면 현재 패치 종료
            if is_patch_title(text):
                break

            current_level = heading_level(node.name)

            # 현재 패치 글의 상위 영역으로 빠져나가면 종료
            if (
                current_level is not None
                and current_level < title_level
            ):
                break

            if text in {
                "위로 이동",
                "Top",
                "Top of post",
                "Back to top",
                "패치 노트의 처음으로 돌아가기",
            }:
                continue

            lowered = text.lower()

            # 페이지 하단 공통 영역
            if "general discussion forum" in lowered:
                break

            if "bug report forum" in lowered:
                break

            if (
                "기술 지원 토론장" in text
                or "버그 제보 토론장" in text
            ):
                break

            if text in {
                "패치 노트",
                "Live Patch Notes",
            }:
                continue

            if raw_parts and raw_parts[-1] == text:
                continue

            raw_parts.append(text)
            items.append((node.name, text))

        if not items:
            continue

        body_hash = hashlib.sha256(
            "\n".join(raw_parts).encode("utf-8")
        ).hexdigest()

        raw_patches.append(
            {
                "title": title,
                "date_key": date_key,
                "items": items,
                "body_hash": body_hash,
            }
        )

    # 페이지 내 각 날짜별 총 패치 개수
    totals = Counter(
        item["date_key"]
        for item in raw_patches
    )

    # 페이지는 최신순이므로 위에서 몇 번째인지 센 후,
    # 아래(오래된 패치) 기준 번호로 바꿉니다.
    seen_from_top: Counter[str] = Counter()

    patches: list[Patch] = []

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

        patches.append(
            Patch(
                title=item["title"],
                date_key=date_key,
                same_day_index=same_day_index,
                patch_id=patch_id,
                items=item["items"],
                body_hash=item["body_hash"],
                source_url=source_url,
            )
        )

    return patches


def fetch_recent_patches() -> list[Patch]:
    """
    최근 월별 페이지를 모두 확인합니다.
    같은 patch_id가 중복될 경우 더 먼저 확인한 페이지의 것을 사용합니다.

    월별 페이지에서 아무 패치도 찾지 못했을 때만 메인 페이지를 확인합니다.
    """

    found: dict[str, Patch] = {}
    errors: list[str] = []

    for url in candidate_monthly_urls():
        try:
            html = fetch_html(url)
            patches = parse_patch_blocks(html, url)

            if not patches:
                print(f"패치 제목 없음: {url}")
                continue

            print(
                f"패치 {len(patches)}개 발견: {url}"
            )

            for patch in patches:
                found.setdefault(
                    patch.patch_id,
                    patch,
                )

        except requests.RequestException as exc:
            message = f"{url}: {exc}"
            errors.append(message)
            print("건너뜀:", message)

    # 월별 페이지를 하나도 읽지 못했거나 패치를 못 찾은 경우
    if not found:
        try:
            html = fetch_html(BASE_URL)
            patches = parse_patch_blocks(
                html,
                BASE_URL,
            )

            for patch in patches:
                found.setdefault(
                    patch.patch_id,
                    patch,
                )

        except requests.RequestException as exc:
            errors.append(f"{BASE_URL}: {exc}")

    if not found:
        raise RuntimeError(
            "최근 패치노트를 찾지 못했습니다.\n"
            + "\n".join(errors)
        )

    # 오래된 날짜 → 최신 날짜,
    # 같은 날짜에서는 #1 → #2 → #3 순서
    return sorted(
        found.values(),
        key=lambda patch: (
            patch.date_key,
            patch.same_day_index,
        ),
    )


# ============================================================
# Discord 메시지 구성
# ============================================================

def format_summary(patch: Patch) -> list[str]:
    lines = [
        f"# {patch.title}",
        f"<{patch.source_url}>",
        "",
    ]

    previous = ""

    for tag_name, text in patch.items:
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
            # 패치 본문은 길더라도 임의로 버리지 않습니다.
            line = text

        else:
            continue

        if not lines or line != lines[-1]:
            lines.append(line)

    return lines


def split_messages(lines: list[str]) -> list[str]:
    chunks: list[str] = []
    current = ""

    for line in lines:
        # 한 줄 자체가 Discord 제한보다 긴 경우에도 안전하게 분할
        remaining = line

        while len(remaining) > MESSAGE_LIMIT:
            piece = remaining[:MESSAGE_LIMIT]

            if current:
                chunks.append(current)
                current = ""

            chunks.append(piece)
            remaining = remaining[MESSAGE_LIMIT:]

        candidate = (
            f"{current}\n{remaining}".strip()
            if current
            else remaining
        )

        if len(candidate) <= MESSAGE_LIMIT:
            current = candidate
            continue

        if current:
            chunks.append(current)

        current = remaining

    if current:
        chunks.append(current)

    if len(chunks) > MAX_MESSAGES:
        chunks = chunks[:MAX_MESSAGES]

        suffix = (
            "\n\n※ 패치 내용이 길어 일부만 표시했습니다. "
            f"전체 내용: <{BASE_URL}>"
        )

        chunks[-1] = (
            chunks[-1][
                :(MESSAGE_LIMIT - len(suffix))
            ]
            + suffix
        )

    return chunks


def send_to_discord(
    webhook_url: str,
    messages: list[str],
) -> None:
    endpoint = (
        webhook_url.rstrip("/")
        + "?wait=true"
    )

    for index, message in enumerate(
        messages,
        start=1,
    ):
        if len(messages) > 1:
            prefix = (
                f"**[{index}/{len(messages)}]**\n"
            )

            # 번호를 붙인 뒤에도 2,000자를 넘지 않게 조정
            message = (
                prefix
                + message[
                    :MESSAGE_LIMIT - len(prefix)
                ]
            )

        response = requests.post(
            endpoint,
            json={
                "username": "오버워치 패치 알림",
                "content": message,
                "allowed_mentions": {
                    "parse": []
                },
            },
            timeout=30,
        )

        response.raise_for_status()
        time.sleep(1)


# ============================================================
# state.json
# ============================================================

def empty_state() -> dict:
    return {
        "version": 4,
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

        if not isinstance(data, dict):
            return empty_state()

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
        "source_url": patch.source_url,
        "status": status,
        "first_seen_utc": now,
        "last_seen_utc": now,
    }

    if status == "sent":
        record["sent_at_utc"] = now

    return record


def save_state(state: dict) -> None:
    state["version"] = 4
    state["updated_at_utc"] = datetime.now(
        timezone.utc
    ).isoformat()

    patches = state.get(
        "patches",
        {},
    )

    if not isinstance(patches, dict):
        patches = {}

    # 너무 오래된 기록이 무한히 쌓이지 않도록 최근 200개만 유지
    records = sorted(
        patches.values(),
        key=lambda record: (
            record.get("date_key", ""),
            int(
                record.get(
                    "same_day_index",
                    0,
                )
            ),
        ),
    )

    records = records[-200:]

    state["patches"] = {
        record["patch_id"]: record
        for record in records
        if record.get("patch_id")
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
    """
    구버전 state.json 예:
      {
        "title": "...",
        "hash": "...",
        "source_url": "..."
      }

    기존 봇에서 이미 봤던 과거 패치가 새 버전 설치 직후
    한꺼번에 재전송되지 않도록 기준점을 잡습니다.

    구버전의 title 날짜까지 발견된 패치는 전송 완료로 이관합니다.
    같은 날짜의 복수 패치도 모두 기준선에 포함합니다.

    이후 같은 날짜에 새 패치가 맨 위에 추가되면
    #03, #04처럼 새로운 patch_id가 생기므로 정상 전송됩니다.
    """

    if isinstance(
        state.get("patches"),
        dict,
    ):
        return False

    old_title = str(
        state.get("title", "")
    )

    old_hash = str(
        state.get("hash", "")
    )

    # 이미 새 형식인데 patches 키만 빠진 경우
    if not old_title and not old_hash:
        state.clear()
        state.update(empty_state())
        return False

    old_date = extract_date_key(
        old_title
    )

    state["version"] = 4
    state["patches"] = {}

    migrated = False

    if old_date:
        for patch in patches:
            if patch.date_key <= old_date:
                state["patches"][
                    patch.patch_id
                ] = make_record(
                    patch,
                    "sent",
                )

                state["patches"][
                    patch.patch_id
                ][
                    "migration"
                ] = (
                    "legacy_baseline"
                )

                migrated = True

    elif old_hash:
        # 날짜를 못 읽은 경우 hash가 정확히 일치하는 패치만 이관
        for patch in patches:
            if patch.body_hash == old_hash:
                state["patches"][
                    patch.patch_id
                ] = make_record(
                    patch,
                    "sent",
                )

                state["patches"][
                    patch.patch_id
                ][
                    "migration"
                ] = (
                    "legacy_hash_match"
                )

                migrated = True

    if migrated:
        print(
            "기존 state.json을 새 형식으로 이관했습니다. "
            "기존 패치는 재전송하지 않습니다."
        )

    return migrated


def initialize_fresh_state(
    state: dict,
    patches: list[Patch],
) -> None:
    """
    state.json 자체가 없는 완전한 첫 실행에서
    최근 4개월치를 한꺼번에 전송하지 않도록 합니다.

    최신 날짜보다 오래된 패치는 기준선(sent)으로 저장합니다.
    SEND_ON_FIRST_RUN=true면 최신 날짜 패치만 실제 처리합니다.
    """

    state.setdefault(
        "patches",
        {},
    )

    if state["patches"]:
        return

    if not patches:
        return

    newest_date = max(
        patch.date_key
        for patch in patches
    )

    for patch in patches:
        if (
            patch.date_key < newest_date
            or not SEND_ON_FIRST_RUN
        ):
            record = make_record(
                patch,
                "sent",
            )

            record["migration"] = (
                "fresh_install_baseline"
            )

            state["patches"][
                patch.patch_id
            ] = record

    if not SEND_ON_FIRST_RUN:
        print(
            "최초 실행: 현재 발견된 패치를 기준선으로만 저장합니다."
        )


# ============================================================
# 패치 처리
# ============================================================

def update_seen_record(
    record: dict,
    patch: Patch,
) -> None:
    """
    이미 알고 있는 동일 patch_id가 수정된 경우
    최신 hash/title만 갱신합니다.

    status=sent 패치는 body_hash가 변해도 다시 전송하지 않습니다.
    """

    record["title"] = patch.title
    record["body_hash"] = patch.body_hash
    record["source_url"] = patch.source_url
    record["last_seen_utc"] = datetime.now(
        timezone.utc
    ).isoformat()


def describe_language(
    result: LanguageCheck,
) -> str:
    return (
        f"한글={result.hangul_count}, "
        f"영문={result.latin_count}, "
        f"한글비율={result.hangul_ratio:.1%}, "
        f"한국어줄={result.korean_lines}/{result.total_lines}"
    )


def process_patch(
    patch: Patch,
    state: dict,
    webhook_url: str,
) -> str:
    """
    반환값:
      sent
      already_sent
      pending_korean
    """

    records: dict = state.setdefault(
        "patches",
        {},
    )

    record = records.get(
        patch.patch_id
    )

    print(
        f"\n[{patch.patch_id}] {patch.title}"
    )

    # 이미 Discord로 보낸 동일 논리 패치
    if (
        record
        and record.get("status") == "sent"
    ):
        changed = (
            record.get("body_hash")
            != patch.body_hash
        )

        update_seen_record(
            record,
            patch,
        )

        if changed:
            print(
                "이미 전송한 패치의 본문 수정 감지 "
                "→ 재전송하지 않음"
            )
        else:
            print(
                "이미 전송 완료 → 건너뜀"
            )

        return "already_sent"

    language = check_korean_patch(
        patch.items
    )

    print(
        f"언어 판별: {language.reason} "
        f"({describe_language(language)})"
    )

    # 영어/불확실하면 Discord 전송 금지
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
            )

            record["status"] = (
                "pending_korean"
            )

        record[
            "language_reason"
        ] = language.reason

        print(
            "본문 영어 또는 판별 불확실 "
            "→ 공식 한국어 업데이트 대기"
        )

        return "pending_korean"

    # 한국어 패치인 경우에만 Discord 전송
    lines = format_summary(
        patch
    )

    messages = split_messages(
        lines
    )

    # 실패하면 예외가 발생하므로 아래 sent 저장까지 도달하지 않습니다.
    send_to_discord(
        webhook_url,
        messages,
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
        )

        record["status"] = "sent"
        record["sent_at_utc"] = now

    record[
        "language_reason"
    ] = language.reason

    print(
        f"한국어 패치 감지 → Discord 전송 완료 "
        f"({len(messages)}개 메시지)"
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

        # 파싱/네트워크 실패 시 state를 건드리지 않습니다.
        return 1

    print(
        f"\n총 {len(patches)}개 패치 블록 확인"
    )

    state = load_state()

    # 구버전 state.json 자동 이관
    migrated = migrate_legacy_state(
        state,
        patches,
    )

    if migrated:
        save_state(state)

    # 완전한 새 설치라면 과거 패치 폭탄 방지
    initialize_fresh_state(
        state,
        patches,
    )

    sent_count = 0
    pending_count = 0
    already_count = 0

    try:
        for patch in patches:
            result = process_patch(
                patch,
                state,
                webhook_url,
            )

            if result == "sent":
                sent_count += 1

                # Discord 전송 성공 직후 즉시 저장
                save_state(state)

            elif result == "pending_korean":
                pending_count += 1

                # pending 상태도 저장해서 추적
                save_state(state)

            elif result == "already_sent":
                already_count += 1

    except requests.RequestException as exc:
        print(
            f"Discord 전송 실패: {exc}",
            file=sys.stderr,
        )

        # 이미 성공한 전송분은 직전에 저장되었고,
        # 실패한 현재 패치는 sent 처리되지 않습니다.
        return 1

    save_state(state)

    print(
        "\n===== 실행 결과 ====="
    )

    print(
        f"새로 전송: {sent_count}"
    )

    print(
        f"한국어 대기: {pending_count}"
    )

    print(
        f"이미 전송됨: {already_count}"
    )

    if sent_count == 0:
        print(
            "새로 전송할 한국어 패치 없음"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
