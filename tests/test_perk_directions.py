from pathlib import Path
import unittest

import monitor
import summary_cards


class PerkDirectionTests(unittest.TestCase):
    def summarize(self, changes):
        title = "특전 분류 검증"
        raw = {"title": title, "date_key": "2026-11-04", "images": [],
               "items": [("h4", "영웅 업데이트"), ("h4", "돌격"), ("h5", "검증 영웅"), *changes],
               "body_hash": "test", "source_url": "https://example.invalid", "source_name": "nexon"}
        return monitor.prepare_card_data(monitor.assign_patch_ids([raw])[0])[0]

    def test_user_reported_dmon_and_winston_are_both_nerfs(self):
        fixture = Path(__file__).parent / "fixtures/nexon-nov4-tank-nerfs.html"
        raw = monitor.parse_nexon_article(fixture.read_text(encoding="utf-8"),
                                         "https://overwatch.nexon.com/news/patchnotes/858/patch-2026-11-03")
        current = monitor.assign_patch_ids([raw])[0]
        entries, general = monitor.prepare_card_data(current)
        self.assertEqual([(e["hero"], e["category"]) for e in entries],
                         [("D.Mon", "nerf"), ("윈스턴", "nerf")])
        self.assertEqual([len(e["changes"]) for e in entries], [3, 1])
        self.assertEqual({c["category"] for e in entries for c in e["changes"]}, {"nerf"})
        pages = summary_cards.plan_cards(entries, general, monitor._find_font_path)
        self.assertEqual([(p["mode"], p["category"], p["role"]) for p in pages],
                         [("일반전", "nerf", "돌격")])
        self.assertEqual({row["hero"] for row in pages[0]["rows"]}, {"D.Mon", "윈스턴"})

    def test_major_and_minor_perks_follow_benefit_instead_of_label(self):
        for label in ("주요 특전", "보조 특전"):
            for text, expected in [
                ("생명력이 175에서 200으로 증가했습니다.", "buff"),
                ("공격력이 30에서 28로 감소했습니다.", "nerf"),
                ("재사용 대기시간이 12초에서 10초로 감소했습니다.", "buff"),
                ("재사용 대기시간이 8초에서 10초로 증가했습니다.", "nerf"),
            ]:
                with self.subTest(label=label, text=text):
                    result = self.summarize([("h6", "효과 - " + label), ("li", text)])
                    self.assertEqual(result[0]["category"], expected)
                    self.assertEqual(result[0]["changes"][0]["category"], expected)

    def test_adjustment_requires_opposing_known_effects(self):
        result = self.summarize([
            ("h6", "효과 - 주요 특전"), ("li", "공격력이 30에서 35로 증가했습니다."),
            ("h6", "기본 기술"), ("li", "재사용 대기시간이 8초에서 10초로 증가했습니다."),
        ])
        self.assertEqual(result[0]["category"], "adjust")
        self.assertEqual([c["category"] for c in result[0]["changes"]], ["buff", "nerf"])

    def test_unknown_and_negated_perks_do_not_force_known_nerfs_to_adjustment(self):
        result = self.summarize([
            ("h6", "효과 - 주요 특전"), ("li", "새로운 방식으로 작동합니다."),
            ("li", "공격력이 30에서 35로 증가하지 않습니다."),
            ("h6", "기본 기술"), ("li", "공격력이 30에서 28로 감소했습니다."),
        ])
        self.assertEqual([e["category"] for e in result], ["nerf", "review"])
        self.assertEqual(len(result[1]["changes"]), 2)

    def test_cosmetic_perk_is_neutral_and_does_not_override_nerf(self):
        result = self.summarize([
            ("h6", "효과 - 보조 특전"), ("li", "시각 효과가 변경되었습니다."),
            ("h6", "기본 기술"), ("li", "공격력이 30에서 28로 감소했습니다."),
        ])
        self.assertEqual(result[0]["category"], "nerf")
        self.assertEqual([c["category"] for c in result[0]["changes"]], ["neutral", "nerf"])


if __name__ == "__main__":
    unittest.main()
