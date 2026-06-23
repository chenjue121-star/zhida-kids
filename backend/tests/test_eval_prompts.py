from eval.recognition.prompts import baseline, variant_example
from app.services.recognition.prompt import _recognition_prompt


def test_baseline_matches_production_prompt():
    assert baseline.build_prompt() == _recognition_prompt()


def test_variant_is_nonempty_string_and_differs():
    v = variant_example.build_prompt()
    assert isinstance(v, str) and v.strip()
    assert v != baseline.build_prompt()
