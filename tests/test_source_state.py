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
    return monitor.assign_patch_ids([{
        "title": title, "date_key": "2026-09-18", "items": items, "images": [],
        "body_hash": monitor.build_body_hash(title, items),
        "source_url": NEXON_URL if source == "nexon" else BLIZZARD_URL,
        "source_name": source,
    }])[0]


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
                self.assertEqual(len(monitor.choose_patches([normal], [changed])), 2)

    def test_paragraph_boundaries_prevent_accidental_identity_concatenation(self):
        separate = official_patch(items=[("p", "공격력이 30"), ("p", "에서 28로 감소했습니다.")])
        combined = official_patch("blizzard", items=[("p", "공격력이 30에서 28로 감소했습니다.")])
        self.assertNotEqual(monitor.source_identity(separate), monitor.source_identity(combined))
        self.assertEqual(len(monitor.choose_patches([separate], [combined])), 2)

    def test_blizzard_ids_stay_stable_when_nexon_is_unavailable_then_returns(self):
        nexon = official_patch(value=200)
        with_nexon = official_patch("blizzard", value=225)
        without_nexon = official_patch("blizzard", value=225)
        expected = with_nexon.patch_id + "-blizzard"
        selected = monitor.choose_patches([nexon], [with_nexon])
        fallback = monitor.choose_patches([], [without_nexon])
        self.assertIn(with_nexon, selected)
        self.assertEqual(with_nexon.patch_id, expected)
        self.assertEqual(fallback[0].patch_id, expected)
        self.assertEqual(monitor.choose_patches([], [without_nexon])[0].patch_id, expected,
                         "A second selection must not append the suffix again")


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

    def test_unmatched_blizzard_does_not_overwrite_existing_nexon_record(self):
        nexon = official_patch(value=200)
        original = copy.deepcopy(self.sent_record(nexon))
        blizzard = monitor.choose_patches([], [official_patch("blizzard", value=225)])[0]
        self.assertEqual(monitor.process_patch(blizzard, self.state, self.webhook), "sent")
        self.assertEqual(self.state["patches"][nexon.patch_id], original)
        self.assertNotEqual(blizzard.patch_id, nexon.patch_id)
        self.assertEqual(self.sync.call_args.args[1], [])
        self.assertIn("225", self.delivered_content())
        self.assertIn(BLIZZARD_URL, self.delivered_content())
        self.assertNotIn(NEXON_URL, self.delivered_content())
        self.delete.assert_not_called()

    def test_legacy_unsuffixed_collision_preserves_different_nexon_message_ids(self):
        nexon = official_patch(value=200)
        original = copy.deepcopy(self.sent_record(nexon))
        blizzard = official_patch("blizzard", value=225)
        self.assertEqual(nexon.patch_id, blizzard.patch_id)
        self.assertEqual(monitor.process_patch(blizzard, self.state, self.webhook), "sent")
        preserved = [record for record in self.state["patches"].values()
                     if record.get("source_name") == "nexon"]
        self.assertEqual(len(preserved), 1)
        self.assertEqual(preserved[0]["source_url"], original["source_url"])
        self.assertEqual(preserved[0]["body_hash"], original["body_hash"])
        self.assertEqual(preserved[0]["discord_message_ids"], ["existing-text"])
        self.assertEqual(preserved[0]["status"], "sent")
        self.assertEqual(self.sync.call_args.args[1], [])
        self.delete.assert_not_called()

    def test_legacy_blizzard_record_moves_to_stable_id_without_resending(self):
        blizzard = official_patch("blizzard")
        legacy_id = blizzard.patch_id
        legacy = self.sent_record(blizzard)
        legacy.pop("source_identity")
        blizzard = monitor.choose_patches([], [blizzard])[0]
        self.assertEqual(monitor.process_patch(blizzard, self.state, self.webhook), "already_sent")
        record = self.state["patches"][blizzard.patch_id]
        self.assertEqual(record["discord_message_ids"], ["existing-text"])
        self.assertEqual(record["status"], "sent")
        self.assertEqual(self.state["patches"][legacy_id]["status"], "duplicate_source")
        self.assertEqual(self.state["patches"][legacy_id]["duplicate_of"], blizzard.patch_id)
        self.sync.assert_not_called()
        self.cards.assert_not_called()

    def test_old_fuzzy_duplicate_is_rechecked_when_numbers_differ(self):
        nexon = official_patch(value=200)
        original = copy.deepcopy(self.sent_record(nexon))
        previous = monitor.choose_patches([], [official_patch("blizzard", value=200)])[0]
        duplicate = monitor.make_record(previous, "duplicate_source")
        duplicate.pop("source_identity")
        duplicate["duplicate_of"] = nexon.patch_id
        self.state["patches"][previous.patch_id] = duplicate
        changed = monitor.choose_patches([], [official_patch("blizzard", value=225)])[0]
        self.assertEqual(monitor.process_patch(changed, self.state, self.webhook), "sent")
        self.assertEqual(self.state["patches"][nexon.patch_id], original)
        self.assertEqual(self.state["patches"][changed.patch_id]["status"], "sent")
        self.assertNotIn("duplicate_of", self.state["patches"][changed.patch_id])
        self.assertIn("225", self.delivered_content())

    def test_confirmed_nexon_adopts_blizzard_text_id_and_updates_displayed_source(self):
        blizzard = monitor.choose_patches([], [official_patch("blizzard")])[0]
        original = self.sent_record(blizzard)
        original.update({"summary_message_ids": ["existing-card"], "summary_empty": False})
        self.cards.return_value = ["replacement-card"]
        nexon = official_patch()
        self.assertEqual(monitor.process_patch(nexon, self.state, self.webhook), "updated")
        self.assertEqual(self.sync.call_args.args[1], ["existing-text"])
        self.assertIn(NEXON_URL, self.delivered_content())
        self.assertNotIn(BLIZZARD_URL, self.delivered_content())
        self.delete.assert_called_once_with(self.webhook, "existing-card")
        current = self.state["patches"][nexon.patch_id]
        self.assertEqual(current["source_name"], "nexon")
        self.assertEqual(current["source_url"], NEXON_URL)
        self.assertEqual(current["discord_message_ids"], ["existing-text"])
        self.assertEqual(current["summary_message_ids"], ["replacement-card"])
        self.assertEqual(self.state["patches"][blizzard.patch_id]["status"], "duplicate_source")
        self.assertEqual(self.state["patches"][blizzard.patch_id]["duplicate_of"], nexon.patch_id)
        self.assertEqual(monitor.process_patch(nexon, self.state, self.webhook), "already_sent")
        self.assertEqual(self.sync.call_count, 1)


if __name__ == "__main__":
    unittest.main()
