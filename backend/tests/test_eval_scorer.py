# backend/tests/test_eval_scorer.py
from eval.recognition.scorer import (
    FIELD_WEIGHTS,
    composite,
    score_exact,
    score_fields,
    score_set,
)


def test_score_exact_match_and_mismatch():
    assert score_exact("top", "top") == 1.0
    assert score_exact("top", "pants") == 0.0


def test_score_exact_both_empty_counts_as_correct_abstention():
    assert score_exact("", "") == 1.0
    assert score_exact("hoodie", "") == 0.0
    assert score_exact("", "hoodie") == 0.0


def test_score_set_jaccard():
    assert score_set(["spring", "autumn"], ["spring", "autumn"]) == 1.0
    assert score_set(["spring"], ["spring", "autumn"]) == 0.5
    assert score_set(["summer"], ["winter"]) == 0.0


def test_score_set_both_empty_is_one():
    assert score_set([], []) == 1.0
    assert score_set(["spring"], []) == 0.0


def test_score_set_is_order_insensitive():
    assert score_set(["autumn", "spring"], ["spring", "autumn"]) == 1.0


def test_weights_sum_to_one():
    assert round(sum(FIELD_WEIGHTS.values()), 6) == 1.0


def test_score_fields_and_composite_perfect():
    predicted = {
        "type": "top", "main_color": "pink", "thickness": "normal",
        "sub_type": "hoodie", "pattern": "stripe",
        "season": ["autumn", "spring"], "style_tags": ["cute", "casual"],
    }
    expected = dict(predicted)
    scores = score_fields(predicted, expected)
    assert all(v == 1.0 for v in scores.values())
    assert composite(scores) == 1.0


def test_composite_partial():
    scores = {
        "type": 1.0, "main_color": 0.0, "thickness": 1.0,
        "sub_type": 1.0, "pattern": 1.0, "season": 1.0, "style_tags": 1.0,
    }
    # 缺失 main_color (权重 0.20) -> composite = 0.80
    assert composite(scores) == 0.8
