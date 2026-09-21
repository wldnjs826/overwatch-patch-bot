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


if __name__ == "__main__":
    unittest.main()
