# backend/eval/recognition/labels.py
from __future__ import annotations

from pathlib import Path

import yaml

from app.domain.vocab import (
    CLOTHING_SUB_TYPES,
    CLOTHING_TYPES,
    COLORS,
    PATTERNS,
    SEASONS,
    STYLE_TAGS,
    THICKNESS,
)

REQUIRED_FIELDS = ("type", "main_color", "thickness")

_ALLOWED_SCALAR = {
    "type": set(CLOTHING_TYPES),
    "sub_type": set(CLOTHING_SUB_TYPES) | {""},
    "main_color": set(COLORS),
    "pattern": set(PATTERNS) | {""},
    "thickness": set(THICKNESS),
}
_ALLOWED_SET = {
    "season": set(SEASONS),
    "style_tags": set(STYLE_TAGS),
}


class LabelError(ValueError):
    """标注文件不合法。"""


def load_labels(path: str | Path) -> list[dict]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise LabelError("labels.yaml 顶层必须是列表")

    for i, entry in enumerate(raw):
        where = f"第 {i + 1} 条"
        if not isinstance(entry, dict):
            raise LabelError(f"{where} 不是对象")
        if not entry.get("image"):
            raise LabelError(f"{where} 缺少 image 字段")
        img = entry["image"]
        for f in REQUIRED_FIELDS:
            if not entry.get(f):
                raise LabelError(f"{img} 缺少必填字段 {f}")
        for f, allowed in _ALLOWED_SCALAR.items():
            v = entry.get(f, "")
            if v is None:
                v = ""
            if v not in allowed:
                raise LabelError(f"{img} 字段 {f} 的值 {v!r} 不是合法枚举")
            entry[f] = v
        for f, allowed in _ALLOWED_SET.items():
            vals = entry.get(f, []) or []
            if not isinstance(vals, list):
                raise LabelError(f"{img} 字段 {f} 必须是列表")
            for v in vals:
                if v not in allowed:
                    raise LabelError(f"{img} 字段 {f} 的值 {v!r} 不是合法枚举")
            entry[f] = vals
    return raw
