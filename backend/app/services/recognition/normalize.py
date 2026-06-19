from typing import Any

from ...domain.vocab import (
    CLOTHING_TYPES, CLOTHING_SUB_TYPES, COLORS, PATTERNS, SEASONS, THICKNESS,
    STYLE_TAGS, RECOGNITION_FIELD_SCORE_META,
    _TYPE_ALIAS, _COLOR_ALIAS, _PATTERN_ALIAS, _THICKNESS_ALIAS,
    _SEASON_ALIAS, _STYLE_ALIAS,
)
from ...schemas import ClothingRecognizeOut


def _mock_recognition() -> ClothingRecognizeOut:
    return ClothingRecognizeOut(
        type="accessory",
        sub_type="bib",
        main_color="cream",
        pattern="cartoon",
        season=["all"],
        thickness="normal",
        style_tags=["cute"],
        confidence=0.72,
        notes="开发 mock：请根据实物确认字段。",
    )


def _normalize_recognition(data: dict) -> ClothingRecognizeOut:
    def pick(value: Any, allowed: list[str], alias_map: dict[str, str], default: str) -> str:
        if value is None:
            return default
        if not isinstance(value, str):
            value = str(value)
        v = value.strip()
        if not v:
            return default
        lowered = v.lower()
        # 1. 精确匹配枚举（大小写不敏感）
        for a in allowed:
            if a.lower() == lowered:
                return a
        # 2. 别名精确匹配（中文）
        if v in alias_map:
            return alias_map[v]
        alias_lowered = {k.lower(): val for k, val in alias_map.items()}
        if lowered in alias_lowered:
            return alias_lowered[lowered]
        # 3. 包含匹配（如 "红色 条纹" -> red；"春秋季" -> spring+autumn 特殊处理交给 pick_list）
        for cn_key, en_val in alias_map.items():
            if cn_key and cn_key in v:
                return en_val
        return default

    def pick_list(value: Any, allowed: list[str], alias_map: dict[str, str]) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_tokens = [t.strip() for t in value.replace("，", ",").replace("、", ",").split(",") if t.strip()]
        elif isinstance(value, list):
            raw_tokens = [str(t).strip() for t in value if isinstance(t, (str, int)) and str(t).strip()]
        else:
            return []
        # 对每个原始 token，若包含特殊组合（如 "春秋"），拆成多个小 token
        tokens: list[str] = []
        for t in raw_tokens:
            # 处理常见中文组合词
            splits: list[str] = []
            if "春秋" in t and ("夏" not in t) and ("冬" not in t):
                splits.append(t.replace("春秋", "春"))
                splits.append(t.replace("春秋", "秋"))
            elif "春夏" in t and ("秋" not in t):
                splits.append(t.replace("春夏", "春"))
                splits.append(t.replace("春夏", "夏"))
            elif "夏秋" in t and ("冬" not in t):
                splits.append(t.replace("夏秋", "夏"))
                splits.append(t.replace("夏秋", "秋"))
            elif "秋冬" in t:
                splits.append(t.replace("秋冬", "秋"))
                splits.append(t.replace("秋冬", "冬"))
            elif "春夏秋" in t or "春秋夏" in t:
                splits.append("春")
                splits.append("夏")
                splits.append("秋")
            else:
                splits.append(t)
            tokens.extend(splits)

        result: list[str] = []
        alias_lk = {k.lower(): val for k, val in alias_map.items()}
        for token in tokens:
            if not token:
                continue
            lowered = token.lower()
            found = None
            # 1. 精确匹配枚举
            for a in allowed:
                if a.lower() == lowered:
                    found = a
                    break
            # 2. 别名精确匹配（中文 key）
            if not found and token in alias_map:
                found = alias_map[token]
            # 3. 别名小写匹配
            if not found and lowered in alias_lk:
                found = alias_lk[lowered]
            # 4. 包含匹配（如 "夏季" -> summer；"适合春天" -> spring）
            if not found:
                for cn_key, en_val in alias_map.items():
                    if cn_key and cn_key in token:
                        found = en_val
                        break
            if found and found not in result:
                result.append(found)
        return result

    result = ClothingRecognizeOut(
        type=pick(data.get("type"), CLOTHING_TYPES, _TYPE_ALIAS, "top"),
        sub_type=pick(data.get("sub_type"), CLOTHING_SUB_TYPES, _TYPE_ALIAS, ""),
        main_color=pick(data.get("main_color"), COLORS, _COLOR_ALIAS, "white"),
        pattern=pick(data.get("pattern"), PATTERNS, _PATTERN_ALIAS, ""),
        season=pick_list(data.get("season"), SEASONS, _SEASON_ALIAS),
        thickness=pick(data.get("thickness"), THICKNESS, _THICKNESS_ALIAS, "normal"),
        style_tags=pick_list(data.get("style_tags"), STYLE_TAGS, _STYLE_ALIAS),
        brand=str(data.get("brand") or "")[:120],
        size=str(data.get("size") or "")[:60],
        confidence=max(0.0, min(1.0, float(data.get("confidence") or 0))),
        notes=str(data.get("notes") or "")[:500],
    )

    # 根据字段完整性重新计算综合置信度
    filled_score = 0.0
    max_score = 0.0
    if result.type and result.type in CLOTHING_TYPES:
        filled_score += RECOGNITION_FIELD_SCORE_META["type"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["type"]["weight"]
    if result.main_color and result.main_color in COLORS:
        filled_score += RECOGNITION_FIELD_SCORE_META["main_color"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["main_color"]["weight"]
    if result.thickness and result.thickness in THICKNESS:
        filled_score += RECOGNITION_FIELD_SCORE_META["thickness"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["thickness"]["weight"]
    if result.pattern and result.pattern in PATTERNS:
        filled_score += RECOGNITION_FIELD_SCORE_META["pattern"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["pattern"]["weight"]
    if result.style_tags:
        filled_score += RECOGNITION_FIELD_SCORE_META["style_tags"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["style_tags"]["weight"]
    if result.season:
        filled_score += RECOGNITION_FIELD_SCORE_META["season"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["season"]["weight"]
    if result.sub_type and result.sub_type in CLOTHING_SUB_TYPES:
        filled_score += RECOGNITION_FIELD_SCORE_META["sub_type"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["sub_type"]["weight"]

    ai_conf = float(data.get("confidence") or 0) if data.get("confidence") else 0.75
    completeness = filled_score / max_score if max_score else 0.0
    result.confidence = round(max(0.0, min(1.0, ai_conf * 0.55 + completeness * 0.45)), 2)
    if not result.notes and completeness < 0.6:
        result.notes = "本次识别部分字段需要人工确认，请检查类别、颜色与厚度。"
    return result
