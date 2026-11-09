import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import monitor


FIXTURES = Path(__file__).parent / "fixtures"
LATEST_NEXON_URL = f"{monitor.NEXON_LIST_URL}/862/patch-2026-11-05"
LATEST_NEXON_HTML = """
<div class="news-detail">
    <div class="news-head"><div class="title">오버워치 패치 노트 – 2026년 11월 6일</div></div>
    <div class="news-body">
        <h4>핫픽스 업데이트</h4>
        <p>핫픽스 업데이트입니다. 11월 4일 패치의 리플레이 코드는 계속 이용할 수 있습니다.</p>
        <h4>영웅 업데이트</h4>
        <h5>레킹볼</h5>
        <div class="PatchNotesAbilityUpdate-name">갈고리 고정</div>
        <ul><li>갈고리 고정을 취소하는 동안 레킹볼의&nbsp;기본 속도 제한이 15% 증가했습니다.</li></ul>
    </div>
</div>
"""
# A featured item appears earlier in the Nuxt table than the newer patch.
NEWS_WITH_LATEST = """
<script id="__NUXT_DATA__">[{"newsNo":1,"categoryId":2,"slug":3},859,2,"older",
{"newsNo":5,"categoryId":2,"slug":6},862,"patch-2026-11-05",
{"newsNo":8,"categoryId":9,"slug":10},863,3,"event"]</script>
"""


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
        self.assertEqual(links[0], "https://overwatch.nexon.com/news/patchnotes/830/patch-2026-09-16")

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

    def test_merges_official_lists_and_keeps_newest_before_applying_limit(self):
        stale_list = '<a href="/news/patchnotes/859/older">이전 공지</a>'
        with patch.object(monitor, "NEXON_MAX_ARTICLES", 1):
            self.assertEqual(
                monitor.extract_nexon_article_links(stale_list, NEWS_WITH_LATEST),
                [LATEST_NEXON_URL],
            )

    def test_known_issues_in_patch_category_are_excluded(self):
        html = """
        <a href="/news/patchnotes/859">알려진 현상</a>
        <script id="__NUXT_DATA__">[{"newsNo":1,"categoryId":2,"title":3},
        859,2,"2026: 5시즌 알려진 현상 안내",{"newsNo":5,"categoryId":2,"title":6},
        858,"오버워치 패치노트 - 2026년 11월 4일"]</script>
        """
        self.assertEqual(monitor.extract_nexon_article_links(html),
                         [f"{monitor.NEXON_LIST_URL}/858"])

    def test_latest_from_alternate_listing_uses_verified_numeric_route(self):
        numeric_url = f"{monitor.NEXON_LIST_URL}/862"
        responses = {
            monitor.NEXON_LIST_URL: requests.Timeout("list timed out"),
            monitor.NEXON_NEWS_URL: NEWS_WITH_LATEST,
            LATEST_NEXON_URL: requests.HTTPError("slug unavailable"),
            numeric_url: LATEST_NEXON_HTML,
        }

        def fetch(url):
            result = responses[url]
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(monitor, "NEXON_MAX_ARTICLES", 1):
            with patch.object(monitor, "fetch_html", side_effect=fetch) as requests_mock:
                latest, = monitor.fetch_recent_patches()
        self.assertCountEqual([call.args[0] for call in requests_mock.call_args_list], responses)
        self.assertEqual(latest.source_url, numeric_url)
        self.assertEqual(latest.date_key, "2026-11-06")
        self.assertIn(("h6", "갈고리 고정"), latest.items)
        self.assertIn(("li", "갈고리 고정을 취소하는 동안 레킹볼의 기본 속도 제한이 15% 증가했습니다."),
                      latest.items)

    def test_unreadable_latest_does_not_substitute_older_patch(self):
        older_html = (FIXTURES / "nexon-article.html").read_text(encoding="utf-8")
        responses = {
            monitor.NEXON_LIST_URL: NEWS_WITH_LATEST,
            monitor.NEXON_NEWS_URL: "",
            LATEST_NEXON_URL: "<main>일시적으로 본문을 표시할 수 없습니다.</main>",
            f"{monitor.NEXON_LIST_URL}/862": "",
            f"{monitor.NEXON_LIST_URL}/859/older": older_html,
        }
        with patch.object(monitor, "fetch_html", side_effect=responses.__getitem__):
            with self.assertRaisesRegex(RuntimeError, "최신 넥슨 패치 본문"):
                monitor.fetch_recent_patches()

    def test_no_blizzard_fallback_when_both_nexon_listings_fail(self):
        with patch.object(monitor, "fetch_html", side_effect=requests.Timeout) as fetch:
            with self.assertRaisesRegex(RuntimeError, "넥슨 목록"):
                monitor.fetch_recent_patches()
        self.assertCountEqual(
            [call.args[0] for call in fetch.call_args_list],
            [monitor.NEXON_LIST_URL, monitor.NEXON_NEWS_URL],
        )


if __name__ == "__main__":
    unittest.main()
