"""Acceptance checks for complete official text and ordered Discord delivery."""
import contextlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

import monitor
import summary_cards


NEXON_URL = "https://overwatch.nexon.com/news/patchnotes/830/patch-2026-09-18"
BLIZZARD_URL = "https://overwatch.blizzard.com/ko-kr/news/patch-notes/live/2026/09#patch-2026-09-18"


def official_patch(items, source="nexon", date="2026-09-18", url=None):
    title = f"오버워치 패치 노트 - {date}"
    return monitor.assign_patch_ids([{
        "title": title,
        "date_key": date,
        "items": list(items),
        "images": [],
        "body_hash": monitor.build_body_hash(title, items),
        "source_url": url or (NEXON_URL if source == "nexon" else BLIZZARD_URL),
        "source_name": source,
    }])[0]


def without_sequence(content):
    return re.sub(r"^\*\*\[\d+/\d+\]\*\*\n", "", content)


class OriginalTextContractTests(unittest.TestCase):
    def test_more_than_twenty_messages_keep_every_original_condition_and_value(self):
        notes = [
            f"항목 {index:03d}: 적에게 적중한 경우에만 12초에서 10초로 감소합니다. "
            "생명력 175 → 200, 20% → 25%, 0.5미터, 20%p (6대6). "
            + "아군의 상태에 따라 적용되는 조건을 유지합니다. " * 55
            + f"마지막 조건 {index:03d}: 방벽에는 적용되지 않습니다."
            for index in range(42)
        ]
        patch_note = official_patch([("h4", "일반 업데이트"), *[("p", line) for line in notes]])
        payloads = monitor.decorate_payloads(monitor.build_discord_payloads(patch_note))
        self.assertGreater(len(payloads), 20)
        received = "\n".join(without_sequence(item["content"]) for item in payloads)
        for line in notes:
            self.assertIn(line, received)
        self.assertIn(NEXON_URL, received)
        self.assertNotIn("일부 텍스트만 표시", received)
        self.assertTrue(all(len(item["content"]) <= 2000 for item in payloads))

    def test_message_numbers_do_not_remove_the_end_of_full_chunks(self):
        originals = ["가" * (monitor.MESSAGE_LIMIT - 12) + "끝수치 0.25초!", "둘째 조건: 6대6에서만 적용"]
        # A full-size chunk previously lost its suffix when the index was added.
        originals[0] += "!" * (monitor.MESSAGE_LIMIT - len(originals[0]))
        payloads = monitor.decorate_payloads([{"content": text, "embeds": []} for text in originals])
        self.assertEqual([without_sequence(item["content"]) for item in payloads], originals)
        self.assertTrue(all(len(item["content"]) <= 2000 for item in payloads))

    def test_one_very_long_original_paragraph_survives_all_chunk_boundaries(self):
        text = "".join(
            f"조건{index:04d}: 재사용 대기시간 12초 → 10초, 175 → 200 (5대5). "
            for index in range(950)
        )
        chunks = monitor.split_text_messages([text])
        self.assertGreater(len(chunks), 20)
        decorated = monitor.decorate_payloads([{"content": chunk, "embeds": []} for chunk in chunks])
        self.assertEqual("".join(without_sequence(item["content"]) for item in decorated), text)


class OfficialSourceContractTests(unittest.TestCase):
    def setUp(self):
        self.items = [("h4", "영웅 업데이트"), ("h4", "돌격"), ("h5", "D.Va"),
                      ("li", "생명력이 175에서 200으로 증가했습니다. (5대5)")]
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def test_verified_same_patch_prefers_nexon_url_in_original_text(self):
        nexon = official_patch(self.items)
        blizzard = official_patch(self.items, source="blizzard")
        selected = monitor.choose_patches([nexon], [blizzard])
        self.assertEqual(len(selected), 1)
        body = "\n".join(monitor.format_summary(selected[0]))
        self.assertIn("출처: 넥슨 공식", body)
        self.assertIn(NEXON_URL, body)
        self.assertNotIn(BLIZZARD_URL, body)

    def test_no_matching_nexon_post_retains_confirmed_blizzard_url(self):
        blizzard = official_patch(self.items, source="blizzard")
        selected = monitor.choose_patches([], [blizzard])
        self.assertEqual(len(selected), 1)
        body = "\n".join(monitor.format_summary(selected[0]))
        self.assertIn("출처: Blizzard 공식", body)
        self.assertIn(BLIZZARD_URL, body)
        self.assertNotIn(NEXON_URL, body)

    def test_identical_words_on_another_date_do_not_borrow_nexon_link(self):
        nexon = official_patch(self.items)
        older_url = "https://overwatch.blizzard.com/ko-kr/news/patch-notes/live/2026/09#patch-2026-09-17"
        blizzard = official_patch(self.items, source="blizzard", date="2026-09-17", url=older_url)
        selected = monitor.choose_patches([nexon], [blizzard])
        self.assertEqual(len(selected), 2)
        older = next(item for item in selected if item.date_key == "2026-09-17")
        body = "\n".join(monitor.format_summary(older))
        self.assertIn(older_url, body)
        self.assertNotIn(NEXON_URL, body)

    def test_same_date_but_different_values_or_conditions_are_not_duplicates(self):
        for changed_line in ["생명력이 175에서 225로 증가했습니다. (5대5)",
                             "생명력이 175에서 200으로 증가했습니다. (6대6)"]:
            with self.subTest(line=changed_line):
                nexon = official_patch(self.items)
                blizzard = official_patch([*self.items[:-1], ("li", changed_line)], source="blizzard")
                selected = monitor.choose_patches([nexon], [blizzard])
                self.assertEqual(len(selected), 2)
                self.assertEqual({item.source_url for item in selected}, {NEXON_URL, BLIZZARD_URL})
                self.assertEqual(len({item.patch_id for item in selected}), 2,
                                 "Different same-day patches must not overwrite each other's state")


class OrderedDiscordContractTests(unittest.TestCase):
    def test_legacy_original_repair_rebuilds_cards_after_text_and_resumes_deletions(self):
        paragraphs = [f"원문 조건 {index}: " + "아군에게만 적용하며 방벽은 제외됩니다. " * 55
                      + "재사용 대기시간 12초 → 10초 (6대6)." for index in range(5)]
        patch_note = official_patch([("p", text) for text in paragraphs])
        record = monitor.make_record(patch_note, "sent")
        record.update({"discord_message_ids": ["old-text"],
                       "summary_message_ids": ["old-card-1", "old-card-2"],
                       "summary_card_version": monitor.SUMMARY_CARD_VERSION,
                       "summary_body_hash": patch_note.body_hash})
        state = monitor.empty_state()
        state["patches"][patch_note.patch_id] = record
        events, fail_once = [], [True]

        def ok(message_id="result"):
            result = Mock(status_code=200, headers={})
            result.json.return_value = {"id": message_id}
            return result

        def delete(url, **_kwargs):
            message_id = url.rsplit("/", 1)[-1]
            events.append(("delete", message_id))
            if message_id == "old-card-2" and fail_once[0]:
                fail_once[0] = False
                raise requests.ConnectionError("interrupted before acknowledgement")
            return ok()

        def edit(_url, **kwargs):
            events.append(("text", kwargs["json"]["content"]))
            return ok("old-text")

        def upload(_url, **kwargs):
            events.append(("card", "new-card") if "files" in kwargs else ("text", kwargs["json"]["content"]))
            return ok(f"new-{len(events)}")

        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(monitor, "STATE_FILE", Path(directory) / "state.json"))
            stack.enter_context(patch.object(monitor.time, "sleep"))
            stack.enter_context(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("Unexpected network call")))
            stack.enter_context(patch.object(monitor.requests, "delete", side_effect=delete))
            stack.enter_context(patch.object(monitor.requests, "patch", side_effect=edit))
            stack.enter_context(patch.object(monitor.requests, "post", side_effect=upload))
            card = Path(directory) / "card.png"
            card.write_bytes(b"mock card")
            stack.enter_context(patch.object(monitor, "generate_summary_cards", return_value=[card]))
            webhook = "https://discord.invalid/api/webhooks/test/token"
            with self.assertRaises(requests.ConnectionError):
                monitor.process_patch(patch_note, state, webhook)
            state = monitor.load_state()
            self.assertEqual(state["patches"][patch_note.patch_id]["summary_message_ids"], ["old-card-2"])
            monitor.process_patch(patch_note, state, webhook)
            self.assertEqual(state["patches"][patch_note.patch_id]["text_format_version"], monitor.TEXT_FORMAT_VERSION)
            count = len(events)
            self.assertEqual(monitor.process_patch(patch_note, state, webhook), "already_sent")
            self.assertEqual(len(events), count)

        self.assertEqual(events.count(("delete", "old-card-1")), 1)
        self.assertEqual(events.count(("delete", "old-card-2")), 2)
        self.assertEqual([kind for kind, _ in events[:3]], ["delete"] * 3)
        self.assertTrue(all(kind == "text" for kind, _ in events[3:-1]))
        self.assertEqual(events[-1][0], "card")
        received = "".join(without_sequence(content) for kind, content in events if kind == "text")
        for text in paragraphs:
            self.assertIn(text, received)

    def test_complete_original_precedes_all_normal_cards_then_all_stadium_cards(self):
        items = [("developer", "개발자의 의견: 0.25초와 20%p는 원문 그대로 유지하며, 방벽에는 적용되지 않습니다.")]
        role_heroes = {"돌격": ["D.Va", "라인하르트", "윈스턴"],
                       "공격": ["캐서디", "리퍼", "솔저: 76"],
                       "지원": ["아나", "메르시", "키리코"]}
        changes = {
            "buff": ["생명력이 175에서 200으로 증가했습니다."],
            "nerf": ["공격력이 30에서 28로 감소했습니다."],
            "adjust": ["재사용 대기시간이 12초에서 10초로 감소했습니다.",
                       "공격력이 30에서 28로 감소했습니다."],
        }
        # Deliberately provide roles/categories in a different order from output.
        for mode_index, heading in enumerate(["영웅 업데이트", "스타디움 업데이트"]):
            items.append(("h4", heading))
            categories = ["buff", "nerf", "adjust"] if mode_index == 0 else ["nerf", "adjust", "buff"]
            for role in ["지원", "공격", "돌격"]:
                items.append(("h4", role))
                for hero, category in zip(role_heroes[role], categories):
                    items.append(("h5", hero))
                    items.extend(("li", line) for line in changes[category])
                    if mode_index == 0 and hero == "D.Va":
                        items.extend(("li", f"생명력이 175에서 {201 + index}로 증가했습니다. (5대5)")
                                     for index in range(20))
        patch_note = official_patch(items)
        patch_note.images = ["https://example.invalid/source-image.png"]
        events, pages_by_file = [], {}

        def render_stub(**kwargs):
            pages = summary_cards.plan_cards(kwargs["entries"], kwargs["general_changes"], kwargs["font_path"])
            paths = []
            for index, page in enumerate(pages):
                output = Path(kwargs["output_dir"]) / f"card-{index:03d}.png"
                output.write_bytes(b"mock image; real layout measured, transport mocked")
                pages_by_file[output.name] = page
                paths.append(output)
            return paths

        def upload(_url, **kwargs):
            if "files" in kwargs:
                payload = json.loads(kwargs["data"]["payload_json"])
                page = pages_by_file[payload["attachments"][0]["filename"]]
                events.append(("card", page))
            else:
                events.append(("text", kwargs["json"]["content"]))
            result = Mock(status_code=200, headers={})
            result.json.return_value = {"id": str(len(events))}
            return result

        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(monitor, "STATE_FILE", Path(directory) / "state.json"))
            stack.enter_context(patch.object(monitor.time, "sleep"))
            stack.enter_context(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("Unexpected network call")))
            stack.enter_context(patch.object(monitor.requests, "post", side_effect=upload))
            stack.enter_context(patch.object(monitor, "render_cards", side_effect=render_stub))
            state = monitor.empty_state()
            self.assertEqual(monitor.process_patch(patch_note, state, "https://discord.invalid/api/webhooks/test/token"), "sent")

        first_card = next(index for index, event in enumerate(events) if event[0] == "card")
        self.assertGreater(first_card, 0)
        self.assertTrue(all(kind == "text" for kind, _ in events[:first_card]))
        self.assertTrue(all(kind == "card" for kind, _ in events[first_card:]))
        original_received = "\n".join(without_sequence(content) for _, content in events[:first_card])
        for _, original in items:
            self.assertIn(original, original_received)
        self.assertNotIn(patch_note.images[0], original_received)

        keys = [(page["mode"], page["category"], page["role"]) for _, page in events[first_card:]]
        groups = [key for index, key in enumerate(keys) if index == 0 or key != keys[index - 1]]
        self.assertEqual(groups, [(mode, category, role)
                                 for mode in ["일반전", "스타디움"]
                                 for category in ["buff", "nerf", "adjust"]
                                 for role in ["돌격", "공격", "지원"]])
        self.assertGreater(keys.count(("일반전", "buff", "돌격")), 1)
        for _, page in events[first_card:]:
            self.assertTrue(page["rows"])
            self.assertEqual({(row["mode"], row["category"], row["role"]) for row in page["rows"]},
                             {(page["mode"], page["category"], page["role"])})
        dva = {(page["mode"], page["category"]) for _, page in events[first_card:]
               if any(row["hero"] == "D.Va" for row in page["rows"])}
        self.assertEqual(dva, {("일반전", "buff"), ("스타디움", "nerf")})


class MissingMessageOrderTests(unittest.TestCase):
    def check_missing_suffix_recovery(self, kind, failure_stage):
        """Model channel chronology, including an interrupted suffix rebuild."""
        saved_ids = ["old-0", "missing-1", "old-2", "old-3"]
        channel = [{"id": message_id, "value": f"old content {index}"}
                   for index, message_id in enumerate(saved_ids) if message_id != "missing-1"]
        deletes, uploads = [], []
        failed = [False]
        acknowledged_posts = [0]

        def response(message_id="", status=200):
            result = Mock(status_code=status, headers={})
            result.json.return_value = {"id": message_id}
            if status >= 400:
                result.raise_for_status.side_effect = requests.HTTPError(response=result)
            return result

        def content(kwargs):
            if kind == "text":
                return without_sequence(kwargs["json"]["content"])
            payload = json.loads(kwargs["data"]["payload_json"])
            filename, stream, _mime = kwargs["files"]["files[0]"]
            uploads.append((filename, stream.read()))
            return payload["attachments"][0]["filename"]

        def edit(url, **kwargs):
            message_id = url.rsplit("/", 1)[-1]
            value = content(kwargs)
            message = next((item for item in channel if item["id"] == message_id), None)
            if message is None:
                return response(status=404)
            message["value"] = value
            return response(message_id)

        def delete(url, **_kwargs):
            message_id = url.rsplit("/", 1)[-1]
            deletes.append(message_id)
            if failure_stage == "delete" and message_id == "old-2" and not failed[0]:
                failed[0] = True
                raise requests.ConnectionError("delete not acknowledged")
            message = next((item for item in channel if item["id"] == message_id), None)
            if message is None:
                return response(status=404)
            channel.remove(message)
            return response(status=204)

        def post(_url, **kwargs):
            value = content(kwargs)
            if failure_stage == "post" and acknowledged_posts[0] == 1 and not failed[0]:
                failed[0] = True
                raise requests.ConnectionError("replacement post not acknowledged")
            acknowledged_posts[0] += 1
            message_id = f"new-{acknowledged_posts[0]}"
            channel.append({"id": message_id, "value": value})
            return response(message_id)

        def checkpoint(ids):
            saved_ids[:] = ids

        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(monitor.time, "sleep"))
            stack.enter_context(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("Unexpected network call")))
            stack.enter_context(patch.object(monitor.requests, "post", side_effect=post))
            stack.enter_context(patch.object(monitor.requests, "patch", side_effect=edit))
            stack.enter_context(patch.object(monitor.requests, "delete", side_effect=delete))
            webhook = "https://discord.invalid/api/webhooks/test/token"
            if kind == "text":
                expected = [f"원문 {index}: 재사용 대기시간 12초 → 10초 (6대6)" for index in range(4)]
                payloads = [{"content": value, "embeds": []} for value in expected]

                def deliver():
                    return monitor.sync_discord_messages(webhook, saved_ids, payloads, checkpoint)
            else:
                paths = [Path(directory) / f"card-{index}.png" for index in range(4)]
                for path in paths:
                    path.write_bytes(f"mock image {path.name}".encode())
                expected = [path.name for path in paths]
                stack.enter_context(patch.object(monitor, "generate_summary_cards", return_value=paths))
                patch_note = official_patch([("li", "생명력이 175에서 200으로 증가했습니다.")])

                def deliver():
                    return monitor.send_summary_cards(webhook, patch_note, saved_ids, checkpoint)

            with self.assertRaises(requests.ConnectionError):
                deliver()
            if failure_stage == "delete":
                self.assertEqual(saved_ids, ["old-0", "missing-1", "old-2"])
                self.assertEqual(acknowledged_posts[0], 0)
            else:
                self.assertEqual(saved_ids, ["old-0", "new-1"])
            final_ids = deliver()
            self.assertEqual([message["value"] for message in channel], expected)
            self.assertEqual(final_ids, [message["id"] for message in channel])
            self.assertEqual(saved_ids, final_ids)
            self.assertEqual(deletes.count("old-3"), 1)
            self.assertEqual(deletes.count("old-2"), 2 if failure_stage == "delete" else 1)
            self.assertEqual(deletes.count("missing-1"), 1)
            for filename, data in uploads:
                self.assertEqual(data, f"mock image {filename}".encode())
            before = list(channel)
            self.assertEqual(deliver(), final_ids)
            self.assertEqual(channel, before)
            self.assertEqual(acknowledged_posts[0], 3)

    def test_text_404_keeps_chronological_order_across_delete_and_upload_failures(self):
        for failure_stage in ["delete", "post"]:
            with self.subTest(stage=failure_stage):
                self.check_missing_suffix_recovery("text", failure_stage)

    def test_card_404_keeps_chronological_order_across_delete_and_upload_failures(self):
        for failure_stage in ["delete", "post"]:
            with self.subTest(stage=failure_stage):
                self.check_missing_suffix_recovery("card", failure_stage)


if __name__ == "__main__":
    unittest.main()
