"""Large, measured cards with one mode, change type and role per page."""
from collections import Counter, defaultdict
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont


WIDTH, MAX_HEIGHT = 1050, 1400
MARGIN, TOP, FOOTER = 38, 264, 76
PAD, HERO_LINE_HEIGHT, HERO_BODY_GAP = 28, 54, 16
LINE_HEIGHT, CHANGE_GAP, HERO_GAP = 52, 12, 22
ARROW_WIDTH = 42
TEXT_X = MARGIN + PAD + ARROW_WIDTH
TEXT_WIDTH = WIDTH - MARGIN - PAD - TEXT_X
HERO_WIDTH = WIDTH - 2 * (MARGIN + PAD)
FONT_SIZES = {"body": 36, "hero": 38, "role": 40, "title": 64, "meta": 25}
COLORS = {
    "buff": "#55C9AD", "nerf": "#F06A91", "adjust": "#F79442",
    "review": "#F2D477", "general": "#5DB6D2", "neutral": "#B7C6CD",
}
LABELS = {
    "buff": "상향", "nerf": "하향", "adjust": "조정",
    "review": "판별 필요", "general": "핵심 요약", "neutral": "기타 변경",
}
ARROWS = {"buff": "↑", "nerf": "↓", "adjust": "↔", "review": "?", "general": "•", "neutral": "•"}
ROLE_ORDER = {"돌격": 0, "공격": 1, "지원": 2, "영웅": 3, "일반": 4}
MODE_ORDER = {"일반전": 0, "스타디움": 1}
CATEGORY_ORDER = {"buff": 0, "nerf": 1, "adjust": 2, "review": 3, "neutral": 4, "general": 5}


def wrap_styled(text, spans, font, width):
    """Wrap by measured width while retaining highlight offsets and all words."""
    lines = []
    start = 0
    while start < len(text):
        while start < len(text) and text[start].isspace():
            start += 1
        if start == len(text):
            break
        end, space = start, -1
        while end < len(text) and font.getlength(text[start:end + 1]) <= width:
            if text[end].isspace():
                space = end
            end += 1
        if end == start:
            raise ValueError("Card text area is narrower than a character")
        if end < len(text) and space > start + (end - start) // 3:
            end = space
        visible_end = end
        while visible_end > start and text[visible_end - 1].isspace():
            visible_end -= 1
        runs = []
        for index in range(start, visible_end):
            emphasized = any(a <= index < b for a, b in spans)
            if runs and runs[-1][1] == emphasized:
                runs[-1] = (runs[-1][0] + text[index], emphasized)
            else:
                runs.append((text[index], emphasized))
        lines.append({"text": text[start:visible_end], "runs": runs})
        start = end
    return lines


def _fonts(font_path):
    return {
        name: ImageFont.truetype(font_path(name in {"hero", "role", "title"}), size)
        for name, size in FONT_SIZES.items()
    }


def _group_key(entry):
    category = entry["category"]
    if category not in CATEGORY_ORDER:
        raise ValueError(f"Unknown card category: {category}")
    return entry.get("mode", "일반전"), category, entry.get("role", "영웅")


def _group_order(key):
    mode, category, role = key
    # Unclassified material is an explicit appendix after BOTH game modes.
    appendix = 0 if category in {"buff", "nerf", "adjust"} else CATEGORY_ORDER[category] - 2
    return (appendix, MODE_ORDER.get(mode, 2), CATEGORY_ORDER[category],
            ROLE_ORDER.get(role, 5), mode, role)


def _role_label(role):
    if role in {"돌격", "공격", "지원"}:
        return role
    return "일반 변경" if role == "일반" else "역할 확인 필요"


def plan_cards(entries, general_changes, font_path):
    """Lay out full-width hero panels, with immutable fonts and strict groups."""
    fonts = _fonts(font_path)
    groups = defaultdict(list)
    for entry_index, entry in enumerate(entries):
        groups[_group_key(entry)].append((entry_index, entry))
    if not entries and general_changes:
        groups[("일반전", "general", "일반")].append((0, {
            "hero": "주요 변경", "changes": general_changes,
        }))
    pages = []
    for key in sorted(groups, key=_group_order):
        mode, category, role = key
        page = {"mode": mode, "category": category, "role": role, "rows": []}
        cursor = TOP

        def finish():
            nonlocal page, cursor
            if page["rows"]:
                page["height"] = int(cursor + FOOTER)
                pages.append(page)
            page = {"mode": mode, "category": category, "role": role, "rows": []}
            cursor = TOP

        for entry_index, entry in groups[key]:
            lines = []
            for change_index, change in enumerate(entry["changes"]):
                wrapped = wrap_styled(change["text"], change.get("highlights", []), fonts["body"], TEXT_WIDTH)
                for line_index, line in enumerate(wrapped):
                    lines.append({**line, "category": change.get("category", category),
                                  "first": line_index == 0, "change_index": change_index,
                                  "entry_index": entry_index})
            offset = 0
            while offset < len(lines):
                gap = HERO_GAP if page["rows"] else 0
                label = entry["hero"] + (" · 계속" if offset else "")
                badge = wrap_styled(label, [], fonts["hero"], HERO_WIDTH)
                heading_height = len(badge) * HERO_LINE_HEIGHT + HERO_BODY_GAP
                base_height = 2 * PAD + heading_height
                available = MAX_HEIGHT - FOOTER - cursor - gap
                if available < base_height + LINE_HEIGHT:
                    if not page["rows"]:
                        raise ValueError("Hero name leaves no room for a patch line")
                    finish()
                    continue
                selected, used_height = [], base_height
                for line in lines[offset:]:
                    before = CHANGE_GAP if selected and line["first"] else 0
                    if used_height + before + LINE_HEIGHT > available:
                        break
                    selected.append({**line, "gap_before": before})
                    used_height += before + LINE_HEIGHT
                top = cursor + gap
                row = {"mode": mode, "category": category, "role": role,
                       "hero": entry["hero"], "badge": badge, "continued": offset > 0,
                       "top": top, "height": used_height,
                       "body_top": top + PAD + heading_height, "lines": selected}
                page["rows"].append(row)
                cursor = top + used_height
                offset += len(selected)
                if offset < len(lines):
                    finish()
        finish()
    totals = Counter((page["mode"], page["category"], page["role"]) for page in pages)
    seen = Counter()
    for page in pages:
        key = (page["mode"], page["category"], page["role"])
        seen[key] += 1
        page["number"], page["count"] = seen[key], totals[key]
    return pages


def _draw_page(page, date_key, number, count, fonts):
    height = page["height"]
    canvas = Image.new("RGB", (WIDTH, height), "#F3F7F7")
    draw = ImageDraw.Draw(canvas)
    accent = COLORS[page["category"]]
    draw.rectangle((0, 0, WIDTH, 10), fill=accent)
    mode_label = "일반 모드" if page["mode"] == "일반전" else page["mode"]
    draw.text((MARGIN, 34), mode_label, font=fonts["meta"], fill="#405760", anchor="lt")
    draw.text((WIDTH - MARGIN, 34), str(date_key), font=fonts["meta"], fill="#53636B", anchor="rt")
    draw.rounded_rectangle((MARGIN, 85, MARGIN + 76, 161), radius=16, fill=accent)
    draw.text((MARGIN + 38, 122), ARROWS[page["category"]], font=fonts["title"], fill="#172326", anchor="mm")
    draw.text((MARGIN + 100, 85), LABELS[page["category"]], font=fonts["title"], fill="#142226", anchor="lt")
    draw.text((MARGIN, 189), _role_label(page["role"]), font=fonts["role"], fill="#263F48", anchor="lt")
    draw.text((WIDTH - MARGIN, 199), f"{number} / {count}", font=fonts["meta"], fill="#53636B", anchor="rt")

    for row in page["rows"]:
        top, bottom = row["top"], row["top"] + row["height"]
        draw.rounded_rectangle((MARGIN, top, WIDTH - MARGIN, bottom), radius=16, fill="#2C3C45")
        for index, line in enumerate(row["badge"]):
            draw.text((MARGIN + PAD, top + PAD + index * HERO_LINE_HEIGHT), line["text"],
                      font=fonts["hero"], fill=accent, anchor="lt")
        divider_y = row["body_top"] - HERO_BODY_GAP
        draw.line((MARGIN + PAD, divider_y, WIDTH - MARGIN - PAD, divider_y), fill="#51636D", width=2)
        y = row["body_top"]
        for index, line in enumerate(row["lines"]):
            y += line["gap_before"]
            color = COLORS.get(line["category"], COLORS["review"])
            if line["first"] or index == 0:
                draw.text((MARGIN + PAD, y), ARROWS.get(line["category"], "?"),
                          font=fonts["body"], fill=color, anchor="lt")
            x = TEXT_X
            for text, emphasized in line["runs"]:
                draw.text((x, y), text, font=fonts["body"],
                          fill=color if emphasized else "#F4F7F8", anchor="lt")
                x += fonts["body"].getlength(text)
            y += LINE_HEIGHT
    footer = "OVERWATCH  ·  원문 기반 요약"
    if page["category"] == "review":
        footer = "판별 필요  ·  상향 / 하향을 확정하지 않은 항목"
    draw.text((WIDTH / 2, height - 35), footer, font=fonts["meta"], fill="#53666E", anchor="mm")
    return canvas


def _filename_part(value):
    return re.sub(r"[^\w.-]+", "-", str(value), flags=re.UNICODE).strip("-.") or "unknown"


def render_cards(*, patch_id, title, date_key, entries, general_changes, output_dir, font_path):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pages = plan_cards(entries, general_changes, font_path)
    fonts = _fonts(font_path)
    paths = []
    for page in pages:
        canvas = _draw_page(page, date_key, page["number"], page["count"], fonts)
        # Include every grouping dimension and a global index to prevent collisions
        # even if external labels normalize to the same filesystem-safe spelling.
        parts = [patch_id, "summary", page["mode"], page["category"], page["role"], page["number"], len(paths) + 1]
        path = output_dir / ("-".join(_filename_part(part) for part in parts) + ".png")
        canvas.save(path)
        paths.append(path)
    return paths
