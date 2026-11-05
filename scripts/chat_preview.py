"""One-off chat preview from a verified public official page; no Discord calls."""
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor
import summary_cards


destination = Path("card-previews/chat-current")
source = "https://overwatch.nexon.com/news/patchnotes/858/patch-2026-11-03"
fixture = Path("tests/fixtures/nexon-nov4-chat-preview.html")
with patch("requests.sessions.Session.request", side_effect=AssertionError("Chat preview is offline")):
    raw = monitor.parse_nexon_article(fixture.read_text(encoding="utf-8"), source)
    if raw is None or raw["date_key"] != "2026-11-04":
        raise RuntimeError("Unexpected official patch in preview snapshot")
    current = monitor.assign_patch_ids([raw])[0]
    entries, general = monitor.prepare_card_data(current)
    paths = monitor.generate_summary_cards(current, destination)
    pages = summary_cards.plan_cards(entries, general, monitor._find_font_path)
    manifest = {
        "title": current.title, "date": current.date_key, "source_url": source,
        "card_version": monitor.SUMMARY_CARD_VERSION, "font_sizes_px": summary_cards.FONT_SIZES,
        "entries": entries,
        "pages": [{**{key: page[key] for key in ("mode", "category", "role", "number", "count", "height")},
                   "heroes": [row["hero"] for row in page["rows"]], "file": path.name}
                  for page, path in zip(pages, paths)],
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(current.title)
    print(f"Rendered official chat preview: {len(paths)} cards")
    for page in manifest["pages"]:
        print(f"{page['mode']} {page['category']} {page['role']} {page['number']}/{page['count']}: {page['file']}")
