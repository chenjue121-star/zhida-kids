from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .config import settings


ALLOWED_TYPES = {
    "top", "pants", "skirt", "outerwear", "shoes", "hat", "accessory", "set", "innerwear", "babywear", "sleepwear",
}
ALLOWED_SUB_TYPES = {
    "tshirt", "shirt", "hoodie", "sweater", "polo", "vest", "jeans", "casual_pants", "shorts", "sweatpants",
    "leggings", "bib_pants", "sock_pants", "short_skirt", "long_skirt", "dress", "tutu", "jacket",
    "down_jacket", "windbreaker", "cardigan", "coat", "cape", "sneakers", "sandals", "boots", "casual_shoes",
    "slippers", "toddler_shoes", "crib_shoes", "cap", "bucket_hat", "beanie", "sun_hat", "scarf", "gloves",
    "bag", "hairband", "socks", "bib", "feeding_bib", "burp_cloth", "blanket", "casual_set", "sport_set",
    "formal_set", "thermal", "undershirt", "onesie", "romper", "bodysuit", "coverall", "swaddle", "pajamas",
    "sleep_sack", "robe",
}
ALLOWED_GARMENT_VALUES = ALLOWED_TYPES | ALLOWED_SUB_TYPES
ALLOWED_COLORS = {
    "white", "black", "gray", "red", "orange", "yellow", "green", "blue", "purple", "pink", "peach", "mint",
    "sky_blue", "lavender", "cream", "beige", "khaki", "brown", "coffee", "navy", "burgundy", "forest_green",
    "charcoal", "denim", "gold", "silver", "neon_green", "multicolor",
}
ALLOWED_PATTERNS = {
    "solid", "stripe", "plaid", "print", "cartoon", "floral", "polka_dot", "animal", "letter", "number",
    "star", "heart", "cloud", "rainbow", "dinosaur", "car", "embroidery", "colorblock", "gradient", "contrast",
    "leopard",
}
ALLOWED_SCENES = {"home", "school", "outdoor", "shopping", "party", "travel"}
ALLOWED_THICKNESS = {"thin", "normal", "thick", "fleece"}
ALLOWED_STYLE_TAGS = {"casual", "sporty", "formal", "cute", "cool", "korean", "japanese", "preppy", "minimalist"}
SCENE_LABELS: dict[str, str] = {
    "home": "日常在家",
    "school": "上学",
    "outdoor": "户外活动",
    "shopping": "外出逛街",
    "party": "聚会派对",
    "travel": "度假出行",
}


def scene_label(scene_key: str) -> str:
    return SCENE_LABELS.get(scene_key, scene_key or "自定义")


class RulesetMeta(BaseModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    locale: str = "zh-CN"
    age_range: List[int] = Field(min_length=2, max_length=2)
    updated_at: str = Field(min_length=1)
    maintainer: str = ""
    source_summary: List[str] = Field(default_factory=list)
    changelog: List[str] = Field(default_factory=list)


class StyleProfile(BaseModel):
    label: str = Field(min_length=1)
    keywords: List[str] = Field(default_factory=list)
    preferred_types: List[str] = Field(default_factory=list)
    preferred_colors: List[str] = Field(default_factory=list)
    preferred_patterns: List[str] = Field(default_factory=list)
    avoid_patterns: List[str] = Field(default_factory=list)
    scenes: List[str] = Field(default_factory=list)
    prompt_hint: str = ""


class ColorPalette(BaseModel):
    label: str = Field(min_length=1)
    colors: List[str] = Field(min_length=1)
    mood: str = ""
    best_scenes: List[str] = Field(default_factory=list)
    score_bonus: int = 0


class SceneRule(BaseModel):
    required_traits: List[str] = Field(default_factory=list)
    prefer_style_tags: List[str] = Field(default_factory=list)
    avoid_types: List[str] = Field(default_factory=list)
    max_visual_focus: int = Field(default=2, ge=0, le=5)


class WeatherRule(BaseModel):
    temp_min: Optional[int] = None
    temp_max: Optional[int] = None
    weather_keywords: List[str] = Field(default_factory=list)
    prefer_thickness: List[str] = Field(default_factory=list)
    avoid_thickness: List[str] = Field(default_factory=list)
    prompt_hint: str = ""


class AgeRule(BaseModel):
    age_min_months: int = Field(ge=0)
    age_max_months: int = Field(ge=0)
    prefer_types: List[str] = Field(default_factory=list)
    avoid_types: List[str] = Field(default_factory=list)
    prompt_hint: str = ""


class ScoringRules(BaseModel):
    weights: Dict[str, int] = Field(default_factory=dict)


class StyleRuleset(BaseModel):
    meta: RulesetMeta
    style_profiles: Dict[str, StyleProfile] = Field(default_factory=dict)
    color_palettes: Dict[str, ColorPalette] = Field(default_factory=dict)
    scene_rules: Dict[str, SceneRule] = Field(default_factory=dict)
    weather_rules: Dict[str, WeatherRule] = Field(default_factory=dict)
    age_rules: Dict[str, AgeRule] = Field(default_factory=dict)
    scoring_rules: ScoringRules = Field(default_factory=ScoringRules)
    prompt_guidelines: List[str] = Field(default_factory=list)
    source_notes: List[str] = Field(default_factory=list)

    @field_validator("style_profiles")
    @classmethod
    def validate_profiles(cls, value: Dict[str, StyleProfile]) -> Dict[str, StyleProfile]:
        for key, profile in value.items():
            _ensure_known(profile.preferred_types, ALLOWED_TYPES, f"style_profiles.{key}.preferred_types")
            _ensure_known(profile.preferred_colors, ALLOWED_COLORS, f"style_profiles.{key}.preferred_colors")
            _ensure_known(profile.preferred_patterns, ALLOWED_PATTERNS, f"style_profiles.{key}.preferred_patterns")
            _ensure_known(profile.avoid_patterns, ALLOWED_PATTERNS, f"style_profiles.{key}.avoid_patterns")
            _ensure_known(profile.scenes, ALLOWED_SCENES, f"style_profiles.{key}.scenes")
        return value

    @field_validator("color_palettes")
    @classmethod
    def validate_palettes(cls, value: Dict[str, ColorPalette]) -> Dict[str, ColorPalette]:
        for key, palette in value.items():
            _ensure_known(palette.colors, ALLOWED_COLORS, f"color_palettes.{key}.colors")
            _ensure_known(palette.best_scenes, ALLOWED_SCENES, f"color_palettes.{key}.best_scenes")
        return value

    @field_validator("scene_rules")
    @classmethod
    def validate_scene_rules(cls, value: Dict[str, SceneRule]) -> Dict[str, SceneRule]:
        _ensure_known(value.keys(), ALLOWED_SCENES, "scene_rules")
        for key, rule in value.items():
            _ensure_known(rule.prefer_style_tags, ALLOWED_STYLE_TAGS, f"scene_rules.{key}.prefer_style_tags")
            _ensure_known(rule.avoid_types, ALLOWED_GARMENT_VALUES, f"scene_rules.{key}.avoid_types")
        return value

    @field_validator("weather_rules")
    @classmethod
    def validate_weather_rules(cls, value: Dict[str, WeatherRule]) -> Dict[str, WeatherRule]:
        for key, rule in value.items():
            _ensure_known(rule.prefer_thickness, ALLOWED_THICKNESS, f"weather_rules.{key}.prefer_thickness")
            _ensure_known(rule.avoid_thickness, ALLOWED_THICKNESS, f"weather_rules.{key}.avoid_thickness")
        return value

    @field_validator("age_rules")
    @classmethod
    def validate_age_rules(cls, value: Dict[str, AgeRule]) -> Dict[str, AgeRule]:
        for key, rule in value.items():
            if rule.age_max_months < rule.age_min_months:
                raise ValueError(f"age_rules.{key}.age_max_months must be >= age_min_months")
            _ensure_known(rule.prefer_types, ALLOWED_TYPES, f"age_rules.{key}.prefer_types")
            _ensure_known(rule.avoid_types, ALLOWED_GARMENT_VALUES, f"age_rules.{key}.avoid_types")
        return value

    @model_validator(mode="after")
    def validate_meta_id(self) -> "StyleRuleset":
        if settings.style_ruleset_id and self.meta.id != settings.style_ruleset_id:
            # Imported or validation-only files may use another id; current loader checks strict id separately.
            return self
        return self


def _ensure_known(values: Any, allowed: set[str], label: str) -> None:
    if values is None:
        return
    if isinstance(values, (list, tuple, set, frozenset)):
        iterable = values
    else:
        # 意外的类型，直接忽略避免 crash；记录 warning 由上游处理
        return
    unknown = sorted({item for item in iterable if item and item not in allowed})
    if unknown:
        raise ValueError(f"{label} contains unknown values: {', '.join(unknown)}")


def resolve_ruleset_path(path_value: Optional[str] = None) -> Path:
    raw = Path(path_value or settings.style_ruleset_path)
    if raw.is_absolute():
        return raw
    cwd_path = Path.cwd() / raw
    if cwd_path.exists():
        return cwd_path
    return Path(__file__).resolve().parents[1] / raw


def parse_ruleset_content(content: bytes, filename: str = "ruleset.yaml") -> StyleRuleset:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".json":
            payload = json.loads(content.decode("utf-8"))
        else:
            payload = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"策略包解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("策略包根节点必须是对象")
    return StyleRuleset.model_validate(payload)


def load_ruleset(path_value: Optional[str] = None, *, strict_id: bool = True) -> StyleRuleset:
    path = resolve_ruleset_path(path_value)
    if not path.exists():
        raise FileNotFoundError(f"策略包不存在: {path}")
    ruleset = parse_ruleset_content(path.read_bytes(), path.name)
    if strict_id and settings.style_ruleset_id and ruleset.meta.id != settings.style_ruleset_id:
        raise ValueError(f"策略包 id 不匹配: expected {settings.style_ruleset_id}, got {ruleset.meta.id}")
    return ruleset


def get_current_ruleset() -> StyleRuleset:
    return load_ruleset(settings.style_ruleset_path, strict_id=True)


def summarize_ruleset(ruleset: StyleRuleset) -> dict[str, Any]:
    return {
        "id": ruleset.meta.id,
        "version": ruleset.meta.version,
        "locale": ruleset.meta.locale,
        "age_range": ruleset.meta.age_range,
        "updated_at": ruleset.meta.updated_at,
        "maintainer": ruleset.meta.maintainer,
        "style_profiles": [
            {"key": key, "label": profile.label, "keywords": profile.keywords, "scenes": profile.scenes}
            for key, profile in ruleset.style_profiles.items()
        ],
        "color_palettes": [
            {"key": key, "label": palette.label, "colors": palette.colors, "best_scenes": palette.best_scenes}
            for key, palette in ruleset.color_palettes.items()
        ],
        "scene_rules": list(ruleset.scene_rules.keys()),
        "weather_rules": list(ruleset.weather_rules.keys()),
        "age_rules": list(ruleset.age_rules.keys()),
        "prompt_guidelines": ruleset.prompt_guidelines,
        "source_summary": ruleset.meta.source_summary,
        "source_notes": ruleset.source_notes,
    }


def safe_import_filename(ruleset: StyleRuleset, original_name: str) -> str:
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".yaml", ".yml", ".json"}:
        suffix = ".yaml"
    base = f"{ruleset.meta.id}_{ruleset.meta.version}"
    base = re.sub(r"[^a-zA-Z0-9_.-]+", "_", base)
    return f"{base}{suffix}"


def validation_error_to_dict(exc: ValidationError) -> dict[str, Any]:
    errors = []
    for item in exc.errors():
        safe_item = dict(item)
        if "ctx" in safe_item:
            safe_item["ctx"] = {key: str(value) for key, value in safe_item["ctx"].items()}
        errors.append(safe_item)
    return {"errors": errors}
