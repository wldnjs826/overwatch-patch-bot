from pathlib import Path
import unittest

import monitor


class SummaryTests(unittest.TestCase):
    def summarize(self, items):
        patch = monitor.assign_patch_ids([{
            "title": "오버워치 패치 노트 - 2026년 9월 18일", "date_key": "2026-09-18",
            "items": items, "images": [], "body_hash": "test",
            "source_url": "https://example.com", "source_name": "nexon",
        }])[0]
        return monitor.extract_balance_summary(patch)

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

    def test_fuel_cost_increase_is_nerf_and_perk_label_survives(self):
        result = self.summarize([
            ("h4", "영웅 업데이트"), ("h5", "D.Mon"),
            ("p", "집중 융합 - 주요 특전"), ("li", "탄환당 피해가 45에서 36으로 감소했습니다."),
            ("h6", "추진기"), ("li", "연료 소모 속도가 25에서 30으로 증가했습니다."),
        ])
        self.assertEqual(result[0]["category"], "nerf")
        self.assertIn("집중 융합 - 주요 특전:", result[0]["changes"][0])
        self.assertIn("추진기:", result[0]["changes"][1])

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
        self.assertEqual([monitor.classify_change_line(line) for line in result[0]["changes"]], ["buff", "nerf"])

    def test_ambiguous_and_negated_changes_stay_neutral(self):
        for text in ["공격력이 10에서 12로 증가하고 재사용 대기시간이 8초에서 9초로 증가했습니다.",
                     "공격력이 10% 증가하고 재사용 대기시간이 2초 증가했습니다.",
                     "피해가 20에서 10으로 감소하지 않습니다."]:
            with self.subTest(text=text):
                self.assertEqual(monitor.classify_change_line(text), "adjust")

    def test_comma_separated_values_keep_numeric_direction(self):
        self.assertEqual(monitor.classify_change_line("생명력이 1,000에서 900으로 감소했습니다."), "nerf")
        self.assertEqual(monitor.classify_change_line("방어력이 900에서 1,000으로 증가했습니다."), "buff")

    def test_conflicting_metrics_names_negation_and_units_stay_neutral(self):
        for text in ["재사용 대기시간 동안 이동 속도가 10%에서 20%로 증가했습니다.",
                     "공격력이 상향되지 않았습니다.",
                     "시전 시간이 1초에서 500밀리초로 감소했습니다."]:
            with self.subTest(text=text):
                self.assertEqual(monitor.classify_change_line(text), "adjust")
        self.assertEqual(monitor.classify_change_line("소용돌이 질주: 회복 시간이 0.5초에서 0.75초로 증가했습니다."), "nerf")

    def test_explicit_combat_metrics_and_reduction_amounts(self):
        cases = [
            ("연료 재생률이 15에서 22.5로 증가했습니다.", "buff"),
            ("배치 거리가 30미터에서 25미터로 감소했습니다.", "nerf"),
            ("투사체 크기가 0.17에서 0.07로 감소했습니다.", "nerf"),
            ("폭발 지연이 1초에서 0.8초로 감소했습니다.", "buff"),
            ("강화된 펀치의 방사형 피해 사거리 증가가 75%에서 40%로 감소했습니다.", "nerf"),
            ("최대 분산도의 범위가 1에서 1.5로 증가했습니다.", "nerf"),
            ("재사용 대기시간 감소량이 20%에서 10%로 감소했습니다.", "nerf"),
            ("궁극기 충전 비용 감소가 50%에서 60%로 증가했습니다.", "buff"),
            ("대상당 재사용 대기시간 감소가 2초에서 2.5초로 증가했습니다.", "buff"),
            ("적응형 방벽 - 주요 특전: 지속 시간이 1.5초에서 1초로 감소했습니다.", "nerf"),
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
        result = {(r["mode"], r["hero"]): r for r in monitor.extract_balance_summary(parsed)}
        for hero, category in {"둠피스트": "nerf", "정커퀸": "buff", "라마트라": "buff", "시그마": "nerf", "캐서디": "nerf", "프레야": "buff", "리퍼": "buff", "벤처": "buff", "아나": "buff", "루시우": "buff", "키리코": "nerf", "시온": "adjust"}.items():
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
            self.assertFalse(any(comment in change for entry in result.values() for change in entry["changes"]))
        self.assertEqual(raw["body_hash"], monitor.build_body_hash(raw["title"], [("p" if tag == "developer" else tag, text) for tag, text in raw["items"]]))

    def test_real_september_patch_has_buffs_nerfs_and_mixed_changes(self):
        raw = monitor.parse_nexon_article((Path(__file__).parent / "fixtures/nexon-sept9.html").read_text(encoding="utf-8"), "https://overwatch.nexon.com/news/patchnotes/820/patch-2026-09-08")
        parsed = monitor.assign_patch_ids([raw])[0]
        entries, _ = monitor.prepare_card_data(parsed)
        core = {e["hero"]: e for e in entries if e["mode"] == "일반전"}
        expected = {"D.Va": "buff", "도미나": "buff", "안란": "buff", "바티스트": "buff",
                    "레킹볼": "nerf", "자리야": "nerf", "프레야": "nerf", "시메트라": "nerf", "키리코": "nerf", "젠야타": "nerf",
                    "정크랫": "adjust", "시에라": "adjust", "토르비욘": "adjust", "벤데타": "adjust", "브리기테": "adjust"}
        for hero, category in expected.items():
            with self.subTest(hero=hero):
                self.assertEqual(core[hero]["category"], category)
        self.assertEqual({line["category"] for line in core["정크랫"]["changes"]}, {"buff", "nerf"})


if __name__ == "__main__":
    unittest.main()
