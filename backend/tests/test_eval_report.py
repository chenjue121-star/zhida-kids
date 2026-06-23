from eval.recognition.report import format_comparison


def test_format_comparison_has_header_and_composite_and_delta():
    baseline = {
        "type": 1.0, "main_color": 0.8, "thickness": 0.6,
        "sub_type": 1.0, "pattern": 1.0, "season": 1.0, "style_tags": 1.0,
        "COMPOSITE": 0.88,
    }
    variant = {
        "type": 1.0, "main_color": 0.9, "thickness": 0.75,
        "sub_type": 1.0, "pattern": 1.0, "season": 1.0, "style_tags": 1.0,
        "COMPOSITE": 0.9275,
    }
    out = format_comparison("baseline", "variant_x", baseline, variant, image_count=20)
    assert "baseline" in out
    assert "variant_x" in out
    assert "COMPOSITE" in out
    assert "main_color" in out
    assert "+0.10" in out      # main_color delta
    assert "图片数: 20" in out
