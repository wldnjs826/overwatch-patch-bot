import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

import monitor
import summary_cards


class FreeClassificationTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(
            requests.sessions.Session, "request",
            side_effect=AssertionError("Offline classification must not call a network API"),
        ))

    def make_patch(self, hero, ability, lines, mode="일반전", role="공격 영웅"):
        items = [("h4", "영웅 업데이트" if mode == "일반전" else "스타디움 업데이트"),
                 ("h4", role), ("h5", hero), ("h6", ability)]
        items.extend(("li", line) for line in lines)
        title = "오버워치 패치 노트 - 2026년 11월 4일"
        return monitor.assign_patch_ids([{
            "title": title, "date_key": "2026-11-04", "items": items, "images": [],
            "body_hash": monitor.build_body_hash(title, items),
            "source_url": "https://overwatch.nexon.com/news/patchnotes/858/patch-2026-11-03",
            "source_name": "nexon",
        }])[0]

    def test_official_metrics_use_hero_ability_and_mode_in_both_card_and_row(self):
        # Verbatim official changes from the source URL above, retrieved 2026-11-05.
        cases = [
            ("겐지", "튕겨내기", "지속 시간이 2초에서 1.5초로 감소했습니다.", "일반전", "nerf"),
            ("엠레", "사이버 파편 수류탄", "폭발 시간이 0.6초에서 0.5초로 감소했습니다.", "일반전", "buff"),
            ("벤데타", "팔라틴 팽", "내리치기 도약 속도가 11에서 9.5로 감소했습니다.", "일반전", "nerf"),
            ("제트팩 캣", "정신 없는 비행", "가속도가 초당 25미터에서 28미터로 증가했습니다.", "일반전", "buff"),
            ("솜브라", "긴급 패치", "지속 시간이 12초에서 10초로 감소했습니다.", "일반전", "nerf"),
            ("솜브라", "사이버 스페이스", "약화 효과가 50%에서 40%로 감소했습니다.", "일반전", "nerf"),
            ("벤데타", "마구잡이 맹공격 - 파워", "맹공의 중첩 증가에 필요한 처치 횟수가 2회에서 3회로 증가했습니다.", "스타디움", "nerf"),
        ]
        for hero, ability, text, mode, expected in cases:
            with self.subTest(hero=hero, ability=ability):
                entries, _ = monitor.prepare_card_data(self.make_patch(hero, ability, [text], mode))
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0]["category"], expected)
                self.assertEqual(entries[0]["changes"][0]["category"], expected)

    def test_context_does_not_leak_to_other_heroes_modes_or_abilities(self):
        for hero, mode, text in [
            ("다른 영웅", "일반전", "튕겨내기: 지속 시간이 2초에서 1.5초로 감소했습니다."),
            ("겐지", "스타디움", "튕겨내기: 지속 시간이 2초에서 1.5초로 감소했습니다."),
            ("겐지", "일반전", "다른 기술: 지속 시간이 2초에서 1.5초로 감소했습니다."),
            ("겐지", "일반전", "지속 시간이 2초에서 1.5초로 감소했습니다."),
        ]:
            with self.subTest(hero=hero, mode=mode, text=text):
                self.assertEqual(monitor.classify_change_line(text, hero=hero, mode=mode), "review")

    def test_rules_apply_to_future_values_and_comparable_units(self):
        for text, expected in [
            ("지속 시간이 1.5초에서 2초로 증가했습니다.", "buff"),
            ("지속 시간이 1초에서 500밀리초로 감소했습니다.", "nerf"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(monitor.classify_change_line(
                    "튕겨내기: " + text, hero="겐지", mode="일반전"), expected)

    def test_context_never_overrides_negation_or_incompatible_units(self):
        for text in [
            "지속 시간이 2초에서 1.5초로 감소하지 않습니다.",
            "지속 시간이 20%에서 30%p로 변경되었습니다.",
            "적의 지속 시간이 2초에서 1.5초로 감소했습니다.",
            "지속 시간 감소량이 2초에서 1.5초로 감소했습니다.",
        ]:
            with self.subTest(text=text):
                self.assertEqual(monitor.classify_change_line(
                    "튕겨내기: " + text, hero="겐지", mode="일반전"), "review")

    def test_context_survives_clause_splitting_and_perks_keep_adjustment_rule(self):
        self.assertEqual(monitor.classify_change_line(
            "튕겨내기: 지속 시간이 2초에서 1.5초로 감소하고 재사용 대기시간이 8초에서 7초로 감소했습니다.",
            hero="겐지", mode="일반전"), "adjust")
        self.assertEqual(monitor.classify_change_line(
            "튕겨내기 - 주요 특전: 지속 시간이 2초에서 1.5초로 감소했습니다.",
            hero="겐지", mode="일반전"), "adjust")

    def test_ui_and_crosshair_changes_do_not_change_combat_category(self):
        lines = [
            "범위 내 아군과 현재 지휘의 외침 효과를 받고 있는 아군을 추적하는 신규 UI 요소를 추가했습니다.",
            "범위 내 아군과 현재 치유 파동 효과를 받고 있는 아군을 추적하는 신규 UI 요소를 추가했습니다.",
            "기본 조준선에 회전 조준선 설정을 추가했습니다.",
            "기본 조준선에서 두께 조준선 설정을 제거했습니다.",
        ]
        for text in lines:
            with self.subTest(text=text):
                entries, _ = monitor.prepare_card_data(self.make_patch(
                    "정커퀸", "지휘의 외침", ["재사용 대기시간이 9초에서 7초로 감소했습니다.", text]))
                self.assertEqual(entries[0]["category"], "buff")
                self.assertEqual([row["category"] for row in entries[0]["changes"]], ["buff", "neutral"])
        self.assertEqual(monitor.classify_change_line(
            "공격력이 10에서 12로 증가했습니다. 조준선이 변경되었습니다."), "buff")
        self.assertEqual(monitor.classify_change_line(
            "공격력이 10에서 12로 증가했습니다. 신규 UI 요소를 추가했습니다."), "buff")

    def test_official_role_heading_variants_keep_roles(self):
        for heading, expected in [("돌격 영웅", "돌격"), ("공격 영웅", "공격"),
                                  ("지원 영웅", "지원"), ("Support Heroes", "지원")]:
            with self.subTest(heading=heading):
                entries, _ = monitor.prepare_card_data(self.make_patch(
                    "겐지", "튕겨내기", ["지속 시간이 2초에서 1.5초로 감소했습니다."], role=heading))
                self.assertEqual(entries[0]["role"], expected)
        self.assertIsNone(monitor._role_from_heading("지원 영웅 업데이트"))

    def test_ambiguous_mechanics_keep_original_without_overriding_known_changes(self):
        unknown = "밀쳐내기 효과가 제거되었습니다."
        patch_note = self.make_patch("안란", "맹염 질주", [
            "공격력이 30에서 35로 증가했습니다.", unknown,
        ])
        entries, _ = monitor.prepare_card_data(patch_note)
        self.assertEqual([entry["category"] for entry in entries], ["buff", "review"])
        self.assertEqual(entries[1]["changes"], [{
            "text": "맹염 질주: " + unknown, "highlights": [], "category": "review",
        }])
        self.assertEqual(summary_cards.LABELS["review"], "변경 사항")
        self.assertEqual(summary_cards.ARROWS["review"], "•")

    def test_unclassified_patch_is_delivered_and_checkpointed_without_manual_input(self):
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(monitor, "STATE_FILE", directory / "state.json"))
        self.stack.enter_context(patch.object(monitor.time, "sleep"))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        messages = []

        def post(*args, **kwargs):
            messages.append(kwargs)
            response = Mock(status_code=200)
            response.json.return_value = {"id": str(len(messages))}
            return response

        self.stack.enter_context(patch.object(monitor.requests, "post", side_effect=post))
        patch_note = self.make_patch("안란", "맹염 질주", ["밀쳐내기 효과가 제거되었습니다."])
        state = monitor.empty_state()
        self.assertEqual(monitor.process_patch(patch_note, state, "https://discord.invalid/api/webhooks/test/token"), "sent")
        self.assertEqual(len(messages), 2)  # Full original, then rendered changes card.
        self.assertIn("밀쳐내기 효과가 제거되었습니다.", messages[0]["json"]["content"])
        record = monitor.load_state()["patches"][patch_note.patch_id]
        self.assertEqual(record["status"], "sent")
        self.assertEqual(record["summary_message_ids"], ["2"])
        self.assertEqual(record["summary_card_version"], monitor.SUMMARY_CARD_VERSION)
        self.assertEqual(monitor.process_patch(patch_note, state, "https://discord.invalid/api/webhooks/test/token"), "already_sent")
        self.assertEqual(len(messages), 2)


if __name__ == "__main__":
    unittest.main()
