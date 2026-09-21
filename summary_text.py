"""Conservative Korean patch-note notation; never invent missing values."""
import re


NUMBER = r"-?\d+(?:,\d{3})*(?:\.\d+)?"
UNIT = r"(?:%p|퍼센트포인트|퍼센트|%|밀리초|초|미터/초|미터|m/s|m|회|발|배)"
ENDING = r"(?:했습니다|하였습니다|되었습니다|됩니다|합니다|했으며|하였으며|되었으며|하며|하고|했고)"
PAIR = re.compile(
    rf"(?P<a>{NUMBER})\s*(?P<au>{UNIT})?\s*에서\s*"
    rf"(?P<b>{NUMBER})\s*(?P<bu>{UNIT})?\s*(?:으)?로\s*"
    rf"(?:증가|감소|변경|조정|확대|축소)(?P<end>{ENDING})(?=$|\s|[.,;:!?()])"
)
DELTA = re.compile(
    rf"(?<![\w.,+\-−])(?P<n>{NUMBER})\s*(?P<u>{UNIT})?\s*(?:만큼\s*)?"
    rf"(?P<verb>증가|감소)(?P<end>{ENDING})(?=$|\s|[.,;:!?()])"
)
FIELDS = (
    "처치 불가 생명력 한계치", "재사용 대기시간", "재사용 대기 시간", "기본 생명력",
    "방어력", "공격력", "생명력", "내구도", "탄환당 피해", "피해", "치유량", "회복량",
    "궁극기 비용", "시전 시간", "지속 시간", "지연 시간", "회복 시간", "추가 속도",
    "투사체 속도", "이동 속도", "연료 소모 속도", "연료 소모량", "분산도", "사거리",
    "시각 효과", "탄약", "탄창", "투척 사거리 증가량", "발사 속도", "범위",
)
FIELD_PATTERN = "|".join(re.escape(x) for x in sorted(FIELDS, key=len, reverse=True))


def _joiner(ending: str) -> str:
    return ", " if ending.endswith(("며", "고")) else ""


def compact_change(text: str) -> dict:
    value = re.sub(r"\s+", " ", text).strip()
    value = re.sub(
        r"^(.+?)\s*-\s*(주요|보조)\s*특전\s*:\s*",
        lambda m: f"[{m[2]} 특전] {m[1].strip()} ", value,
    )
    value = re.sub(r"^(주요|보조) 특전\s+", r"[\1 특전] ", value)
    value = value.replace(": ", " ", 1)

    def pair(match):
        a_unit, b_unit = match["au"] or "", match["bu"] or ""
        # A unit on only one endpoint also describes the other endpoint.
        if not a_unit:
            a_unit = b_unit
        if not b_unit:
            b_unit = a_unit
        return f"{match['a']}{a_unit} → {match['b']}{b_unit}" + _joiner(match["end"])

    value = PAIR.sub(pair, value)

    def delta(match):
        # Signed input with prose direction can be ambiguous; keep it verbatim.
        if match["n"].startswith("-"):
            return match[0]
        sign = "+" if match["verb"] == "증가" else "-"
        return f"{sign}{match['n']}{match['u'] or ''}" + _joiner(match["end"])

    value = DELTA.sub(delta, value)
    value = re.sub(rf"({FIELD_PATTERN})(?:이|가|은|는)(?=\s)", r"\1", value)
    # Remove possessive endings only in front of a known metric, not inside names.
    value = re.sub(rf"의\s+(?=(?:{FIELD_PATTERN})(?:\s|이|가|은|는))", " ", value)
    value = re.sub(r"(?P<v>증가|감소|추가|제거|삭제|확대|축소|변경|활성화|비활성화)"
                   rf"(?:되었습니다|했습니다|됩니다|합니다)(?=\.|$|\s*\()", r"\g<v>", value)
    value = re.sub(r",\s*,", ",", value)
    value = re.sub(r"\.(?=\s*\(|$)", "", value)
    value = re.sub(r"\s+", " ", value).strip(" ,")

    spans = []
    for match in re.finditer(rf"→\s*(?P<value>{NUMBER}(?:{UNIT})?)", value):
        spans.append(list(match.span("value")))
    for match in re.finditer(rf"(?<![\w.])[-+]\d+(?:,\d{{3}})*(?:\.\d+)?(?:{UNIT})?", value):
        if not any(start <= match.start() < end for start, end in spans):
            spans.append(list(match.span()))
    if not spans:
        match = re.search(r"(?:시각 효과\s+)?(?:증가|감소|추가|제거|삭제|활성화|비활성화)(?=\s*(?:\([^)]*\))?$)", value)
        if match:
            spans.append(list(match.span()))
    return {"text": value, "highlights": sorted(spans)}
