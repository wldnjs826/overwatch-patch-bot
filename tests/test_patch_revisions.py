import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests
import monitor
from patch_revisions import changed_entries


def note(items):
    title = "오버워치 패치 노트 - 2026년 11월 4일"
    return monitor.assign_patch_ids([{
        "title": title, "date_key": "2026-11-04", "items": items, "images": [],
        "body_hash": monitor.build_body_hash(title, items),
        "source_url": "https://overwatch.nexon.com/news/patchnotes/858/patch-2026-11-03",
        "source_name": "nexon",
    }])[0]


def hero_lines(*changes, hero="겐지", ability="수리검", mode="영웅 업데이트", role="공격"):
    return [("h4", mode), ("h4", role), ("h5", hero), ("h6", ability),
            *[("li", line) for line in changes]]


def diff(old, new):
    return changed_entries(monitor.format_summary(old)[4:], monitor.format_summary(new)[4:],
                           classify=monitor.classify_change_line,
                           role_from_heading=monitor._role_from_heading, hero_roles={})


class SourceDiffTests(unittest.TestCase):
    def test_one_modified_metric_does_not_repeat_other_changes_or_heroes(self):
        old = note(hero_lines("공격력 30 → 28", "재사용 대기시간 12초 → 10초")
                   + hero_lines("생명력 175 → 200", hero="D.Va", role="돌격"))
        new = note(hero_lines("공격력 30 → 26", "재사용 대기시간 12초 → 10초")
                   + hero_lines("생명력 175 → 200", hero="D.Va", role="돌격"))
        entries = diff(old, new)
        self.assertEqual([(e["hero"], e["category"]) for e in entries], [("겐지", "nerf")])
        text = entries[0]["changes"][0]["text"]
        self.assertIn("[수정] 수리검: 공격력 30 → 26", text)
        self.assertIn("이전 표기: 수리검: 공격력 30 → 28", text)
        self.assertNotIn("재사용", text)

    def test_perk_label_correction_includes_affected_line_only(self):
        old = note(hero_lines("피해량 30 → 28", ability="음파 분열 - 주요 특전"))
        new = note(hero_lines("피해량 30 → 28", ability="음파 분열 - 보조 특전"))
        entries = diff(old, new)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["category"], "adjust")
        text = entries[0]["changes"][0]["text"]
        self.assertIn("음파 분열 - 보조 특전", text)
        self.assertIn("이전 표기: 음파 분열 - 주요 특전", text)

    def test_additions_deletions_and_unknowns_keep_original_conditions(self):
        old = note(hero_lines("최대 3회 적중 시에만 기존 효과가 적용됩니다."))
        new = note(hero_lines("전혀 다른 새 이동 방식으로 작동합니다. 방벽은 제외됩니다."))
        text = "\n".join(c["text"] for e in diff(old, new) for c in e["changes"])
        self.assertIn("[추가]", text)
        self.assertIn("[원문에서 삭제]", text)
        self.assertIn("최대 3회 적중 시에만", text)
        self.assertIn("방벽은 제외됩니다.", text)
        self.assertEqual({e["category"] for e in diff(old, new)}, {"review"})

    def test_reordering_and_whitespace_do_not_create_revision_cards(self):
        old = note(hero_lines("공격력 30 → 28", "재사용 대기시간 12초 → 10초"))
        new = note(hero_lines("재사용 대기시간  12초 → 10초", "공격력 30 → 28"))
        self.assertEqual(diff(old, new), [])

    def test_same_hero_in_normal_and_stadium_is_compared_independently(self):
        old = note(hero_lines("공격력 30 → 28") + hero_lines("공격력 30 → 28", mode="스타디움 업데이트"))
        new = note(hero_lines("공격력 30 → 28") + hero_lines("공격력 30 → 32", mode="스타디움 업데이트"))
        entries = diff(old, new)
        self.assertEqual([(e["mode"], e["category"]) for e in entries], [("스타디움", "buff")])

    def test_general_and_developer_text_changes_are_not_lost(self):
        old = note([("h4", "일반 업데이트"), ("p", "이벤트는 11월 10일까지 진행됩니다.")])
        new = note([("h4", "일반 업데이트"), ("p", "이벤트는 11월 11일까지 진행됩니다.")])
        entries = diff(old, new)
        self.assertEqual(entries[0]["role"], "일반")
        self.assertIn("11월 11일", entries[0]["changes"][0]["text"])


class RevisionDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(monitor, "STATE_FILE", self.directory / "state.json"))
        self.stack.enter_context(patch.object(monitor.time, "sleep"))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("Unexpected network")))
        self.post = self.stack.enter_context(patch.object(monitor.requests, "post", side_effect=self.upload))
        self.edit = self.stack.enter_context(patch.object(monitor.requests, "patch", return_value=self.response("original")))
        self.delete = self.stack.enter_context(patch.object(monitor.requests, "delete"))
        self.get = self.stack.enter_context(patch.object(monitor.requests, "get"))
        self.generated, self.posts = [], []
        self.generator = self.stack.enter_context(patch.object(monitor, "generate_summary_cards", side_effect=self.render))
        self.old = note(hero_lines("공격력 30 → 28", "재사용 대기시간 12초 → 10초"))
        self.new = note(hero_lines("공격력 30 → 26", "재사용 대기시간 12초 → 10초"))
        self.state = monitor.empty_state()
        self.record = monitor.make_record(self.old, "sent")
        self.record.update({"discord_message_ids": ["original"], "summary_message_ids": ["old-card"],
                            "summary_source_lines": monitor.format_summary(self.old)[4:],
                            "summary_body_hash": self.old.body_hash,
                            "summary_card_version": monitor.SUMMARY_CARD_VERSION,
                            "text_format_version": monitor.TEXT_FORMAT_VERSION})
        self.state["patches"][self.old.patch_id] = self.record
        self.webhook = "https://discord.invalid/api/webhooks/test/token"

    @staticmethod
    def response(message_id="", status=200, content=None):
        result = Mock(status_code=status, headers={})
        result.json.return_value = {"id": message_id, "content": content}
        if status >= 400:
            result.raise_for_status.side_effect = requests.HTTPError(response=result)
        return result

    def upload(self, _url, **kwargs):
        self.posts.append(kwargs)
        return self.response(f"new-{len(self.posts)}")

    def render(self, _note, directory, **kwargs):
        self.generated.append(kwargs)
        path = Path(directory) / "revision.png"
        path.write_bytes(b"mock image")
        return [path]

    def process(self, current=None):
        return monitor.process_patch(current or self.new, self.state, self.webhook)

    def test_revision_posts_only_changed_rows_and_preserves_original_card_ids(self):
        self.assertEqual(self.process(), "updated")
        self.delete.assert_not_called()
        self.assertEqual(self.edit.call_count, 1)  # Original full text only.
        self.assertEqual(self.record["summary_message_ids"], ["old-card"])
        self.assertEqual(len(self.posts), 1)
        self.assertTrue(self.generated[0]["revision"])
        entries = self.generated[0]["entries_override"]
        self.assertEqual(len(entries[0]["changes"]), 1)
        self.assertNotIn("재사용", str(entries))
        self.assertIn("수정 사항", json.loads(self.posts[0]["data"]["payload_json"])["content"])
        self.assertEqual(self.process(), "already_sent")
        self.assertEqual(len(self.posts), 1)

    def test_version_upgrade_and_legacy_baseline_are_silent(self):
        self.record.pop("summary_source_lines")
        self.record["summary_card_version"] -= 1
        self.assertEqual(self.process(self.old), "already_sent")
        self.assertEqual(self.record["summary_source_lines"], monitor.format_summary(self.old)[4:])
        self.post.assert_not_called()
        self.edit.assert_not_called()
        self.delete.assert_not_called()
        self.assertEqual(self.process(), "updated")
        self.assertEqual(len(self.posts), 1)

    def test_legacy_changed_source_is_recovered_before_original_is_edited(self):
        self.record.pop("summary_source_lines")
        messages = monitor.decorate_payloads(monitor.build_discord_payloads(self.old))
        self.assertEqual(len(messages), 1)
        self.get.return_value = self.response(content=messages[0]["content"])
        self.assertEqual(self.process(), "updated")
        self.get.assert_called_once()
        self.assertEqual(len(self.generated[0]["entries_override"][0]["changes"]), 1)
        self.delete.assert_not_called()

    def test_unavailable_legacy_baseline_never_falls_back_to_full_repost(self):
        self.record.pop("summary_source_lines")
        self.get.return_value = self.response(status=404)
        with self.assertRaises(requests.HTTPError):
            self.process()
        self.post.assert_not_called()
        self.edit.assert_not_called()
        self.delete.assert_not_called()
        self.assertEqual(self.record["body_hash"], self.old.body_hash)

    def test_failed_revision_resumes_without_editing_source_or_touching_old_cards(self):
        self.post.side_effect = requests.ConnectionError("card upload interrupted")
        with self.assertRaises(requests.ConnectionError):
            self.process()
        self.state = monitor.load_state()
        self.record = self.state["patches"][self.new.patch_id]
        self.assertTrue(self.record["pending_revision"]["text_done"])
        self.edit.reset_mock()
        self.post.side_effect = self.upload
        self.assertEqual(self.process(), "updated")
        self.edit.assert_not_called()
        self.delete.assert_not_called()
        self.assertNotIn("pending_revision", self.record)
        self.assertEqual(self.record["summary_message_ids"], ["old-card"])
        self.assertEqual(self.process(), "already_sent")
        self.assertEqual(len(self.posts), 1)

    def test_new_site_revision_does_not_discard_an_unfinished_revision(self):
        self.post.side_effect = requests.ConnectionError("card interrupted")
        with self.assertRaises(requests.ConnectionError):
            self.process()
        newest = note(hero_lines("공격력 30 → 25", "재사용 대기시간 12초 → 10초"))
        self.post.side_effect = self.upload
        self.assertEqual(self.process(newest), "updated")
        self.assertEqual(len(self.posts), 2)
        self.assertEqual([b["body_hash"] for b in self.record["revision_batches"]],
                         [self.new.body_hash, newest.body_hash])

    def test_acknowledged_revision_page_is_reused_after_next_page_fails(self):
        def two_pages(_note, directory, **kwargs):
            paths = [Path(directory) / f"revision-{i}.png" for i in range(2)]
            for path in paths:
                path.write_bytes(b"mock image")
            return paths
        self.generator.side_effect = two_pages
        self.post.side_effect = [self.response("first-delta"), requests.ConnectionError("second page failed")]
        with self.assertRaises(requests.ConnectionError):
            self.process()
        self.state = monitor.load_state()
        self.record = self.state["patches"][self.new.patch_id]
        self.assertEqual(self.record["pending_revision"]["message_ids"], ["first-delta"])
        self.edit.reset_mock()
        self.edit.return_value = self.response("first-delta")
        self.post.side_effect = self.upload
        self.assertEqual(self.process(), "updated")
        self.assertEqual(self.edit.call_count, 1)
        self.assertIn("/messages/first-delta", self.edit.call_args.args[0])
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.record["revision_batches"][0]["message_ids"], ["first-delta", "new-1"])
        self.assertEqual(self.record["summary_message_ids"], ["old-card"])
        self.delete.assert_not_called()

    def test_interrupted_source_edit_resumes_before_any_revision_upload(self):
        self.edit.side_effect = requests.ConnectionError("source edit interrupted")
        with self.assertRaises(requests.ConnectionError):
            self.process()
        self.assertFalse(self.record["pending_revision"]["text_done"])
        self.post.assert_not_called()
        self.edit.side_effect = None
        self.edit.return_value = self.response("original")
        self.assertEqual(self.process(), "updated")
        self.assertEqual(len(self.posts), 1)
        self.delete.assert_not_called()

    def test_deleted_source_replacement_can_resume_after_all_old_ids_are_removed(self):
        self.edit.return_value = self.response(status=404)
        self.delete.return_value = self.response(status=404)
        self.post.side_effect = requests.ConnectionError("source replacement interrupted")
        with self.assertRaises(requests.ConnectionError):
            self.process()
        self.state = monitor.load_state()
        self.record = self.state["patches"][self.new.patch_id]
        self.assertEqual(self.record["discord_message_ids"], [])
        self.assertFalse(self.record["pending_revision"]["text_done"])
        self.post.side_effect = self.upload
        self.assertEqual(self.process(), "updated")
        self.assertEqual(self.record["discord_message_ids"], ["new-1"])
        self.assertEqual(self.record["summary_message_ids"], ["old-card"])
        self.assertEqual(len(self.posts), 2)
        self.assertNotIn("historical_delivery_locked", self.record)

    def test_first_delivery_is_full_and_later_delivery_is_incremental(self):
        self.state["patches"].clear()
        self.assertEqual(self.process(self.old), "sent")
        record = self.state["patches"][self.old.patch_id]
        original_ids = list(record["summary_message_ids"])
        self.assertEqual(self.generated, [{}])
        self.assertEqual(record["summary_source_lines"], monitor.format_summary(self.old)[4:])
        self.assertEqual(self.process(), "updated")
        self.assertEqual(record["summary_message_ids"], original_ids)
        self.assertTrue(self.generated[-1]["revision"])
        self.assertEqual(len(self.posts), 3)  # Original, full card, one revision card.

    def test_legacy_recovery_preserves_numbered_multimessage_source(self):
        old = note(hero_lines(*[f"조건 {n}: 공격력이 30에서 28로 감소했습니다. 방벽에는 적용되지 않습니다." for n in range(160)]))
        payloads = monitor.decorate_payloads(monitor.build_discord_payloads(old))
        self.assertGreater(len(payloads), 1)
        self.get.side_effect = [self.response(content=item["content"]) for item in payloads]
        recovered = monitor.read_delivered_source(self.webhook, [str(n) for n in range(len(payloads))])
        self.assertEqual(recovered, monitor.format_summary(old)[4:])

    def test_reordering_only_updates_original_without_posting_any_cards(self):
        reordered = note(hero_lines("재사용 대기시간 12초 → 10초", "공격력 30 → 28"))
        self.assertEqual(self.process(reordered), "updated")
        self.post.assert_not_called()
        self.delete.assert_not_called()
        self.assertEqual(self.edit.call_count, 1)


if __name__ == "__main__":
    unittest.main()
