import contextlib
import copy
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests
import monitor


class ManualScopeTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(monitor, "STATE_FILE", directory / "state.json"))
        self.stack.enter_context(patch.dict(os.environ, {
            "LATEST_PATCH_ONLY": "true", "DRY_RUN": "false",
            "DISCORD_WEBHOOK_URL": "https://discord.invalid/api/webhooks/test/token",
        }))
        self.stack.enter_context(patch.object(monitor, "SEND_ON_FIRST_RUN", True))
        self.output = self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("Unexpected network call")))
        self.text = self.stack.enter_context(patch.object(monitor, "sync_discord_messages", return_value=["text-new"]))
        self.cards = self.stack.enter_context(patch.object(monitor, "refresh_summary_cards", return_value=["card-new"]))
        self.delete = self.stack.enter_context(patch.object(monitor, "delete_discord_message"))
        self.process = self.stack.enter_context(patch.object(monitor, "process_patch", wraps=monitor.process_patch))
        raws = []
        for date, title in [("2026-09-18", "최신"), ("2026-09-18", "같은 날 이전"), ("2026-09-11", "과거")]:
            items = [("h4", "영웅 업데이트"), ("li", f"{title} 패치의 방어력이 325에서 275로 감소했습니다.")]
            raws.append({"title": title, "date_key": date, "items": items, "images": [],
                         "body_hash": monitor.build_body_hash(title, items),
                         "source_url": "https://example.com/patch", "source_name": "nexon"})
        self.latest, self.same_day_old, self.older = monitor.assign_patch_ids(raws)
        # Deliberately unsorted: selection cannot rely on list position.
        self.patches = [self.same_day_old, self.latest, self.older]
        self.stack.enter_context(patch.object(monitor, "fetch_recent_patches", return_value=self.patches))

    def seed_state(self, include_latest=True):
        state = monitor.empty_state()
        for item in self.patches:
            if item is self.latest and not include_latest:
                continue
            record = monitor.make_record(item, "sent")
            record.update({"text_format_version": monitor.TEXT_FORMAT_VERSION,
                           "discord_message_ids": ["text-" + item.patch_id],
                           "summary_message_ids": ["card-" + item.patch_id]})
            if item is self.latest:
                record.update({"summary_card_version": monitor.SUMMARY_CARD_VERSION,
                               "summary_body_hash": item.body_hash})
            else:
                record["body_hash"] = "outdated body"
            state["patches"][item.patch_id] = record
        monitor.save_state(state)
        return copy.deepcopy(monitor.load_state()["patches"])

    def test_latest_selection_uses_date_and_newest_same_day_id(self):
        selected = monitor.select_delivery_patches(self.patches, True)
        self.assertEqual([p.patch_id for p in selected], ["2026-09-18#02"])
        self.assertEqual(len(self.patches), 3)
        self.assertEqual(monitor.select_delivery_patches([], True), [])

    def test_manual_current_latest_does_not_update_older_text_or_cards(self):
        before = self.seed_state()
        self.assertEqual(monitor.main(), 0)
        self.assertEqual([call.args[0].patch_id for call in self.process.call_args_list], [self.latest.patch_id])
        self.text.assert_not_called()
        self.cards.assert_not_called()
        self.delete.assert_not_called()
        after = monitor.load_state()["patches"]
        for old in (self.same_day_old, self.older):
            self.assertEqual(after[old.patch_id], before[old.patch_id])

    def test_manual_sends_only_latest_and_repeated_run_remains_idempotent(self):
        before = self.seed_state(include_latest=False)
        self.assertEqual(monitor.main(), 0)
        self.text.assert_called_once()
        self.cards.assert_called_once()
        self.assertEqual(self.cards.call_args.args[1].patch_id, self.latest.patch_id)
        self.assertEqual(monitor.main(), 0)
        self.assertEqual(self.text.call_count, 1)
        self.assertEqual(self.cards.call_count, 1)
        for old in (self.same_day_old, self.older):
            self.assertEqual(monitor.load_state()["patches"][old.patch_id], before[old.patch_id])

    def test_scheduled_run_cannot_unlock_historical_bulk_delivery(self):
        self.seed_state()
        # Even an explicit false value must not disable the production safety lock.
        with patch.dict(os.environ, {"LATEST_PATCH_ONLY": "false"}):
            self.assertEqual(monitor.main(), 0)
        self.assertEqual(
            [call.args[0].patch_id for call in self.process.call_args_list],
            [self.latest.patch_id],
        )
        self.text.assert_not_called()
        self.cards.assert_not_called()

    def test_fresh_manual_run_preserves_full_history_baseline(self):
        self.assertEqual(monitor.main(), 0)
        self.assertEqual([call.args[0].patch_id for call in self.process.call_args_list], [self.latest.patch_id])
        old_record = monitor.load_state()["patches"][self.older.patch_id]
        self.assertEqual(old_record["migration"], "fresh_install_baseline")
        self.assertEqual(old_record["discord_message_ids"], [])
        self.text.assert_called_once()
        self.cards.assert_called_once()

    def test_dry_run_previews_only_latest_without_writing(self):
        self.seed_state()
        before = monitor.STATE_FILE.read_bytes()
        with patch.dict(os.environ, {"DRY_RUN": "true", "DISCORD_WEBHOOK_URL": ""}):
            self.assertEqual(monitor.main(), 0)
        self.assertEqual(monitor.STATE_FILE.read_bytes(), before)
        self.assertIn(self.latest.patch_id, self.output.getvalue())
        self.assertNotIn(self.older.patch_id, self.output.getvalue())
        self.assertNotIn(self.same_day_old.patch_id, self.output.getvalue())
        self.process.assert_not_called()
        self.text.assert_not_called()
        self.cards.assert_not_called()

    def test_english_latest_waits_without_falling_back_to_older_korean(self):
        self.seed_state(include_latest=False)
        self.latest.items = [("li", "Armor decreased from 325 to 275.")]
        self.assertEqual(monitor.main(), 0)
        self.assertEqual(monitor.load_state()["patches"][self.latest.patch_id]["status"], "pending_korean")
        self.assertEqual(self.process.call_count, 1)
        self.text.assert_not_called()
        self.cards.assert_not_called()


if __name__ == "__main__":
    unittest.main()
