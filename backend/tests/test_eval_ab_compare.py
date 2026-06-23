from eval.recognition.ab_compare import aggregate_scores


def test_aggregate_averages_per_field_and_composite():
    # 两张图的 per-image field 分数
    per_image = [
        {"type": 1.0, "main_color": 1.0, "thickness": 1.0,
         "sub_type": 1.0, "pattern": 1.0, "season": 1.0, "style_tags": 1.0},
        {"type": 1.0, "main_color": 0.0, "thickness": 1.0,
         "sub_type": 1.0, "pattern": 1.0, "season": 1.0, "style_tags": 1.0},
    ]
    agg = aggregate_scores(per_image)
    assert agg["type"] == 1.0
    assert agg["main_color"] == 0.5
    # composite 为每图 composite 的平均：(1.0 + 0.8) / 2 = 0.9
    assert agg["COMPOSITE"] == 0.9
