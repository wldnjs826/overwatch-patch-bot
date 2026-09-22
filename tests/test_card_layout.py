from pathlib import Path
import tempfile
import unittest

from PIL import Image
import monitor
import summary_cards as cards
from summary_text import compact_change


def entry(changes, hero="정크랫", category="adjust", role="공격", mode="일반전"):
    return {"hero": hero, "role": role, "category": category, "changes": changes, "mode": mode}


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
        self.assertEqual([page["number"] for page in pages], list(range(1, len(pages) + 1)))
        self.assertEqual({page["count"] for page in pages}, {len(pages)})
        fonts = cards._fonts(monitor._find_font_path)
        for page in pages:
            self.assertLessEqual(page["height"], cards.MAX_HEIGHT)
            for row in page["rows"]:
                self.assertLessEqual(row["top"] + row["height"], page["height"] - cards.FOOTER)
                bottom = row["body_top"]
                for line in row["lines"]:
                    self.assertLessEqual(fonts["body"].getlength(line["text"]), cards.TEXT_WIDTH)
                    bottom += line["gap_before"] + cards.LINE_HEIGHT
                self.assertLessEqual(bottom, row["top"] + row["height"] - cards.PAD)

    def test_long_single_change_preserves_all_text_across_pages(self):
        text = "적에게 보이는 효과만 변경되며 아군에게 보이는 효과와 피해량은 변경되지 않습니다. " * 80
        pages = cards.plan_cards([entry([self.change(text, "adjust")])], [], monitor._find_font_path)
        rendered = "".join(line["text"] for p in pages for row in p["rows"] for line in row["lines"])
        self.assertEqual("".join(rendered.split()), "".join(text.strip().removesuffix(".").split()))
        self.assertGreater(len(pages), 1)

    def test_two_line_change_moves_whole_to_next_page_at_boundary(self):
        changes = [self.change(f"항목 {index}: 생명력 175 → 200") for index in range(13)]
        text = "공격력 감소율 최소: 적중한 적에게만 적용 적중한 적에게만 적용 30% → 20%"
        final_change = self.change(text, "nerf")
        wrapped = cards.wrap_styled(final_change["text"], final_change["highlights"],
                                    cards._fonts(monitor._find_font_path)["body"], cards.TEXT_WIDTH)
        self.assertEqual(len(wrapped), 2)
        pages = cards.plan_cards([entry([*changes, final_change])], [], monitor._find_font_path)
        self.assertEqual(len(pages), 2)
        locations = [(page_index, line) for page_index, page in enumerate(pages)
                     for row in page["rows"] for line in row["lines"]
                     if line["change_index"] == 13]
        self.assertEqual([page_index for page_index, _ in locations], [1, 1])
        self.assertEqual([line["first"] for _, line in locations], [True, False])
        self.assertEqual("".join(line["text"] for _, line in locations).replace(" ", ""),
                         final_change["text"].replace(" ", ""))
        self.assertTrue(pages[1]["rows"][0]["continued"])
        self.assertTrue(all(page["rows"] and page["height"] <= cards.MAX_HEIGHT for page in pages))

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
        self.assertEqual([page["mode"] for page in pages], ["일반전", "스타디움"])
        self.assertEqual([row["mode"] for row in rows], ["일반전", "스타디움"])

    def test_all_eighteen_groups_follow_mode_type_role_order(self):
        expected = [(mode, category, role)
                    for mode in ("일반전", "스타디움")
                    for category in ("buff", "nerf", "adjust")
                    for role in ("돌격", "공격", "지원")]
        entries = [entry([self.change("생명력 175 → 200", category)],
                         hero=f"영웅 {index}", mode=mode, category=category, role=role)
                   for index, (mode, category, role) in enumerate(reversed(expected))]
        pages = cards.plan_cards(entries, [], monitor._find_font_path)
        self.assertEqual([(page["mode"], page["category"], page["role"]) for page in pages], expected)
        for page in pages:
            self.assertTrue(page["rows"])
            self.assertEqual((page["number"], page["count"]), (1, 1))
            for row in page["rows"]:
                self.assertEqual((row["mode"], row["category"], row["role"]),
                                 (page["mode"], page["category"], page["role"]))

    def test_multiple_pages_stay_together_and_reset_number_for_new_group(self):
        long_changes = [self.change(f"항목 {index}: 재사용 대기시간 12초 → 10초") for index in range(35)]
        entries = [entry([self.change("생명력 175 → 200")], role="지원", category="buff"),
                   entry(long_changes, role="공격", category="buff"),
                   entry([self.change("생명력 175 → 200")], role="돌격", category="buff")]
        pages = cards.plan_cards(entries, [], monitor._find_font_path)
        roles = [page["role"] for page in pages]
        self.assertEqual(roles[0], "돌격")
        self.assertEqual(roles[-1], "지원")
        self.assertGreater(len(roles[1:-1]), 1)
        self.assertEqual(set(roles[1:-1]), {"공격"})
        self.assertEqual([page["number"] for page in pages[1:-1]], list(range(1, len(pages) - 1)))
        self.assertEqual({page["count"] for page in pages[1:-1]}, {len(pages) - 2})
        self.assertEqual((pages[-1]["number"], pages[-1]["count"]), (1, 1))

    def test_review_appendix_follows_classified_changes_in_both_modes(self):
        unknown = "특수 대상에게만 새 효과가 적용됩니다. 원문 조건 2회, 1.5초를 유지합니다."
        entries = [entry([{"text": unknown, "category": "review", "highlights": []}], category="review"),
                   entry([self.change("공격력 30 → 28", "nerf")], mode="스타디움", category="nerf"),
                   entry([self.change("생명력 175 → 200")], category="buff")]
        pages = cards.plan_cards(entries, [], monitor._find_font_path)
        self.assertEqual([(page["mode"], page["category"]) for page in pages],
                         [("일반전", "buff"), ("스타디움", "nerf"), ("일반전", "review")])
        review = pages[-1]
        rendered = "".join(line["text"] for row in review["rows"] for line in row["lines"])
        self.assertEqual("".join(rendered.split()), "".join(unknown.split()))
        self.assertFalse(any(marked for row in review["rows"] for line in row["lines"]
                             for _, marked in line["runs"]))

    def test_mobile_fonts_and_spacing_remain_large_for_long_cards(self):
        self.assertGreaterEqual(cards.FONT_SIZES["body"], 36)
        self.assertGreaterEqual(cards.FONT_SIZES["hero"], 38)
        self.assertGreaterEqual(cards.FONT_SIZES["role"], 40)
        self.assertGreaterEqual(cards.FONT_SIZES["title"], 64)
        self.assertGreaterEqual(cards.LINE_HEIGHT, 52)
        self.assertGreaterEqual(cards.CHANGE_GAP, 12)
        self.assertGreaterEqual(cards.HERO_GAP, 22)
        pages = cards.plan_cards([entry([self.change(f"조건 {index}: 생명력 175 → 200")
                                        for index in range(40)])], [], monitor._find_font_path)
        self.assertGreater(len(pages), 1)
        self.assertEqual(cards._fonts(monitor._find_font_path)["body"].size, 36)

    def test_rendered_filenames_are_unique_and_stable_across_groups(self):
        entries = [entry([self.change("생명력 175 → 200")], category="buff", mode=mode, role=role)
                   for mode in ("일반전", "스타디움") for role in ("돌격", "공격", "지원")]
        arguments = {"patch_id": "2026-09-18#01", "title": "테스트", "date_key": "2026-09-18",
                     "entries": entries, "general_changes": [], "font_path": monitor._find_font_path}
        with tempfile.TemporaryDirectory() as directory:
            paths = cards.render_cards(**arguments, output_dir=Path(directory))
            rerendered = cards.render_cards(**arguments, output_dir=Path(directory))
            self.assertEqual(paths, rerendered)
            self.assertEqual(len({path.name for path in paths}), 6)
            self.assertTrue(all(path.is_file() for path in paths))

    def test_missing_groups_do_not_create_empty_cards(self):
        self.assertEqual(cards.plan_cards([], [], monitor._find_font_path), [])
        self.assertEqual(cards.plan_cards([entry([])], [], monitor._find_font_path), [])
        pages = cards.plan_cards([entry([self.change("공격력 30 → 28", "nerf")],
                                       category="nerf", role="지원", mode="스타디움")], [], monitor._find_font_path)
        self.assertEqual(len(pages), 1)
        self.assertEqual((pages[0]["mode"], pages[0]["category"], pages[0]["role"]),
                         ("스타디움", "nerf", "지원"))


if __name__ == "__main__":
    unittest.main()
