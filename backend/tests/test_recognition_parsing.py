import pytest
from fastapi import HTTPException

from app.services.recognition.parsing import _extract_json, _pick_recognition_object
from app.services.recognition.normalize import _normalize_recognition


def test_extract_json_plain_object():
    assert _extract_json('{"type": "top"}') == {"type": "top"}


def test_extract_json_strips_markdown_fence():
    text = '```json\n{"type": "pants", "main_color": "navy"}\n```'
    assert _extract_json(text) == {"type": "pants", "main_color": "navy"}


def test_extract_json_finds_object_in_prose():
    text = '识别结果如下：{"type": "shoes"} 仅供参考'
    assert _extract_json(text) == {"type": "shoes"}


def test_extract_json_array():
    assert _extract_json('[{"type": "top"}, {"type": "pants"}]') == [
        {"type": "top"}, {"type": "pants"}
    ]


def test_extract_json_empty_raises_502():
    with pytest.raises(HTTPException) as exc:
        _extract_json("   ")
    assert exc.value.status_code == 502


def test_extract_json_no_json_raises_502():
    with pytest.raises(HTTPException) as exc:
        _extract_json("这里没有任何 JSON")
    assert exc.value.status_code == 502


def test_pick_recognition_object_unwraps_result_key():
    parsed = {"result": {"type": "top", "main_color": "white"}}
    assert _pick_recognition_object(parsed) == {"type": "top", "main_color": "white"}


def test_pick_recognition_object_picks_most_complete_from_list():
    parsed = [
        {"type": "top"},
        {"type": "pants", "main_color": "navy", "confidence": 0.9},
    ]
    picked = _pick_recognition_object(parsed)
    assert picked["type"] == "pants"
    assert "识别到多件衣物" in picked["notes"]


def test_normalize_recognition_maps_chinese_aliases():
    out = _normalize_recognition({
        "type": "上衣", "main_color": "白色", "pattern": "条纹",
        "thickness": "薄", "season": "夏季", "style_tags": ["休闲"],
    })
    assert out.type == "top"
    assert out.main_color == "white"
    assert out.pattern == "stripe"
    assert out.thickness == "thin"
    assert out.season == ["summer"]
    assert out.style_tags == ["casual"]
