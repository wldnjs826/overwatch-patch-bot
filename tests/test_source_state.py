"""Regressions for exact official-source matching and saved Discord identities."""
import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

import monitor


NEXON_URL = "https://overwatch.nexon.com/news/patchnotes/830/patch-2026-09-18"
BLIZZARD_URL = "https://overwatch.blizzard.com/ko-kr/news/patch-notes/live/2026/09#patch-2026-09-18"


def official_patch(source="nexon", value=200, items=None):
    if items is None:
        items = [("h3", "일반 모드 (5대5)"), ("h4", "영웅 업데이트"),
                 ("h4", "돌격"), ("h5", "D.Va"),
                 ("li", f"메카의 기본 생명력이 175에서 {value}으로 증가했습니다.")]
    title = "오버워치 패치 노트 - 2026년 9월 18일"
    note = monitor.assign_patch_ids([{
        "title": title, "date_key": "2026-09-18", "items": items, "images": [],
        "body_hash": monitor.build_body_hash(title, items),
        "source_url": NEXON_URL if source == "nexon" else BLIZZARD_URL,
        "source_name": source,
    }])[0]
    if source == "blizzard":
        note.patch_id += "-blizzard"
    return note


class SourceIdentityTests(unittest.TestCase):
    def setUp(self):
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def test_h3_mode_and_application_condition_are_part_of_identity(self):
        normal = official_patch()
        for heading in ("스타디움 (5대5)", "일반 모드 (6대6)"):
            with self.subTest(heading=heading):
                changed = official_patch("blizzard", items=[("h3", heading), *normal.items[1:]])
                self.assertNotEqual(monitor.source_identity(normal), monitor.source_identity(changed))

    def test_paragraph_boundaries_prevent_accidental_identity_concatenation(self):
        separate = official_patch(items=[("p", "공격력이 30"), ("p", "에서 28로 감소했습니다.")])
        combined = official_patch("blizzard", items=[("p", "공격력이 30에서 28로 감소했습니다.")])
        self.assertNotEqual(monitor.source_identity(separate), monitor.source_identity(combined))


class SourceStateTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(monitor, "STATE_FILE", directory / "state.json"))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(requests.sessions.Session, "request",
                                             side_effect=AssertionError("Unexpected network call")))
        self.sync = self.stack.enter_context(patch.object(
            monitor, "sync_discord_messages", side_effect=lambda _url, ids, *_args: list(ids) or ["new-text"]))
        self.cards = self.stack.enter_context(patch.object(monitor, "refresh_summary_cards", return_value=[]))
        self.delete = self.stack.enter_context(patch.object(monitor, "delete_discord_message"))
        self.state = monitor.empty_state()
        self.webhook = "https://discord.invalid/api/webhooks/test/token"

    def sent_record(self, note):
        record = monitor.make_record(note, "sent")
        record.update({"discord_message_ids": ["existing-text"],
                       "summary_card_version": monitor.SUMMARY_CARD_VERSION,
                       "summary_body_hash": note.body_hash, "summary_empty": True,
                       "text_format_version": monitor.TEXT_FORMAT_VERSION})
        self.state["patches"][note.patch_id] = record
        return record

    def delivered_content(self):
        return "\n".join(payload["content"] for payload in self.sync.call_args.args[2])

    def test_blizzard_cannot_be_sent_or_overwrite_nexon(self):
        nexon = official_patch(value=200)
        original = copy.deepcopy(self.sent_record(nexon))
        blizzard = official_patch("blizzard", value=225)
        with self.assertRaisesRegex(ValueError, "넥슨 패치노트만"):
            monitor.process_patch(blizzard, self.state, self.webhook)
        self.assertEqual(self.state["patches"], {nexon.patch_id: original})
        self.sync.assert_not_called()
        self.cards.assert_not_called()

    def test_different_legacy_source_keeps_its_own_message_ids(self):
        blizzard = official_patch("blizzard", value=200)
        nexon = official_patch(value=225)
        blizzard.patch_id = nexon.patch_id  # Old state lacked a source suffix.
        original = copy.deepcopy(self.sent_record(blizzard))
        self.assertEqual(monitor.process_patch(nexon, self.state, self.webhook), "sent")
        self.assertEqual(self.state["patches"][nexon.patch_id + "-blizzard"],
                         {**original, "patch_id": nexon.patch_id + "-blizzard"})
        self.assertEqual(self.sync.call_args.args[1], [])
        self.assertIn("225", self.delivered_content())
        self.assertIn(NEXON_URL, self.delivered_content())
        self.delete.assert_not_called()

    def test_confirmed_nexon_adopts_blizzard_text_id_and_updates_displayed_source(self):
        blizzard = official_patch("blizzard")
        original = self.sent_record(blizzard)
        original.pop("source_identity")  # Pre-v4 records still retain the exact original body hash.
        original.update({"summary_message_ids": ["existing-card"], "summary_empty": False})
        self.cards.return_value = ["replacement-card"]
        nexon = official_patch()
        self.assertEqual(monitor.process_patch(nexon, self.state, self.webhook), "updated")
        self.assertEqual(self.sync.call_args.args[1], ["existing-text"])
        self.assertIn(NEXON_URL, self.delivered_content())
        self.assertNotIn(BLIZZARD_URL, self.delivered_content())
        self.delete.assert_not_called()
        self.cards.assert_not_called()
        current = self.state["patches"][nexon.patch_id]
        self.assertEqual(current["source_name"], "nexon")
        self.assertEqual(current["source_url"], NEXON_URL)
        self.assertEqual(current["discord_message_ids"], ["existing-text"])
        self.assertEqual(current["summary_message_ids"], ["existing-card"])
        self.assertEqual(self.state["patches"][blizzard.patch_id]["status"], "duplicate_source")
        self.assertEqual(self.state["patches"][blizzard.patch_id]["duplicate_of"], nexon.patch_id)
        self.assertEqual(monitor.process_patch(nexon, self.state, self.webhook), "already_sent")
        self.assertEqual(self.sync.call_count, 1)

    def test_same_day_article_keeps_its_message_ids_when_list_order_changes(self):
        older = official_patch(value=200)
        original = copy.deepcopy(self.sent_record(older))
        latest = official_patch(value=225)
        latest.source_url = f"{monitor.NEXON_LIST_URL}/831/newer"

        # Only the newest article was readable, so both were assigned #01.
        self.assertEqual(latest.patch_id, older.patch_id)
        self.assertEqual(monitor.process_patch(latest, self.state, self.webhook), "sent")
        self.assertEqual(self.state["patches"][older.patch_id], original)
        self.assertEqual(self.sync.call_args.args[1], [])

        # When both articles are readable, #02 must reuse the new message.
        latest.patch_id = latest.date_key + "#02"
        self.assertEqual(monitor.process_patch(latest, self.state, self.webhook), "already_sent")
        self.sync.assert_called_once()

    def test_nexon_hotfix_862_edits_the_verified_legacy_delivery(self):
        blizzard = official_patch("blizzard")
        blizzard.date_key = "2026-11-06"
        blizzard.patch_id = "2026-11-06#01-blizzard"
        blizzard.body_hash = "7eede3454bfdc5447985ef33212cf6f3181e289b086757f02413fa3a9524aa3b"
        old = self.sent_record(blizzard)
        old["summary_source_lines"] = monitor.format_summary(blizzard)[4:]
        old["summary_message_ids"] = ["existing-card"]
        nexon = official_patch(items=[*blizzard.items, ("p", "핫픽스 패치 안내입니다.")])
        nexon.date_key = blizzard.date_key
        nexon.patch_id = "2026-11-06#01"
        nexon.source_url = f"{monitor.NEXON_LIST_URL}/862/patch-2026-11-05"

        with patch.object(monitor, "send_summary_cards", return_value=[]) as revision:
            self.assertEqual(monitor.process_patch(nexon, self.state, self.webhook), "updated")
        self.assertEqual(self.sync.call_args.args[1], ["existing-text"])
        self.assertIn(nexon.source_url, self.delivered_content())
        self.assertEqual(self.state["patches"][nexon.patch_id]["summary_message_ids"], ["existing-card"])
        revision.assert_called_once()
        self.assertTrue(revision.call_args.kwargs["revision"])
        self.cards.assert_not_called()
        self.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
