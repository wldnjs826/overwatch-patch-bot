import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests
import monitor


def response(message_id="message", status=200):
    result = Mock(status_code=status)
    result.json.return_value = {"id": message_id}
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(response=result)
    return result


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(monitor, "STATE_FILE", self.directory / "state.json"))
        self.stack.enter_context(patch.object(monitor.time, "sleep"))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        # Fail closed: every network operation must be explicitly mocked in a test.
        self.stack.enter_context(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("Unexpected network call")))
        self.post = self.stack.enter_context(patch.object(monitor.requests, "post"))
        self.edit = self.stack.enter_context(patch.object(monitor.requests, "patch", return_value=response("card-1")))
        self.delete = self.stack.enter_context(patch.object(monitor.requests, "delete", return_value=response(status=204)))
        self.card = self.directory / "summary.png"
        self.card.write_bytes(b"test image: transport is mocked")
        self.generate = self.stack.enter_context(patch.object(monitor, "generate_summary_cards", return_value=[self.card]))
        self.real_build_payloads = monitor.build_discord_payloads
        self.payloads = self.stack.enter_context(patch.object(monitor, "build_discord_payloads", return_value=[{"content": "patch body", "embeds": []}]))
        items = [("h2", "영웅 업데이트"), ("li", "방어력이 325에서 275로 감소했습니다.")]
        self.patch = monitor.assign_patch_ids([{
            "title": "오버워치 패치 노트 - 2026년 9월 18일", "date_key": "2026-09-18",
            "items": items, "images": [], "body_hash": monitor.build_body_hash("title", items),
            "source_url": "https://example.com/patch", "source_name": "nexon",
        }])[0]
        self.state = monitor.empty_state()
        self.webhook = "https://discord.invalid/api/webhooks/test/token"

    def legacy_record(self):
        record = monitor.make_record(self.patch, "sent")
        self.state["patches"][self.patch.patch_id] = record
        return record

    def process(self):
        return monitor.process_patch(self.patch, self.state, self.webhook)

    def reload(self):
        self.state = monitor.load_state()
        return self.state["patches"][self.patch.patch_id]

    def test_unchanged_legacy_patch_backfills_cards_once(self):
        record = self.legacy_record()
        self.post.return_value = response("card-1")
        self.assertEqual(self.process(), "updated")
        self.assertEqual(record["discord_message_ids"], [])
        self.assertEqual(record["summary_message_ids"], ["card-1"])
        self.assertEqual(self.process(), "already_sent")
        self.assertEqual(self.post.call_count, 1)

    def test_changed_legacy_patch_sends_replacement_once(self):
        record = self.legacy_record()
        record["body_hash"] = "old"
        self.post.side_effect = [response("text-1"), response("card-1")]
        self.assertEqual(self.process(), "updated")
        self.assertEqual(record["discord_message_ids"], ["text-1"])
        self.assertEqual(self.process(), "already_sent")
        self.assertEqual(self.post.call_count, 2)

    def test_card_version_upgrade_edits_existing_card_once_without_resending_text(self):
        record = self.legacy_record()
        record.update({
            "discord_message_ids": ["text-1"],
            "summary_message_ids": ["card-1"],
            "summary_card_version": monitor.SUMMARY_CARD_VERSION - 1,
            "summary_body_hash": self.patch.body_hash,
        })
        self.assertEqual(self.process(), "updated")
        self.edit.assert_called_once()
        self.assertIn("/messages/card-1", self.edit.call_args.args[0])
        self.assertIn("files", self.edit.call_args.kwargs)
        self.post.assert_not_called()
        self.payloads.assert_not_called()
        self.assertEqual(self.reload()["summary_card_version"], monitor.SUMMARY_CARD_VERSION)
        self.assertEqual(self.process(), "already_sent")
        self.assertEqual(self.edit.call_count, 1)

    def test_previously_discarded_update_is_recovered(self):
        record = self.legacy_record()
        record["last_uneditable_change_utc"] = "2026-09-16T00:00:00Z"
        self.post.side_effect = [response("text-1"), response("card-1")]
        self.process()
        self.assertNotIn("last_uneditable_change_utc", record)
        self.assertEqual(record["discord_message_ids"], ["text-1"])
        self.assertEqual(self.process(), "already_sent")

    def test_card_failure_preserves_text_and_retries_only_card(self):
        self.post.side_effect = [response("text-1"), requests.ConnectionError("card failed")]
        with self.assertRaises(requests.ConnectionError):
            self.process()
        record = self.reload()
        self.assertEqual(record["status"], "sent")
        self.assertEqual(record["discord_message_ids"], ["text-1"])
        self.post.reset_mock(side_effect=True)
        self.post.return_value = response("card-1")
        self.assertEqual(self.process(), "updated")
        self.assertEqual(self.post.call_count, 1)
        self.assertIn("files", self.post.call_args.kwargs)
        self.edit.assert_not_called()

    def test_partial_text_delivery_resumes_using_saved_id(self):
        self.payloads.return_value *= 2
        self.post.side_effect = [response("text-1"), requests.ConnectionError("second text failed")]
        with self.assertRaises(requests.ConnectionError):
            self.process()
        record = self.reload()
        self.assertEqual(record["status"], "sending")
        self.assertEqual(record["discord_message_ids"], ["text-1"])
        self.post.reset_mock(side_effect=True)
        self.post.side_effect = [response("text-2"), response("card-1")]
        self.process()
        self.assertEqual(record["discord_message_ids"], ["text-1", "text-2"])
        self.assertEqual(self.post.call_count, 2)
        self.assertIn("/messages/text-1", self.edit.call_args.args[0])

    def test_partial_card_delivery_resumes_without_duplicate_card(self):
        self.legacy_record()
        self.generate.return_value = [self.card, self.card]
        self.post.side_effect = [response("card-1"), requests.ConnectionError("second card failed")]
        with self.assertRaises(requests.ConnectionError):
            self.process()
        record = self.reload()
        self.assertEqual(record["summary_message_ids"], ["card-1"])
        self.post.reset_mock(side_effect=True)
        self.post.return_value = response("card-2")
        self.process()
        self.assertEqual(record["summary_message_ids"], ["card-1", "card-2"])
        self.assertEqual(self.post.call_count, 1)
        self.assertIn("/messages/card-1", self.edit.call_args.args[0])

    def test_missing_discord_message_is_replaced(self):
        record = self.legacy_record()
        record["body_hash"] = "old"
        record["discord_message_ids"] = ["deleted"]
        self.edit.return_value = response(status=404)
        self.post.side_effect = [response("replacement"), response("card-1")]
        self.process()
        self.assertEqual(record["discord_message_ids"], ["replacement"])

    def test_empty_summary_is_not_repeated(self):
        self.legacy_record()
        self.generate.return_value = []
        self.assertEqual(self.process(), "updated")
        self.assertEqual(self.process(), "already_sent")
        self.assertEqual(self.generate.call_count, 1)
        self.post.assert_not_called()

    def test_first_run_baseline_does_not_send_historical_cards(self):
        record = self.legacy_record()
        record["migration"] = "fresh_install_baseline"
        self.assertEqual(self.process(), "already_sent")
        self.post.assert_not_called()
        self.generate.assert_not_called()

    def test_english_patch_stays_pending_without_discord_calls(self):
        self.patch.items = [("li", "Armor decreased from 325 to 275.")]
        self.assertEqual(self.process(), "pending_korean")
        self.post.assert_not_called()
        self.edit.assert_not_called()
        self.generate.assert_not_called()

    def test_dry_run_without_secret_never_writes_or_sends(self):
        monitor.save_state(self.state)
        before = monitor.STATE_FILE.read_bytes()
        with patch.dict(os.environ, {"DRY_RUN": "true", "DISCORD_WEBHOOK_URL": ""}), patch.object(monitor, "fetch_recent_patches", return_value=[self.patch]):
            self.assertEqual(monitor.main(), 0)
        self.assertEqual(monitor.STATE_FILE.read_bytes(), before)
        self.post.assert_not_called()
        self.edit.assert_not_called()

    def test_atomic_write_failure_keeps_previous_state(self):
        monitor.save_state(self.state)
        before = monitor.STATE_FILE.read_bytes()
        self.legacy_record()
        with patch.object(monitor.os, "replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                monitor.save_state(self.state)
        self.assertEqual(monitor.STATE_FILE.read_bytes(), before)
        self.assertFalse(monitor.STATE_FILE.with_suffix(".json.tmp").exists())

    def test_source_images_are_omitted_but_summary_card_is_sent(self):
        self.payloads.side_effect = self.real_build_payloads
        self.patch.images = ["https://example.com/hero.png", "https://example.com/ability.png"]
        self.patch.image_hash = monitor.build_image_hash(self.patch.images)
        self.post.side_effect = [response("text-1"), response("card-1")]
        self.assertEqual(self.process(), "sent")
        self.assertEqual(self.post.call_count, 2)
        text_request, card_request = self.post.call_args_list
        self.assertEqual(text_request.kwargs["json"]["embeds"], [])
        self.assertIn(self.patch.title, text_request.kwargs["json"]["content"])
        self.assertIn(self.patch.source_url, text_request.kwargs["json"]["content"])
        self.assertIn(self.patch.items[-1][1], text_request.kwargs["json"]["content"])
        for image_url in self.patch.images:
            self.assertNotIn(image_url, str(self.post.call_args_list))
        self.assertIn("files[0]", card_request.kwargs["files"])
        self.assertEqual(self.reload()["summary_message_ids"], ["card-1"])

    def test_source_image_change_does_not_resend_or_refresh_cards(self):
        record = self.legacy_record()
        record.update({
            "discord_message_ids": ["text-1", "old-source-images"],
            "summary_message_ids": ["card-1"],
            "summary_card_version": monitor.SUMMARY_CARD_VERSION,
            "summary_body_hash": self.patch.body_hash,
            "summary_image_hash": self.patch.image_hash,
        })
        self.patch.images = ["https://example.com/replaced-image.png"]
        self.patch.image_hash = monitor.build_image_hash(self.patch.images)
        self.assertEqual(self.process(), "already_sent")
        self.post.assert_not_called()
        self.edit.assert_not_called()
        self.delete.assert_not_called()
        self.generate.assert_not_called()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            monitor.preview_patches([self.patch], self.state)
        self.assertIn("변경 없음", output.getvalue())
        self.assertNotIn("대상", output.getvalue())

    def test_text_update_preserves_cards_and_removes_old_image_batch(self):
        self.payloads.side_effect = self.real_build_payloads
        record = self.legacy_record()
        record.update({
            "body_hash": "previous body",
            "discord_message_ids": ["text-1", "old-source-images"],
            "summary_message_ids": ["card-1"],
            "summary_card_version": monitor.SUMMARY_CARD_VERSION,
            "summary_body_hash": "previous body",
        })
        self.patch.images = ["https://example.com/updated-image.png"]
        self.patch.image_hash = monitor.build_image_hash(self.patch.images)
        self.assertEqual(self.process(), "updated")
        self.post.assert_not_called()
        self.assertEqual(self.edit.call_count, 2)
        self.assertIn("/messages/text-1", self.edit.call_args_list[0].args[0])
        self.assertIn("files", self.edit.call_args_list[1].kwargs)
        self.delete.assert_called_once()
        self.assertIn("/messages/old-source-images", self.delete.call_args.args[0])
        self.assertEqual(record["discord_message_ids"], ["text-1"])
        self.assertEqual(record["summary_message_ids"], ["card-1"])
        self.assertEqual(self.process(), "already_sent")


if __name__ == "__main__":
    unittest.main()
