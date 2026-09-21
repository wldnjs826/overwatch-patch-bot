"""Offline CI previews: illustrative reference data, never Discord delivery."""
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor


def sample(name, items):
    title = f"오버워치 카드 표기 예시 - {name}"
    return monitor.assign_patch_ids([{
        "title": title, "date_key": "형식 예시", "items": items, "images": [],
        "body_hash": monitor.build_body_hash(title, items),
        "source_url": "https://example.com/format-reference", "source_name": "nexon",
    }])[0]


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
    }
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/nexon-article.html"
    raw = monitor.parse_nexon_article(fixture.read_text(encoding="utf-8"), "https://overwatch.nexon.com/news/patchnotes/830")
    examples["nexon-fixture"] = monitor.assign_patch_ids([raw])[0]
    for name in ("nexon-july15", "nexon-sept9"):
        fixture = Path(__file__).resolve().parents[1] / f"tests/fixtures/{name}.html"
        raw = monitor.parse_nexon_article(fixture.read_text(encoding="utf-8"), "https://overwatch.nexon.com/news/patchnotes/")
        examples[name] = monitor.assign_patch_ids([raw])[0]
    destination = Path("card-previews")
    manifest = {}
    with patch("requests.sessions.Session.request", side_effect=AssertionError("Preview must stay offline")):
        for name, example in examples.items():
            paths = monitor.generate_summary_cards(example, destination / name)
            entries, general = monitor.prepare_card_data(example)
            manifest[name] = {"files": [str(path) for path in paths], "entries": entries, "general": general}
            print(f"Rendered {name}: {len(paths)} cards")
            if name.startswith("nexon-"):
                print("Hero classification: " + ", ".join(f"{entry.get('mode', '')} {entry['hero']}={entry['category']}" for entry in entries))
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
