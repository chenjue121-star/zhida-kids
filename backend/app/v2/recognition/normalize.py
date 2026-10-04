import math
from typing import get_args
from app.v2.integrations.recognition import RecognitionFailure
from app.v2.wardrobe.schemas import Category, Color, Pattern, Thickness


def normalize_result(result):
    if not isinstance(result, dict) or not isinstance(result.get('candidates'), list) or not 0 <= len(result['candidates']) <= 30:
        raise RecognitionFailure('MODEL_RESPONSE_INVALID', '未获得可靠衣物候选，请继续手填')
    normalized = []
    for raw in result['candidates']:
        if not isinstance(raw, dict):
            raise RecognitionFailure('MODEL_RESPONSE_INVALID', '识别结果格式有误，请继续手填')
        colors = raw.get('colors')
        colors = list(dict.fromkeys(c for c in colors if c in get_args(Color))) if isinstance(colors, list) else []
        box = raw.get('bbox')
        if not (isinstance(box, list) and len(box) == 4 and all(isinstance(n, (int, float)) and not isinstance(n, bool)
                and math.isfinite(n) and 0 <= n <= 1 for n in box) and box[0] < box[2] and box[1] < box[3]):
            box = None
        name = raw.get('name')
        normalized.append({'name': name[:80].strip() if isinstance(name, str) else '',
            'category': raw.get('category') if raw.get('category') in get_args(Category) else None,
            'colors': colors[:15] or ['unknown'],
            'pattern': raw.get('pattern') if raw.get('pattern') in get_args(Pattern) else 'unknown',
            'thickness': raw.get('thickness') if raw.get('thickness') in get_args(Thickness) else 'unknown',
            'bbox': box})
    return normalized
