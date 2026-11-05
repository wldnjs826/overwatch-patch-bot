"""Compare delivered source text, independently of card layout/classifier versions."""
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import re


def _clean(text):
    return re.sub(r"\s+", " ", text).strip()


def source_atoms(lines, role_from_heading, hero_roles):
    """Read the bot's lossless Markdown source format, including legacy messages."""
    mode, role, hero, ability, section = "일반전", "일반", "주요 변경", "", ""
    atoms = []
    explicit_role = False
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("### "):
            hero, ability = line[4:], ""
            if not explicit_role:
                role = hero_roles.get(hero, "영웅")
            continue
        if line.startswith("## "):
            heading = _clean(line[3:])
            found_role = role_from_heading(heading)
            if found_role:
                role, hero, ability = found_role, "주요 변경", ""
                explicit_role = True
                continue
            if "스타디움" in heading or "stadium" in heading.lower():
                mode = "스타디움"
            elif heading in {"일반", "일반 업데이트", "영웅 업데이트", "버그 수정"}:
                mode = "일반전"
            section, role, hero, ability = heading, "일반", "주요 변경", ""
            explicit_role = False
            continue
        if line.startswith("**") and line.endswith("**"):
            ability = _clean(line[2:-2])
            continue
        text = _clean(line[2:] if line.startswith("- ") else line)
        if hero != "주요 변경" and re.search(r"[-–].*(?:특전|파워|아이템)$", text):
            ability = text
            continue
        atoms.append({"mode": mode, "role": role, "hero": hero,
                      "ability": ability, "section": section, "text": text})
    return atoms


def _identity(atom):
    return tuple(atom[key] for key in ("mode", "role", "hero", "ability", "section", "text"))


def _display(atom):
    prefix = atom["ability"] or (atom["section"] if atom["hero"] == "주요 변경" else "")
    return f"{prefix}: {atom['text']}" if prefix else atom["text"]


def _ability_root(atom):
    return re.sub(r"\s*[-–]\s*(?:주요|보조) 특전$", "", atom["ability"])


def changed_entries(before, after, *, classify, role_from_heading, hero_roles):
    """Return only added/edited/deleted statements; reordering alone is silent."""
    old = source_atoms(before, role_from_heading, hero_roles)
    new = source_atoms(after, role_from_heading, hero_roles)
    old_counts, new_counts = Counter(map(_identity, old)), Counter(map(_identity, new))
    removed, added = [], []
    for atom in old:
        key = _identity(atom)
        if new_counts[key]:
            new_counts[key] -= 1
        else:
            removed.append(atom)
    for atom in new:
        key = _identity(atom)
        if old_counts[key]:
            old_counts[key] -= 1
        else:
            added.append(atom)

    rows = []
    for atom in added:
        # Pair corrections only within one hero/mode/role; unrelated additions
        # and removals retain explicit labels rather than inventing a relation.
        candidates = [(SequenceMatcher(None, _display(prior), _display(atom)).ratio(), i)
                      for i, prior in enumerate(removed)
                      if all(prior[k] == atom[k] for k in ("mode", "role", "hero"))
                      and _ability_root(prior) == _ability_root(atom)]
        score, index = max(candidates, default=(0, -1))
        previous = removed.pop(index) if score >= 0.55 else None
        text = _display(atom)
        category = classify(text, hero=atom["hero"], mode=atom["mode"])
        if atom["hero"] == "주요 변경":
            category = "review"
        shown = (f"[수정] {text}\n이전 표기: {_display(previous)}" if previous
                 else f"[추가] {text}")
        rows.append((atom, category, shown))
    for atom in removed:
        # Deleting a patch-note sentence is not evidence of an in-game nerf.
        rows.append((atom, "review", f"[원문에서 삭제] {_display(atom)}"))

    grouped = defaultdict(list)
    for atom, category, text in rows:
        group = (atom["mode"], atom["role"], atom["hero"])
        grouped[group].append({"text": text, "highlights": [], "category": category})
    entries = []
    for (mode, role, hero), changes in grouped.items():
        known = [row for row in changes if row["category"] != "review"]
        unknown = [row for row in changes if row["category"] == "review"]
        if known:
            types = {row["category"] for row in known} - {"neutral"}
            category = ("adjust" if "adjust" in types or {"buff", "nerf"} <= types
                        else next(iter(types)) if types else "neutral")
            entries.append({"mode": mode, "role": role, "hero": hero,
                            "category": category, "changes": known})
        if unknown:
            entries.append({"mode": mode, "role": role, "hero": hero,
                            "category": "review", "changes": unknown})
    return entries
