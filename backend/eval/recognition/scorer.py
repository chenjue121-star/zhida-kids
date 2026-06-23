# backend/eval/recognition/scorer.py
from __future__ import annotations

FIELD_WEIGHTS: dict[str, float] = {
    "type": 0.25,
    "main_color": 0.20,
    "thickness": 0.15,
    "sub_type": 0.15,
    "pattern": 0.10,
    "season": 0.10,
    "style_tags": 0.05,
}

EXACT_FIELDS = ("type", "main_color", "thickness", "sub_type", "pattern")
SET_FIELDS = ("season", "style_tags")


def score_exact(predicted: str, expected: str) -> float:
    return 1.0 if (predicted or "") == (expected or "") else 0.0


def score_set(predicted: list[str], expected: list[str]) -> float:
    p, e = set(predicted or []), set(expected or [])
    if not p and not e:
        return 1.0
    if not (p & e):
        return 0.0
    return len(p & e) / len(p | e)


def score_fields(predicted: dict, expected: dict) -> dict[str, float]:
    scores: dict[str, float] = {}
    for f in EXACT_FIELDS:
        scores[f] = score_exact(predicted.get(f, "") or "", expected.get(f, "") or "")
    for f in SET_FIELDS:
        scores[f] = score_set(predicted.get(f, []) or [], expected.get(f, []) or [])
    return scores


def composite(field_scores: dict[str, float]) -> float:
    return round(sum(field_scores[f] * w for f, w in FIELD_WEIGHTS.items()), 4)
