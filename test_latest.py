from __future__ import annotations

import os
import sys

import monitor


def main() -> int:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

    if not webhook_url:
        print("DISCORD_WEBHOOK_URL 환경 변수가 없습니다.", file=sys.stderr)
        return 2

    try:
        patches = monitor.fetch_recent_patches()
    except Exception as exc:
        print(f"패치 확인 실패: {exc}", file=sys.stderr)
        return 1

    latest = monitor.select_delivery_patches(patches)

    if not latest or not monitor.check_korean_patch(latest[0].items).is_korean:
        print("최신 넥슨 공지의 한국어 본문을 확인하지 못했습니다.", file=sys.stderr)
        return 1

    patch = latest[0]

    print("===== 테스트 전송 =====")
    print(f"선택된 패치: {patch.patch_id} / {patch.title}")
    print(f"출처: {patch.source_name} / {patch.source_url}")
    print("state.json은 읽거나 수정하지 않습니다.")

    payloads = monitor.build_discord_payloads(patch)

    if payloads:
        payloads[0] = dict(payloads[0])
        original = str(payloads[0].get("content", ""))
        payloads[0]["content"] = (
            "🧪 **테스트 전송 — state.json 미변경**\n"
            + original
        )

    try:
        original_message_ids = monitor.send_to_discord(
            webhook_url,
            payloads,
        )

        summary_message_ids = monitor.send_summary_cards(
            webhook_url,
            patch,
        )

    except Exception as exc:
        print(f"Discord 테스트 전송 실패: {exc}", file=sys.stderr)
        return 1

    print(
        f"테스트 전송 완료: 원문 {len(original_message_ids)}개 / "
        f"요약 카드 {len(summary_message_ids)}개"
    )
    print("실제 자동 감시 state.json에는 영향이 없습니다.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
