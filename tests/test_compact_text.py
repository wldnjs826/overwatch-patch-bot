import unittest

from summary_text import compact_change


class CompactTextTests(unittest.TestCase):
    def test_reference_examples_and_conditions(self):
        cases = [
            ("메카의 기본 생명력이 175에서 200으로 증가했습니다.", "메카 기본 생명력 175 → 200"),
            ("궁극기 비용이 6% 감소했습니다.", "궁극기 비용 -6%"),
            ("불사 장치의 재사용 대기시간이 22초에서 20초로 감소했습니다.", "불사 장치 재사용 대기시간 22초 → 20초"),
            ("방어력이 325에서 275로 감소했습니다. (5대5)", "방어력 325 → 275 (5대5)"),
            ("집중 융합 - 주요 특전: 탄환당 피해가 45에서 36으로 감소했습니다.", "[주요 특전] 집중 융합 탄환당 피해 45 → 36"),
            ("추진기: 연료 소모 속도가 25에서 30으로 증가했습니다.", "추진기 연료 소모 속도 25 → 30"),
            ("시전 시간이 3에서 2.5초로 감소했습니다.", "시전 시간 3초 → 2.5초"),
            ("처치 불가 생명력 한계치가 20%에서 25%로 증가했습니다.", "처치 불가 생명력 한계치 20% → 25%"),
            ("적중 시 적에게 보이는 시각 효과가 감소했습니다.", "적중 시 적에게 보이는 시각 효과 감소"),
            ("확률이 5%p 증가했습니다.", "확률이 +5%p"),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(compact_change(source)["text"], expected)

    def test_highlights_only_changed_values(self):
        result = compact_change("시전 시간이 0.3초에서 0.15초로 감소했습니다.")
        self.assertEqual([result["text"][a:b] for a, b in result["highlights"]], ["0.15초"])

    def test_multiple_changes_and_mode_survive(self):
        result = compact_change("공격력이 10에서 12로 증가하고 재사용 대기시간이 8초에서 9초로 증가했습니다. (6대6)")
        self.assertIn("10 → 12", result["text"])
        self.assertIn("8초 → 9초", result["text"])
        self.assertIn("(6대6)", result["text"])

    def test_unknown_and_negated_changes_keep_meaning(self):
        cases = ["피해가 감소하지 않습니다", "적 방벽은 통과하지 않지만 아군 방벽은 통과합니다", "피해가 20에서 10으로 감소하지 않습니다"]
        for source in cases:
            result = compact_change(source)["text"]
            self.assertIn("않", result)
            self.assertNotIn("→", result)

    def test_no_invented_endpoint_for_delta(self):
        result = compact_change("궁극기 비용이 6% 감소했습니다.")
        self.assertEqual(result, {"text": "궁극기 비용 -6%", "highlights": [[7, 10]]})

    def test_compound_units_and_large_deltas_are_fully_highlighted(self):
        cases = [("투사체 속도가 10미터/초에서 12미터/초로 증가했습니다.", "12미터/초"),
                 ("생명력이 1,000 증가했습니다.", "+1,000")]
        for text, expected in cases:
            result = compact_change(text)
            self.assertEqual([result["text"][a:b] for a, b in result["highlights"]], [expected])

    def test_unknown_suffix_and_signed_input_are_not_partially_rewritten(self):
        for source in ["공격력이 10에서 12로 증가했습니다만 조건은 동일합니다",
                       "피해가 +10% 증가했습니다", "피해가 −10% 감소했습니다", "피해가 -10% 감소했습니다"]:
            result = compact_change(source)["text"]
            self.assertNotIn("→", result)
            self.assertNotIn("++", result)
            self.assertNotIn("−-", result)
        self.assertIn("증가했습니다만", compact_change("공격력이 10에서 12로 증가했습니다만 조건은 동일합니다")["text"])


if __name__ == "__main__":
    unittest.main()
