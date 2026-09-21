"""Measured, paginated summary cards built entirely from patch text."""
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH, MAX_HEIGHT = 1050, 1400
MARGIN, TOP, FOOTER = 38, 162, 74
ROLE_WIDTH, HERO_WIDTH = 100, 164
TEXT_X = MARGIN + ROLE_WIDTH + HERO_WIDTH + 45
TEXT_WIDTH = WIDTH - MARGIN - TEXT_X - 24
LINE_HEIGHT, PAD = 38, 18
COLORS = {"buff": "#55C9AD", "nerf": "#F06A91", "adjust": "#F79442", "general": "#5DB6D2", "neutral": "#B7C6CD"}
LABELS = {"buff": "상향", "nerf": "하향", "adjust": "조정", "general": "핵심 요약"}
ARROWS = {"buff": "↑", "nerf": "↓", "adjust": "↔", "general": "•", "neutral": "•"}
ROLE_ORDER = {"돌격": 0, "공격": 1, "지원": 2, "영웅": 3, "일반": 4}


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
        "body": ImageFont.truetype(font_path(False), 27),
        "hero": ImageFont.truetype(font_path(True), 25),
        "role": ImageFont.truetype(font_path(True), 24),
        "title": ImageFont.truetype(font_path(True), 54),
        "meta": ImageFont.truetype(font_path(False), 21),
    }


def plan_cards(entries, general_changes, font_path):
    """Return explicit layout geometry; no rendering or network operations."""
    fonts = _fonts(font_path)
    grouped = OrderedDict((key, []) for key in ("buff", "nerf", "adjust"))
    for entry in entries:
        grouped[entry["category"]].append(entry)
    if not entries and general_changes:
        grouped["general"] = [{"role": "일반", "hero": "주요 변경", "category": "general", "changes": general_changes}]
    pages = []
    for category, group in grouped.items():
        if not group:
            continue
        page = {"category": category, "rows": []}
        cursor = TOP

        def finish():
            nonlocal page, cursor
            if page["rows"]:
                page["height"] = max(380, int(cursor + FOOTER))
                pages.append(page)
            page = {"category": category, "rows": []}
            cursor = TOP

        for entry_index, entry in enumerate(sorted(group, key=lambda e: ROLE_ORDER.get(e["role"], 5))):
            lines = []
            for change_index, change in enumerate(entry["changes"]):
                wrapped = wrap_styled(change["text"], change.get("highlights", []), fonts["body"], TEXT_WIDTH)
                for line_index, line in enumerate(wrapped):
                    lines.append({**line, "category": change["category"], "first": line_index == 0,
                                  "change_index": change_index, "entry_index": entry_index})
            offset = 0
            while offset < len(lines):
                separated = bool(page["rows"] and page["rows"][-1]["role"] != entry["role"])
                gap = 14 if separated else 0
                label = entry["hero"] + (" · 계속" if offset else "")
                badge = wrap_styled(label, [], fonts["hero"], HERO_WIDTH - 18)
                if entry.get("mode") == "스타디움":
                    badge.extend(wrap_styled("스타디움", [], fonts["hero"], HERO_WIDTH - 18))
                minimum = max(116, len(badge) * 30 + 2 * PAD)
                available = MAX_HEIGHT - FOOTER - cursor - gap
                if available < minimum:
                    finish()
                    continue
                take = min(len(lines) - offset, int((available - 2 * PAD) // LINE_HEIGHT))
                height = max(minimum, take * LINE_HEIGHT + 2 * PAD)
                row = {"role": entry["role"], "hero": entry["hero"], "badge": badge,
                       "mode": entry.get("mode", "일반전"),
                       "continued": offset > 0, "top": cursor + gap, "height": height,
                       "lines": lines[offset:offset + take]}
                page["rows"].append(row)
                cursor += gap + height
                offset += take
                if offset < len(lines):
                    finish()
        finish()
    return pages


def _role_icon(draw, role, cx, cy, color):
    draw.ellipse((cx - 24, cy - 24, cx + 24, cy + 24), outline=color, width=2)
    if role == "돌격":
        draw.polygon([(cx - 11, cy - 12), (cx + 11, cy - 12), (cx + 10, cy + 4), (cx, cy + 15), (cx - 10, cy + 4)], fill=color)
    elif role == "지원":
        draw.rectangle((cx - 5, cy - 15, cx + 5, cy + 15), fill=color)
        draw.rectangle((cx - 15, cy - 5, cx + 15, cy + 5), fill=color)
    elif role == "공격":
        for dx in (-10, 0, 10):
            draw.rounded_rectangle((cx + dx - 3, cy - 14, cx + dx + 3, cy + 13), radius=3, fill=color)
    else:
        draw.polygon([(cx, cy - 13), (cx + 13, cy), (cx, cy + 13), (cx - 13, cy)], outline=color, width=2)


def _draw_page(page, date_key, number, count, fonts):
    height = page["height"]
    canvas = Image.new("RGB", (WIDTH, height), "#F3F7F7")
    draw = ImageDraw.Draw(canvas)
    accent = COLORS[page["category"]]
    # Quiet geometric background, built in code instead of downloading images.
    for y in range(130, height, 105):
        for x in range(-50, WIDTH + 60, 120):
            draw.line([(x, y + 30), (x + 30, y), (x + 70, y), (x + 100, y + 30)], fill="#E5ECEC", width=1)
    draw.rectangle((0, 0, WIDTH, 9), fill=accent)
    draw.rounded_rectangle((MARGIN, 53, MARGIN + 70, 123), radius=16, fill=accent)
    draw.text((MARGIN + 35, 88), ARROWS[page["category"]], font=fonts["title"], fill="#172326", anchor="mm")
    draw.text((MARGIN + 91, 50), LABELS[page["category"]], font=fonts["title"], fill="#142226")
    meta = f"{date_key}  ·  오버워치 패치"
    if count > 1:
        meta += f"  ·  {number}/{count}"
    draw.text((WIDTH - MARGIN, 110), meta, font=fonts["meta"], fill="#53636B", anchor="rs")

    groups = []
    for row in page["rows"]:
        if groups and groups[-1][0]["role"] == row["role"]:
            groups[-1].append(row)
        else:
            groups.append([row])
    for group in groups:
        top = group[0]["top"]
        bottom = group[-1]["top"] + group[-1]["height"]
        draw.rounded_rectangle((MARGIN, top, WIDTH - MARGIN, bottom), radius=13, fill="#2C3C45")
        cx, cy = MARGIN + ROLE_WIDTH / 2, (top + bottom) / 2 - 14
        _role_icon(draw, group[0]["role"], cx, cy, "#E4F1F2")
        draw.text((cx, cy + 31), group[0]["role"], font=fonts["role"], fill="#E4F1F2", anchor="mt")
        for row_index, row in enumerate(group):
            y = row["top"] + PAD
            badge_x = MARGIN + ROLE_WIDTH + 10
            badge_height = len(row["badge"]) * 30 + 10
            draw.rounded_rectangle((badge_x, y, badge_x + HERO_WIDTH, y + badge_height), radius=4, fill=accent)
            for index, line in enumerate(row["badge"]):
                draw.text((badge_x + HERO_WIDTH / 2, y + 5 + index * 30), line["text"], font=fonts["hero"], fill="#15282D", anchor="mt")
            for index, line in enumerate(row["lines"]):
                color = COLORS.get(line["category"], COLORS["adjust"])
                if line["first"] or index == 0:
                    draw.text((TEXT_X - 27, y), ARROWS.get(line["category"], "↔"), font=fonts["body"], fill=color, anchor="lt")
                x = TEXT_X
                for text, emphasized in line["runs"]:
                    draw.text((x, y), text, font=fonts["body"], fill=color if emphasized else "#F4F7F8", anchor="lt")
                    x += fonts["body"].getlength(text)
                y += LINE_HEIGHT
            if row_index < len(group) - 1:
                draw.line((badge_x, row["top"] + row["height"] - 1, WIDTH - MARGIN - 20, row["top"] + row["height"] - 1), fill="#3E4C54", width=1)
    draw.text((WIDTH / 2, height - 27), "OVERWATCH  ·  자동 요약", font=fonts["meta"], fill="#5C6D73", anchor="mm")
    return canvas


def render_cards(*, patch_id, title, date_key, entries, general_changes, output_dir, font_path):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pages = plan_cards(entries, general_changes, font_path)
    fonts = _fonts(font_path)
    totals = {category: sum(p["category"] == category for p in pages) for category in LABELS}
    seen, paths = {}, []
    for page in pages:
        category = page["category"]
        seen[category] = seen.get(category, 0) + 1
        canvas = _draw_page(page, date_key, seen[category], totals[category], fonts)
        path = output_dir / f"{patch_id.replace('#', '-')}-summary-{category}-{seen[category]}.png"
        canvas.save(path)
        paths.append(path)
    return paths
