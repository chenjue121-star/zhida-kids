# backend/tests/test_eval_labels.py
import textwrap

import pytest

from eval.recognition.labels import LabelError, load_labels


def _write(tmp_path, text):
    p = tmp_path / "labels.yaml"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


def test_load_valid_labels(tmp_path):
    p = _write(tmp_path, """
        - image: img001.jpg
          type: top
          sub_type: hoodie
          main_color: pink
          pattern: stripe
          season: [autumn, spring]
          thickness: normal
          style_tags: [cute, casual]
    """)
    labels = load_labels(p)
    assert len(labels) == 1
    assert labels[0]["image"] == "img001.jpg"
    assert labels[0]["season"] == ["autumn", "spring"]


def test_missing_required_field_raises(tmp_path):
    p = _write(tmp_path, """
        - image: img001.jpg
          type: top
          main_color: pink
    """)  # 缺 thickness
    with pytest.raises(LabelError, match="thickness"):
        load_labels(p)


def test_unknown_enum_value_raises(tmp_path):
    p = _write(tmp_path, """
        - image: img001.jpg
          type: tops
          main_color: pink
          thickness: normal
    """)  # type 应为 top
    with pytest.raises(LabelError, match="tops"):
        load_labels(p)


def test_unknown_set_value_raises(tmp_path):
    p = _write(tmp_path, """
        - image: img001.jpg
          type: top
          main_color: pink
          thickness: normal
          season: [autum]
    """)  # autum 拼错
    with pytest.raises(LabelError, match="autum"):
        load_labels(p)


def test_missing_image_key_raises(tmp_path):
    p = _write(tmp_path, """
        - type: top
          main_color: pink
          thickness: normal
    """)
    with pytest.raises(LabelError, match="image"):
        load_labels(p)


def test_empty_optional_fields_ok(tmp_path):
    p = _write(tmp_path, """
        - image: img001.jpg
          type: top
          main_color: pink
          thickness: normal
          sub_type: ""
          pattern: ""
          season: []
          style_tags: []
    """)
    labels = load_labels(p)
    assert labels[0]["sub_type"] == ""
    assert labels[0]["season"] == []
