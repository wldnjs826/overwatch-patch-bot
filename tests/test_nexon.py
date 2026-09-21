import unittest
from pathlib import Path
from unittest.mock import patch

import monitor


FIXTURES = Path(__file__).parent / "fixtures"


class NexonParsingTests(unittest.TestCase):
    def test_nuxt_cards_resolve_only_patch_detail_routes(self):
        html = (FIXTURES / "nexon-list.html").read_text(encoding="utf-8")
        self.assertEqual(monitor.extract_nexon_article_links(html), [
            "https://overwatch.nexon.com/news/patchnotes/830/patch-2026-09-16",
            "https://overwatch.nexon.com/news/patchnotes/823/patch-2026-09-10",
        ])
        with patch.object(monitor, "NEXON_MAX_ARTICLES", 1):
            self.assertEqual(len(monitor.extract_nexon_article_links(html)), 1)

    def test_legacy_anchors_and_nuxt_deduplicate_by_article_number(self):
        html = '<a href="/news/patchnotes/830">latest</a>'
        html += '<a href="https://example.com/news/patchnotes/1">external</a>'
        html += (FIXTURES / "nexon-list.html").read_text(encoding="utf-8")
        links = monitor.extract_nexon_article_links(html)
        self.assertEqual(len(links), 2)
        self.assertEqual(links[0], "https://overwatch.nexon.com/news/patchnotes/830")

    def test_invalid_payload_keeps_legacy_link_fallback(self):
        for payload in ("{invalid", "{}", '[{"newsNo":999,"categoryId":-1}]'):
            html = '<a href="/news/patchnotes/823?tracking=1">patch</a>'
            html += f'<script id="__NUXT_DATA__">{payload}</script>'
            self.assertEqual(monitor.extract_nexon_article_links(html), [
                "https://overwatch.nexon.com/news/patchnotes/823",
            ])

    def test_detail_title_body_images_and_nested_lists_are_scoped(self):
        html = (FIXTURES / "nexon-article.html").read_text(encoding="utf-8")
        result = monitor.parse_nexon_article(html, monitor.NEXON_LIST_URL + "/830")
        self.assertIsNotNone(result)
        self.assertEqual(result["date_key"], "2026-09-18")
        self.assertEqual(result["title"], "오버워치 패치 노트 – 2026년 9월 18일")
        self.assertEqual(result["items"], [
            ("h4", "영웅 업데이트"),
            ("h5", "D.Mon"),
            ("li", "방어력이 325에서 275로 감소했습니다. (5대5)"),
            ("h6", "추진기"),
            ("li", "기술 조정"),
            ("li", "재사용 대기시간이 10에서 12초로 증가했습니다."),
        ])
        self.assertEqual(result["images"], ["https://overwatch.nexon.com/images/hero.png"])
        self.assertTrue(monitor.check_korean_patch(result["items"]).is_korean)

    def test_missing_article_body_is_not_replaced_with_summary_or_related_news(self):
        html = '<div class="news-detail"><div class="news-head">'
        html += '<div class="title">오버워치 패치 노트 - 2026년 9월 18일</div></div>'
        html += '<p>관련 기사의 내용만 있습니다.</p></div>'
        self.assertIsNone(monitor.parse_nexon_article(html, monitor.NEXON_LIST_URL))
        list_html = (FIXTURES / "nexon-list.html").read_text(encoding="utf-8")
        self.assertIsNone(monitor.parse_nexon_article(list_html, monitor.NEXON_LIST_URL))

    def test_legacy_article_heading_still_parses(self):
        html = '<article><h1>오버워치 패치 노트 - 2026년 9월 18일</h1>'
        html += '<ul><li>영웅 생명력이 증가했습니다.</li></ul></article>'
        result = monitor.parse_nexon_article(html, monitor.NEXON_LIST_URL + "/830")
        self.assertEqual(result["items"], [("li", "영웅 생명력이 증가했습니다.")])


if __name__ == "__main__":
    unittest.main()
