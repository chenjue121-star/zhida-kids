from __future__ import annotations

from eval.recognition.scorer import FIELD_WEIGHTS

_ROW_ORDER = list(FIELD_WEIGHTS.keys()) + ["COMPOSITE"]


def _fmt_delta(d: float) -> str:
    return f"{d:+.2f}"


def format_comparison(
    baseline_name: str,
    variant_name: str,
    baseline: dict[str, float],
    variant: dict[str, float],
    image_count: int,
) -> str:
    lines = [
        f"# 识别 A/B 对比报告",
        "",
        f"图片数: {image_count}",
        "",
        f"| Field | {baseline_name} | {variant_name} | Δ |",
        "| --- | --- | --- | --- |",
    ]
    for field in _ROW_ORDER:
        b = baseline.get(field, 0.0)
        v = variant.get(field, 0.0)
        lines.append(f"| {field} | {b:.2f} | {v:.2f} | {_fmt_delta(v - b)} |")
    return "\n".join(lines)
