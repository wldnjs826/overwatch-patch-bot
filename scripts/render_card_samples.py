"""Offline CI previews: illustrative reference data, never Discord delivery."""
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor
import summary_cards


def sample(name, items):
    title = f"오버워치 카드 표기 예시 - {name}"
    return monitor.assign_patch_ids([{
        "title": title, "date_key": "형식 예시", "items": items, "images": [],
        "body_hash": monitor.build_body_hash(title, items),
        "source_url": "https://example.com/format-reference", "source_name": "nexon",
    }])[0]


def all_groups_sample():
    heroes = {
        "돌격": ("D.Va", "자리야", "라마트라"),
        "공격": ("캐서디", "솔저: 76", "애쉬"),
        "지원": ("아나", "메르시", "바티스트"),
    }
    changes = [
        ["생명력이 175에서 200으로 증가했습니다."],
        ["공격력이 30에서 28로 감소했습니다."],
        ["재사용 대기시간이 12초에서 10초로 감소했습니다.", "공격력이 30에서 28로 감소했습니다."],
    ]
    items = []
    for mode in ("영웅 업데이트", "스타디움 업데이트"):
        items.append(("h4", mode))
        for role, names in heroes.items():
            items.append(("h4", role))
            for hero, lines in zip(names, changes):
                items.append(("h5", hero))
                items.extend(("li", line) for line in lines)
    return sample("모드·분류·역할 18개 조합", items)


def main():
    examples = {
        "buff": sample("상향", [
            ("h4", "영웅 업데이트"), ("h4", "돌격"), ("h5", "D.Va"),
            ("li", "메카의 기본 생명력이 175에서 200으로 증가했습니다."),
            ("h5", "도미나"), ("li", "궁극기 비용이 6% 감소했습니다."),
            ("h4", "공격"), ("h5", "안란"), ("h6", "주작 부활"),
            ("li", "시전 시간이 3초에서 2.5초로 감소했습니다."),
            ("h4", "지원"), ("h5", "바티스트"), ("h6", "불사 장치"),
            ("li", "처치 불가 생명력 한계치가 20%에서 25%로 증가했습니다."),
            ("li", "재사용 대기시간이 22초에서 20초로 감소했습니다."),
            ("li", "내구도가 125에서 150으로 증가했습니다."),
        ]),
        "adjust": sample("조정", [
            ("h4", "영웅 업데이트"), ("h4", "공격"), ("h5", "정크랫"),
            ("h6", "충격 지뢰"), ("li", "재사용 대기시간이 8초에서 7초로 감소했습니다."),
            ("p", "니트로 부스트 - 보조 특전"), ("li", "추가 속도가 125%에서 100%로 감소했습니다."),
            ("h5", "토르비욘"), ("h6", "대못 발사기"),
            ("li", "보조 발사 분산도가 4.5에서 4로 감소했습니다."),
            ("p", "고정 나사 - 주요 특전"),
            ("li", "포탑 설치 투척 사거리 증가량이 50%에서 25%로 감소했습니다."),
            ("h5", "벤데타"), ("h6", "팔라틴 팽"),
            ("li", "첫 휘두르기 지연 시간이 0.3초에서 0.15초로 감소했습니다."),
            ("li", "연속 공격 지속 시간이 0.75초에서 0.9초로 증가했습니다."),
            ("h6", "소용돌이 질주"), ("li", "회복 시간이 0.5초에서 0.75초로 증가했습니다."),
        ]),
        "long": sample("여러 페이지", [
            ("h4", "영웅 업데이트"), ("h5", "D.Mon"),
            *[("li", f"항목 {n + 1}: 방어력이 325에서 {275 - n}로 감소했습니다. (5대5)") for n in range(35)],
        ]),
        "general": sample("일반 변경", [
            ("h4", "버그 수정"), ("li", "전장에 진입할 수 없던 문제를 수정했습니다."),
            ("li", "일부 효과가 적에게 표시되지 않던 문제를 수정했습니다."),
        ]),
        "mode-separated": sample("일반 모드·스타디움 독립 분류와 판별 필요", [
            ("h4", "영웅 업데이트"), ("h4", "돌격"), ("h5", "D.Va"),
            ("li", "메카의 기본 생명력이 175에서 200으로 증가했습니다."),
            ("li", "특정 적에게만 새 효과가 적용됩니다. 조건: 2회 적중 후 1.5초 동안."),
            ("h4", "공격"), ("h5", "캐서디"),
            ("li", "공격력이 30에서 28로 감소했습니다."),
            ("li", "재사용 대기시간이 12초에서 10초로 감소했습니다."),
            ("h4", "지원"), ("h5", "아나"),
            ("li", "치유량이 70에서 75로 증가했습니다."),
            ("h4", "스타디움 업데이트"), ("h4", "돌격"), ("h5", "D.Va"),
            ("li", "메카의 기본 생명력이 200에서 175로 감소했습니다."),
            ("h4", "공격"), ("h5", "캐서디"),
            ("li", "공격력이 28에서 30으로 증가했습니다."),
            ("h4", "지원"), ("h5", "아나"),
            ("li", "치유량이 70에서 75로 증가했습니다."),
            ("li", "재사용 대기시간이 10초에서 12초로 증가했습니다."),
            ("li", "대상 선택 규칙이 변경되었습니다. 이미 선택한 대상에는 기존 규칙이 유지됩니다."),
        ]),
        "all-groups": all_groups_sample(),
    }
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/nexon-article.html"
    raw = monitor.parse_nexon_article(fixture.read_text(encoding="utf-8"), "https://overwatch.nexon.com/news/patchnotes/830")
    examples["nexon-fixture"] = monitor.assign_patch_ids([raw])[0]
    fixture_urls = {
        "nexon-july15": "https://overwatch.nexon.com/news/patchnotes/689/patch-2026-07-14",
        "nexon-sept9": "https://overwatch.nexon.com/news/patchnotes/820/patch-2026-09-08",
    }
    for name, source_url in fixture_urls.items():
        fixture = Path(__file__).resolve().parents[1] / f"tests/fixtures/{name}.html"
        raw = monitor.parse_nexon_article(fixture.read_text(encoding="utf-8"), source_url)
        examples[name] = monitor.assign_patch_ids([raw])[0]
    monitor.inherit_explicit_roles(list(examples.values()))
    destination = Path("card-previews")
    manifest = {}
    with patch("requests.sessions.Session.request", side_effect=AssertionError("Preview must stay offline")):
        for name, example in examples.items():
            paths = monitor.generate_summary_cards(example, destination / name)
            entries, general = monitor.prepare_card_data(example)
            pages = summary_cards.plan_cards(entries, general, monitor._find_font_path)
            manifest[name] = {
                "source_url": example.source_url,
                "files": [str(path) for path in paths], "entries": entries, "general": general,
                "font_sizes_px": summary_cards.FONT_SIZES,
                "pages": [
                    {**{key: page[key] for key in ("mode", "category", "role", "number", "count", "height")},
                     "file": str(path), "heroes": [row["hero"] for row in page["rows"]]}
                    for page, path in zip(pages, paths)
                ],
            }
            print(f"Rendered {name}: {len(paths)} cards")
            if name.startswith("nexon-"):
                print("Hero classification: " + ", ".join(f"{entry.get('mode', '')} {entry['hero']}={entry['category']}" for entry in entries))
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
