from pathlib import Path
import tempfile
import unittest

from PIL import Image
import monitor
import summary_cards as cards
from summary_text import compact_change


def entry(changes, hero="정크랫", category="adjust", role="공격"):
    return {"hero": hero, "role": role, "category": category, "changes": changes}


class CardLayoutTests(unittest.TestCase):
    def change(self, text, category="buff"):
        return {**compact_change(text), "category": category}

    def test_short_card_has_adaptive_height_and_keeps_labels(self):
        entries = [entry([self.change("충격 지뢰 재사용 대기시간 8초 → 7초")])]
        pages = cards.plan_cards(entries, [], monitor._find_font_path)
        self.assertEqual(len(pages), 1)
        self.assertLess(pages[0]["height"], 600)
        self.assertEqual(pages[0]["rows"][0]["hero"], "정크랫")
        self.assertEqual(pages[0]["rows"][0]["role"], "공격")

    def test_long_hero_continues_without_losing_changes(self):
        changes = [self.change(f"항목 {n}: 적중 시 재사용 대기시간이 8초에서 7초로 감소했습니다. (6대6)") for n in range(45)]
        pages = cards.plan_cards([entry(changes)], [], monitor._find_font_path)
        self.assertGreater(len(pages), 1)
        first_lines = [line for p in pages for row in p["rows"] for line in row["lines"] if line["first"]]
        self.assertEqual([line["change_index"] for line in first_lines], list(range(45)))
        self.assertTrue(pages[1]["rows"][0]["continued"])
        for page in pages:
            self.assertLessEqual(page["height"], cards.MAX_HEIGHT)
            for row in page["rows"]:
                self.assertLessEqual(row["top"] + row["height"], page["height"] - cards.FOOTER)

    def test_long_single_change_preserves_all_text_across_pages(self):
        text = "적에게 보이는 효과만 변경되며 아군에게 보이는 효과와 피해량은 변경되지 않습니다. " * 80
        pages = cards.plan_cards([entry([self.change(text, "adjust")])], [], monitor._find_font_path)
        rendered = "".join(line["text"] for p in pages for row in p["rows"] for line in row["lines"])
        self.assertEqual("".join(rendered.split()), "".join(text.strip().removesuffix(".").split()))
        self.assertGreater(len(pages), 1)

    def test_mixed_changes_retain_individual_colors_and_spans(self):
        changes = [self.change("재사용 대기시간 8초 → 7초", "buff"), self.change("추가 속도 125% → 100%", "nerf")]
        page = cards.plan_cards([entry(changes)], [], monitor._find_font_path)[0]
        self.assertEqual(page["category"], "adjust")
        lines = page["rows"][0]["lines"]
        self.assertEqual({line["category"] for line in lines}, {"buff", "nerf"})
        emphasized = [text for line in lines for text, marked in line["runs"] if marked]
        self.assertEqual(emphasized, ["7초", "100%"])

    def test_png_dimensions_and_font_rendering(self):
        entries = [entry([self.change("방어력이 325에서 275로 감소했습니다. (5대5)", "nerf")], hero="D.Mon", category="nerf", role="영웅")]
        with tempfile.TemporaryDirectory() as directory:
            paths = cards.render_cards(patch_id="2026-09-18#01", title="테스트", date_key="2026-09-18", entries=entries, general_changes=[], output_dir=Path(directory), font_path=monitor._find_font_path)
            self.assertEqual(len(paths), 1)
            with Image.open(paths[0]) as image:
                self.assertEqual(image.width, cards.WIDTH)
                self.assertLessEqual(image.height, cards.MAX_HEIGHT)
                self.assertEqual(image.format, "PNG")

    def test_stadium_mode_is_visible_and_not_merged_with_core_hero(self):
        core = entry([self.change("재사용 대기시간 12초 → 10초")], hero="정커퀸", role="돌격", category="buff")
        stadium = {**core, "mode": "스타디움"}
        pages = cards.plan_cards([core, stadium], [], monitor._find_font_path)
        rows = [row for page in pages for row in page["rows"]]
        self.assertEqual(len(rows), 2)
        self.assertNotIn("스타디움", "".join(line["text"] for line in rows[0]["badge"]))
        self.assertIn("스타디움", "".join(line["text"] for line in rows[1]["badge"]))


if __name__ == "__main__":
    unittest.main()
