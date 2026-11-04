"""Offline ability context for metrics whose benefit cannot be inferred alone.

These rules describe benefit directions, not particular before/after values.
They are scoped by mode, hero and ability so a shared phrase such as 'duration'
cannot transfer a rule to an unrelated effect. Unknown effects remain unknown.

Source: official patch text and developer comments, retrieved 2026-11-05:
https://overwatch.nexon.com/news/patchnotes/858/patch-2026-11-03
"""
import re


# 1: a higher value benefits this hero; -1: a lower value benefits this hero.
ABILITY_METRICS = {
    ("일반전", "겐지", "튕겨내기"): {"지속시간": 1},
    ("일반전", "엠레", "사이버 파편 수류탄"): {"폭발시간": -1},
    ("일반전", "벤데타", "팔라틴 팽"): {"내리치기도약속도": 1},
    ("일반전", "제트팩 캣", "정신 없는 비행"): {"가속도": 1},
    ("일반전", "솜브라", "긴급 패치"): {"지속시간": 1},
    ("일반전", "솜브라", "사이버 스페이스"): {"약화효과": 1},
    ("스타디움", "벤데타", "마구잡이 맹공격 - 파워"): {
        "맹공의중첩증가에필요한처치횟수": -1,
    },
}


def classify_ability_metric(*, hero, mode, ability, metric, direction):
    """Return a category for an exact supported metric, or None for no rule."""
    rules = ABILITY_METRICS.get((mode, hero, ability), {})
    compact_metric = re.sub(r"\s+", "", metric)
    for name, benefit_direction in rules.items():
        # Reject extra qualifiers: cost, reduction amount and enemy effects
        # must not be mistaken for the base metric.
        if re.fullmatch(re.escape(name) + r"(?:이|가|은|는)?(?:초당)?", compact_metric):
            if direction == 0:
                return "review"
            return "buff" if direction == benefit_direction else "nerf"
    return None
