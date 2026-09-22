from pathlib import Path
import unittest

import monitor


class SummaryTests(unittest.TestCase):
    def make_patch(self, items, date_key="2026-09-18"):
        return monitor.assign_patch_ids([{
            "title": "오버워치 패치 노트 - " + date_key, "date_key": date_key,
            "items": items, "images": [], "body_hash": "test",
            "source_url": "https://overwatch.nexon.com/news/patchnotes/830", "source_name": "nexon",
        }])[0]

    def summarize(self, items):
        return monitor.extract_balance_summary(self.make_patch(items))

    def test_roleless_nexon_hero_keeps_ability_changes(self):
        fixture = Path(__file__).parent / "fixtures" / "nexon-article.html"
        raw = monitor.parse_nexon_article(fixture.read_text(encoding="utf-8"), "https://overwatch.nexon.com/news/patchnotes/830")
        result = self.summarize(raw["items"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["hero"], "D.Mon")
        self.assertEqual(result[0]["role"], "영웅")
        self.assertEqual(result[0]["category"], "nerf")
        self.assertIn("추진기:", result[0]["changes"][1])

    def test_role_hero_ability_hierarchy_and_section_end(self):
        result = self.summarize([
            ("h4", "영웅 업데이트"), ("h4", "돌격"), ("h5", "D.Va"),
            ("h6", "부스터"), ("li", "재사용 대기시간이 5초에서 4초로 감소했습니다."),
            ("h5", "라인하르트"), ("li", "방어력이 200에서 250으로 증가했습니다."),
            ("h4", "버그 수정"), ("h5", "메르시"), ("li", "치유량이 잘못 감소하던 문제를 수정했습니다."),
        ])
        self.assertEqual([r["hero"] for r in result], ["D.Va", "라인하르트"])
        self.assertEqual([r["role"] for r in result], ["돌격", "돌격"])
        self.assertEqual([r["category"] for r in result], ["buff", "buff"])
        self.assertIn("부스터:", result[0]["changes"][0])

    def test_perk_change_forces_hero_into_adjustment_and_label_survives(self):
        result = self.summarize([
            ("h4", "영웅 업데이트"), ("h5", "D.Mon"),
            ("p", "집중 융합 - 주요 특전"), ("li", "탄환당 피해가 45에서 36으로 감소했습니다."),
            ("h6", "추진기"), ("li", "연료 소모 속도가 25에서 30으로 증가했습니다."),
        ])
        self.assertEqual(result[0]["category"], "adjust")
        self.assertIn("집중 융합 - 주요 특전:", result[0]["changes"][0])
        self.assertIn("추진기:", result[0]["changes"][1])
        self.assertEqual(monitor.classify_change_line(result[0]["changes"][0]), "adjust")

    def test_all_hero_changes_survive_without_eight_line_limit(self):
        lines = [("li", f"변경 {n}: 방어력이 200에서 {201 + n}로 증가했습니다.") for n in range(20)]
        result = self.summarize([("h4", "영웅 업데이트"), ("h5", "D.Va"), *lines])
        self.assertEqual(result[0]["changes"], [text for _, text in lines])

    def test_mixed_hero_and_each_change_have_separate_directions(self):
        result = self.summarize([
            ("h4", "영웅 업데이트"), ("h4", "공격"), ("h5", "정크랫"),
            ("h6", "충격 지뢰"), ("li", "재사용 대기시간이 8초에서 7초로 감소했습니다."),
            ("p", "니트로 부스트 - 보조 특전"), ("li", "추가 속도가 125%에서 100%로 감소했습니다."),
        ])
        self.assertEqual(result[0]["category"], "adjust")
        self.assertEqual([monitor.classify_change_line(line) for line in result[0]["changes"]], ["buff", "adjust"])

    def test_independent_opposing_clauses_are_mixed_adjustments(self):
        for text in ["공격력이 10에서 12로 증가하고 재사용 대기시간이 8초에서 9초로 증가했습니다.",
                     "공격력이 10% 증가하고 재사용 대기시간이 2초 증가했습니다."]:
            with self.subTest(text=text):
                self.assertEqual(monitor.classify_change_line(text), "adjust")

    def test_comma_separated_values_keep_numeric_direction(self):
        self.assertEqual(monitor.classify_change_line("생명력이 1,000에서 900으로 감소했습니다."), "nerf")
        self.assertEqual(monitor.classify_change_line("방어력이 900에서 1,000으로 증가했습니다."), "buff")

    def test_ambiguous_metrics_negation_and_incompatible_units_require_review(self):
        for text in ["재사용 대기시간 동안 이동 속도가 10%에서 20%로 증가했습니다.",
                     "공격력이 상향되지 않았습니다.",
                     "피해가 20에서 10으로 감소하지 않습니다.",
                     "공격력이 10%에서 15%p로 증가했습니다.",
                     "생명줄이 이제 새로운 방식으로 작동합니다."]:
            with self.subTest(text=text):
                self.assertEqual(monitor.classify_change_line(text), "review")
        self.assertEqual(monitor.classify_change_line("소용돌이 질주: 회복 시간이 0.5초에서 0.75초로 증가했습니다."), "nerf")

    def test_comparable_time_units_preserve_benefit_direction(self):
        self.assertEqual(monitor.classify_change_line("시전 시간이 1초에서 500밀리초로 감소했습니다."), "buff")
        self.assertEqual(monitor.classify_change_line("시전 시간이 500밀리초에서 1초로 증가했습니다."), "nerf")

    def test_required_metric_examples_follow_gameplay_benefit(self):
        for text, category in [
            ("생명력 175 → 200", "buff"),
            ("공격력 30 → 28", "nerf"),
            ("재사용 대기시간 12초 → 10초", "buff"),
            ("재사용 대기시간 8초 → 10초", "nerf"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(monitor.classify_change_line(text), category)

    def test_receiving_damage_and_damage_reduction_have_opposite_benefits(self):
        for text, category in [
            ("받는 피해가 20%에서 30%로 증가했습니다.", "nerf"),
            ("입는 피해가 30%에서 20%로 감소했습니다.", "buff"),
            ("받는 피해 감소량이 20%에서 30%로 증가했습니다.", "buff"),
            ("받는 피해 감소율이 30%에서 20%로 감소했습니다.", "nerf"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(monitor.classify_change_line(text), category)

    def test_healing_reduction_is_a_cost_without_inverting_falloff_range(self):
        for text, category in [
            ("치유량 감소가 75%에서 80%로 변경되었습니다.", "nerf"),
            ("치유량 감소가 75%에서 65%로 변경되었습니다.", "buff"),
            ("공격력 감소율 최소 사거리가 30미터에서 20미터로 감소했습니다.", "nerf"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(monitor.classify_change_line(text), category)

    def test_opposite_changes_in_separate_modes_do_not_make_adjustment(self):
        result = self.summarize([
            ("h4", "영웅 업데이트"), ("h4", "돌격"), ("h5", "D.Va"),
            ("li", "메카 기본 생명력이 175에서 200으로 증가했습니다."),
            ("h4", "스타디움 업데이트"), ("h4", "돌격"), ("h5", "D.Va"),
            ("li", "공격력이 30에서 28로 감소했습니다."),
        ])
        self.assertEqual(
            [(entry["mode"], entry["role"], entry["hero"], entry["category"]) for entry in result],
            [("일반전", "돌격", "D.Va", "buff"), ("스타디움", "돌격", "D.Va", "nerf")],
        )

    def test_unknown_changes_keep_original_text_in_separate_review_entry(self):
        unknown = "아군이 사망 구역 위에 있을 경우 자동으로 생명줄에 연결됩니다."
        patch = self.make_patch([
            ("h4", "영웅 업데이트"), ("h4", "지원"), ("h5", "제트팩 캣"),
            ("h6", "생체 냥냥탄"), ("li", "공격력이 4.5에서 4로 감소했습니다."),
            ("h6", "생명줄"), ("li", unknown),
        ])
        entries, general = monitor.prepare_card_data(patch)
        self.assertEqual([entry["category"] for entry in entries], ["nerf", "review"])
        self.assertEqual(entries[1]["changes"], [{
            "text": "생명줄: " + unknown, "highlights": [], "category": "review",
        }])
        self.assertEqual(general, [])
        self.assertIn(unknown, "\n".join(monitor.format_summary(patch)))

    def test_unknown_only_and_cosmetic_only_are_not_mixed_adjustments(self):
        result = self.summarize([
            ("h4", "영웅 업데이트"), ("h4", "지원"), ("h5", "제트팩 캣"),
            ("li", "아군이 사망 구역 위에 있을 경우 자동으로 생명줄에 연결됩니다."),
            ("h4", "공격"), ("h5", "위도우메이커"),
            ("li", "충전 효과음이 변경되었습니다."),
        ])
        self.assertEqual([(entry["hero"], entry["category"]) for entry in result],
                         [("제트팩 캣", "review"), ("위도우메이커", "neutral")])

    def test_roleless_hotfix_uses_explicit_role_from_other_official_patch(self):
        documented = self.make_patch([
            ("h4", "영웅 업데이트"), ("h4", "돌격"), ("h5", "D.Mon"),
            ("li", "생명력이 175에서 200으로 증가했습니다."),
        ], date_key="2026-09-09")
        hotfix = self.make_patch([
            ("h4", "영웅 업데이트"), ("h5", "D.Mon"),
            ("li", "공격력이 30에서 28로 감소했습니다."),
            ("h5", "확인되지 않은 영웅"), ("li", "생명력이 175에서 200으로 증가했습니다."),
        ])
        monitor.inherit_explicit_roles([hotfix, documented])
        entries = monitor.extract_balance_summary(hotfix)
        self.assertEqual([(entry["hero"], entry["role"]) for entry in entries],
                         [("D.Mon", "돌격"), ("확인되지 않은 영웅", "영웅")])

    def test_generic_fallback_keeps_regular_and_stadium_changes_separate(self):
        patch = self.make_patch([
            ("h4", "일반 업데이트"), ("li", "연습장의 표적 배치를 변경했습니다."),
            ("h4", "스타디움 업데이트"), ("li", "스타디움 상점의 구매 단계를 변경했습니다."),
        ])
        entries, general = monitor.prepare_card_data(patch)
        self.assertEqual(general, [])
        self.assertEqual({entry["mode"] for entry in entries}, {"일반전", "스타디움"})
        self.assertEqual({entry["category"] for entry in entries}, {"general"})
        by_mode = {entry["mode"]: entry for entry in entries}
        self.assertEqual(len(by_mode["일반전"]["changes"]), 1)
        self.assertEqual(len(by_mode["스타디움"]["changes"]), 1)
        self.assertIn("연습장", by_mode["일반전"]["changes"][0]["text"])
        self.assertNotIn("스타디움", by_mode["일반전"]["changes"][0]["text"])
        self.assertIn("스타디움 상점", by_mode["스타디움"]["changes"][0]["text"])
        self.assertNotIn("연습장", by_mode["스타디움"]["changes"][0]["text"])

    def test_explicit_combat_metrics_and_reduction_amounts(self):
        cases = [
            ("연료 재생률이 15에서 22.5로 증가했습니다.", "buff"),
            ("배치 거리가 30미터에서 25미터로 감소했습니다.", "nerf"),
            ("투사체 크기가 0.17에서 0.07로 감소했습니다.", "nerf"),
            ("폭발 지연이 1초에서 0.8초로 감소했습니다.", "buff"),
            ("강화된 펀치의 방사형 피해 사거리 증가가 75%에서 40%로 감소했습니다.", "nerf"),
            ("최대 분산도의 범위가 1에서 1.5로 증가했습니다.", "nerf"),
            ("최대 분산도에 도달하기까지의 탄환 수가 0발에서 30발로 증가했습니다.", "buff"),
            ("하나의 기관포만을 발사할 때의 최대 분산도가 1.5에서 1로 복원되었습니다.", "buff"),
            ("재사용 대기시간 감소량이 20%에서 10%로 감소했습니다.", "nerf"),
            ("궁극기 충전 비용 감소가 50%에서 60%로 증가했습니다.", "buff"),
            ("대상당 재사용 대기시간 감소가 2초에서 2.5초로 증가했습니다.", "buff"),
            ("적응형 방벽 - 주요 특전: 지속 시간이 1.5초에서 1초로 감소했습니다.", "adjust"),
            ("팔라틴 팽: 가로 휘두르기 지속 시간이 0.25초에서 0.2초로 감소했습니다.", "buff"),
            ("팔라틴 팽: 연속 공격 지속 시간이 0.75초에서 0.9초로 증가했습니다.", "nerf"),
        ]
        for line, category in cases:
            with self.subTest(line=line):
                self.assertEqual(monitor.classify_change_line(line), category)

    def test_cosmetics_do_not_override_combat_direction_or_disappear(self):
        result = self.summarize([
            ("h4", "영웅 업데이트"), ("h5", "안란"),
            ("li", "적에게 보이는 시각 효과가 감소했습니다."),
            ("h6", "주작 부활"), ("li", "시전 시간이 3초에서 2.5초로 감소했습니다."),
        ])
        self.assertEqual(result[0]["category"], "buff")
        self.assertEqual(len(result[0]["changes"]), 2)
        self.assertEqual(monitor.classify_change_line(result[0]["changes"][0]), "neutral")
        self.assertEqual(monitor.classify_change_line("강화 사격: 시각 효과가 변경되었습니다."), "neutral")

    def test_real_july_patch_ignores_developer_prose_and_separates_stadium(self):
        raw = monitor.parse_nexon_article((Path(__file__).parent / "fixtures/nexon-july15.html").read_text(encoding="utf-8"), "https://overwatch.nexon.com/news/patchnotes/689/patch-2026-07-14")
        parsed = monitor.assign_patch_ids([raw])[0]
        entries = monitor.extract_balance_summary(parsed)
        result = {(r["mode"], r["hero"]): r for r in entries if r["category"] != "review"}
        for hero, category in {"둠피스트": "nerf", "정커퀸": "buff", "라마트라": "buff", "시그마": "adjust", "캐서디": "adjust", "프레야": "buff", "리퍼": "adjust", "벤처": "buff", "아나": "buff", "루시우": "buff", "키리코": "nerf", "시온": "adjust", "마우가": "adjust"}.items():
            with self.subTest(hero=hero):
                self.assertEqual(result[("일반전", hero)]["category"], category)
        self.assertEqual(monitor.classify_change_line(result[("스타디움", "정커퀸")]["changes"][0]), "nerf")
        self.assertEqual(result[("스타디움", "캐서디")]["category"], "buff")
        self.assertIn("고귀한 총알 - 파워:", result[("스타디움", "정커퀸")]["changes"][0])
        comments = [text for tag, text in raw["items"] if tag == "developer"]
        self.assertGreater(len(comments), 10)
        original_body = "\n".join(monitor.format_summary(parsed))
        for comment in comments:
            self.assertIn(comment, original_body)
            self.assertFalse(any(comment in change for entry in entries for change in entry["changes"]))
        self.assertEqual(raw["body_hash"], monitor.build_body_hash(raw["title"], [("p" if tag == "developer" else tag, text) for tag, text in raw["items"]]))

    def test_stadium_item_section_is_not_attached_to_previous_hero(self):
        fixture = Path(__file__).parent / "fixtures/nexon-july15.html"
        raw = monitor.parse_nexon_article(fixture.read_text(encoding="utf-8"),
                                         "https://overwatch.nexon.com/news/patchnotes/689/patch-2026-07-14")
        parsed = monitor.assign_patch_ids([raw])[0]
        self.assertIn(("section", "아이템 변경 사항"), raw["items"])
        zenyatta = [entry for entry in monitor.extract_balance_summary(parsed)
                    if entry["mode"] == "스타디움" and entry["hero"] == "젠야타"]
        self.assertEqual(len(zenyatta), 1)
        self.assertEqual(zenyatta[0]["category"], "nerf")
        self.assertEqual(zenyatta[0]["changes"], [
            "깨달음 - 파워: 치유량이 준 피해의 40%에서 30%로 감소했습니다.",
            "내면의 평화 - 파워: 치유량 감소가 75%에서 80%로 변경되었습니다.",
        ])
        original_body = "\n".join(monitor.format_summary(parsed))
        self.assertIn("아이템 변경 사항", original_body)
        self.assertIn("가젯 재사용 대기시간 감소 효과가 25%에서 35%로 증가했습니다.", original_body)

    def test_real_september_patch_has_buffs_nerfs_and_mixed_changes(self):
        raw = monitor.parse_nexon_article((Path(__file__).parent / "fixtures/nexon-sept9.html").read_text(encoding="utf-8"), "https://overwatch.nexon.com/news/patchnotes/820/patch-2026-09-08")
        parsed = monitor.assign_patch_ids([raw])[0]
        entries, _ = monitor.prepare_card_data(parsed)
        core = {e["hero"]: e for e in entries if e["mode"] == "일반전" and e["category"] != "review"}
        expected = {"D.Va": "buff", "도미나": "buff", "안란": "buff", "바티스트": "buff",
                    "레킹볼": "adjust", "자리야": "nerf", "프레야": "adjust", "시메트라": "nerf", "키리코": "nerf", "젠야타": "nerf",
                    "정크랫": "adjust", "시에라": "adjust", "토르비욘": "adjust", "벤데타": "adjust", "브리기테": "adjust", "마우가": "adjust", "제트팩 캣": "nerf"}
        for hero, category in expected.items():
            with self.subTest(hero=hero):
                self.assertEqual(core[hero]["category"], category)
        self.assertEqual({line["category"] for line in core["정크랫"]["changes"]}, {"buff", "adjust"})
        self.assertTrue(any("복원" in line or "1.5 → 1" in line for line in (c["text"] for c in core["마우가"]["changes"])))
        review = [entry for entry in entries if entry["mode"] == "일반전" and
                  entry["hero"] == "제트팩 캣" and entry["category"] == "review"]
        self.assertEqual(len(review), 1)
        self.assertEqual([change["text"] for change in review[0]["changes"]], [
            "생명줄: 운반 중인 대상이 기절 및 이동 봉인 효과를 받으면 생명줄이 해제됩니다.",
            "생명줄: 아군이 사망 구역 위에 있을 경우 자동으로 생명줄에 연결됩니다.",
        ])


if __name__ == "__main__":
    unittest.main()
