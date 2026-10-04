"""One rule set for suggestions, provider validation, editing and fallback."""
from itertools import product

RULE_VERSION = 'd1'
NEUTRALS = {'black', 'white', 'gray', 'beige', 'brown'}


def identity(item):
    return str(item.get('garment_id', item['id']))


def effective_weather(weather, comfort):
    if weather.get('status') != 'known':
        return None, None
    adjustment = {'runs_cold': -3, 'runs_warm': 3}.get(comfort.get('thermal_preference'), 0)
    return weather['temp_min'] + adjustment, weather['temp_max'] + adjustment


def eligible(item, weather, comfort):
    if item.get('archived_at') or item.get('state') != 'ready' or item.get('fit') != 'fit':
        return False
    if comfort.get('avoid_high_neck') and '高领' in item.get('name', ''):
        return False
    low, high = effective_weather(weather, comfort)
    if high is not None and high >= 28 and item.get('thickness') == 'thick':
        return False
    if low is not None and low >= 22 and high >= 28 and item['category'] == 'outerwear' and item.get('thickness') in ('medium', 'thick'):
        return False
    return True


def required(scene, age_months, weather, comfort):
    low, _ = effective_weather(weather, comfort)
    return {'shoes': scene != 'daily' and age_months >= 12,
            'outerwear': low is not None and low < 15}


def validate_partial(items, scene, age_months, weather, comfort):
    """Check wearable pieces while a parent repairs an unfinished draft."""
    usable = [item for item in items if eligible(item, weather, comfort)]
    return validate(usable, scene, age_months, weather, comfort, incomplete=True)


def validate(items, scene, age_months, weather, comfort, incomplete=False):
    categories = [i['category'] for i in items]
    errors = []
    if not all(eligible(i, weather, comfort) for i in items):
        errors.append({'code': 'GARMENT_UNAVAILABLE', 'message': '单品可用、合身或舒适条件需要核对'})
    complete_body = (categories.count('top') == 1 and categories.count('bottom') == 1 and
            'dress' not in categories and 'onesie' not in categories) or (
                categories.count('dress') + categories.count('onesie') == 1 and
                'top' not in categories and 'bottom' not in categories)
    partial_body = (categories.count('top') <= 1 and categories.count('bottom') <= 1 and
                    categories.count('dress') + categories.count('onesie') <= 1 and
                    not (('dress' in categories or 'onesie' in categories) and
                         ('top' in categories or 'bottom' in categories)))
    body = partial_body if incomplete else complete_body
    if not body or (scene == 'sport' and 'dress' in categories):
        errors.append({'code': 'MISSING_BODY', 'message': '缺少适合本次场景的主体衣物'})
    if len({identity(i) for i in items}) != len(items):
        errors.append({'code': 'DUPLICATE_ITEM', 'message': '主搭配中同一实物只能出现一次'})
    if any(categories.count(c) > 1 for c in ('shoes', 'outerwear')):
        errors.append({'code': 'INCOMPATIBLE_ITEMS', 'message': '同类主体衣物重复，请核对组合'})
    need = required(scene, age_months, weather, comfort)
    for category in ('shoes', 'outerwear'):
        if not incomplete and need[category] and category not in categories:
            errors.append({'code': 'MISSING_' + category.upper(),
                           'message': '本次场景缺少鞋' if category == 'shoes' else '天气偏冷，请补充合适外套'})
    low, _ = effective_weather(weather, comfort)
    thermal = [i for i in items if i['category'] in ('top', 'bottom', 'dress', 'onesie', 'outerwear')]
    complete_layers = complete_body and all(not needed or category in categories for category, needed in need.items())
    if (not incomplete or complete_layers) and low is not None and low < 10 and thermal and all(i.get('thickness') != 'unknown' for i in thermal):
        warmth = {'thin': 1, 'medium': 2, 'thick': 3}
        body_items = [i for i in thermal if i['category'] != 'outerwear']
        body_warmth = min((warmth.get(i.get('thickness'), 0) for i in body_items), default=0)
        layer_warmth = max((warmth.get(i.get('thickness'), 0) for i in thermal if i['category'] == 'outerwear'), default=0)
        if body_warmth + layer_warmth < (5 if low < 0 else 4):
            errors.append({'code': 'INSUFFICIENT_WARMTH', 'message': '当前主体和外套偏薄，请补充适合低温的衣物'})
    styled = [i for i in items if i['category'] in ('top', 'bottom', 'dress', 'onesie', 'outerwear')]
    bright = set().union(*(set(i.get('colors') or []) - NEUTRALS - {'unknown', 'multicolor'} for i in styled))
    prints = [i for i in styled if i.get('pattern') in ('print', 'plaid', 'stripe', 'dots')]
    matching_prints = len({(i.get('pattern'), tuple(sorted(i.get('colors') or []))) for i in prints}) <= 1
    if len(bright) > 3 or (len(prints) > 1 and not matching_prints):
        errors.append({'code': 'COORDINATION_REVIEW_REQUIRED', 'message': '图案或颜色组合过于分散，请核对整套协调'})
    return errors


def score(items, weather, comfort, styles):
    result = 0
    weights = styles if isinstance(styles, dict) else {s: 1 for s in styles}
    colors = set()
    for item in items:
        palette = set(item.get('colors') or []) - {'unknown', 'multicolor'}
        colors |= palette
        pattern = item.get('pattern', 'unknown')
        if 'clean_daily' in styles:
            result += (3 if pattern == 'solid' else 0) * weights['clean_daily']
        if 'playful_print' in styles:
            result += (4 if pattern in ('print', 'dots') else 0) * weights['playful_print']
        if 'soft_natural' in styles:
            result += len(palette & {'white', 'beige', 'brown', 'green'}) * 2 * weights['soft_natural']
        if 'sporty' in styles:
            result += (2 if item['category'] in ('top', 'bottom', 'shoes') else 0) * weights['sporty']
        result += 1 if item.get('thickness') != 'unknown' else 0
    result += 4 if len(colors - NEUTRALS) <= 2 else -len(colors - NEUTRALS)
    return result


def options(garments, scene, age_months, weather, comfort, styles, locked_ids=(), excluded_ids=(),
            occupied_ids=(), exclude_combination=()):
    locked, excluded, occupied = set(map(str, locked_ids)), set(map(str, excluded_ids)), set(map(str, occupied_ids))
    available = [i for i in garments if eligible(i, weather, comfort) and identity(i) not in excluded | occupied]
    groups = {category: [i for i in available if i['category'] == category]
              for category in ('top', 'bottom', 'dress', 'onesie', 'shoes', 'outerwear', 'accessory')}
    bodies = [[top, bottom] for top, bottom in product(groups['top'], groups['bottom'])]
    bodies += [[i] for i in groups['dress'] + groups['onesie'] if scene != 'sport' or i['category'] != 'dress']
    need = required(scene, age_months, weather, comfort)
    result = []
    low, _ = effective_weather(weather, comfort)
    locked_layers = [i for i in groups['outerwear'] if identity(i) in locked]
    if need['outerwear'] or locked_layers:
        layers = locked_layers or groups['outerwear']
    elif low is not None and low < 22:
        layers = [None] + groups['outerwear']
    else:
        layers = [None]
    shoes = groups['shoes'] if need['shoes'] else [None] + groups['shoes']
    accessories = [i for i in groups['accessory'] if identity(i) in locked]
    for body, layer, shoe in product(bodies, layers, shoes):
        combo = body + ([layer] if layer else []) + ([shoe] if shoe else []) + accessories
        identities = {identity(i) for i in combo}
        if not locked <= identities or identities == set(map(str, exclude_combination)):
            continue
        if not validate(combo, scene, age_months, weather, comfort):
            result.append(combo)
    return sorted(result, key=lambda combo: (-score(combo, weather, comfort, styles),
                   len(combo), tuple(int(identity(i)) for i in combo)))[:100]


def generate(garments, scene, age_months, weather, comfort, styles, locked_ids=(), excluded_ids=(),
             occupied_ids=(), exclude_combination=()):
    params = dict(scene=scene, age_months=age_months, weather=weather, comfort=comfort, styles=styles,
                  locked_ids=locked_ids, excluded_ids=excluded_ids, occupied_ids=occupied_ids,
                  exclude_combination=exclude_combination)
    warnings = []
    if weather.get('status') != 'known':
        warnings.append({'code': 'WEATHER_UNKNOWN', 'message': '目标日天气暂未知，请家长核对适宜性'})
    blocked = set(map(str, excluded_ids)) | set(map(str, occupied_ids))
    by_id = {identity(i): i for i in garments}
    for gid in map(str, locked_ids):
        if gid not in by_id or not eligible(by_id[gid], weather, comfort) or gid in blocked:
            return {'items': [], 'missing': [{'code': 'LOCKED_UNAVAILABLE', 'garment_id': gid,
                    'message': '固定单品已失效，请核对或明确解除固定'}], 'warnings': warnings,
                    'reason': '固定单品需要核对，原草稿保持'}
    candidates = options(garments, **params)
    if candidates:
        items = candidates[0]
        if any(i.get('thickness') == 'unknown' for i in items):
            warnings.append({'code': 'THICKNESS_UNKNOWN', 'message': '部分衣物厚薄未知，请核对'})
        return {'items': items, 'missing': [], 'warnings': warnings,
                'reason': '优先合身、可穿和舒适，并按当前偏好协调配色'}
    available = [i for i in garments if eligible(i, weather, comfort) and identity(i) not in blocked]
    group = lambda category: [i for i in available if i['category'] == category]
    onepiece = group('onesie') + ([] if scene == 'sport' else group('dress'))
    probe = onepiece[:1] if onepiece else group('top')[:1] + group('bottom')[:1]
    need = required(scene, age_months, weather, comfort)
    for category in ('outerwear', 'shoes'):
        if need[category]:
            probe += group(category)[:1]
    missing = validate(probe, scene, age_months, weather, comfort)
    if not missing:
        missing = [{'code': 'INCOMPATIBLE_FIXED', 'message': '固定与排除条件下没有合理组合，请核对当前草稿'}]
    problems = set()
    for problem in missing:
        if problem['code'] == 'MISSING_BODY':
            problems.update(('top', 'bottom', 'dress', 'onesie'))
        elif problem['code'] == 'MISSING_SHOES':
            problems.add('shoes')
        elif problem['code'] == 'MISSING_OUTERWEAR':
            problems.add('outerwear')
    for item in garments:
        if item['category'] not in problems or eligible(item, weather, comfort):
            continue
        if item.get('state') in ('washing', 'missing') or item.get('archived_at'):
            missing.append({'code': 'GARMENT_STATE_REVIEW', 'garment_id': identity(item), 'state': item.get('state'),
                            'message': '已有相关衣物当前不可用，请核对衣橱状态'})
        elif item.get('fit') != 'fit':
            missing.append({'code': 'FIT_REVIEW_REQUIRED', 'garment_id': identity(item), 'fit': item.get('fit'),
                            'message': '已有相关衣物合身情况需核对，不能自动视为合身'})
    if any(i.get('fit') == 'unknown' for i in garments):
        missing.append({'code': 'FIT_REVIEW_REQUIRED', 'message': '已有衣物合身未知，请先核对'})
    if exclude_combination and available:
        missing = [{'code': 'NO_ALTERNATIVE', 'message': '没有其他合理组合，当前搭配和固定项保留'}]
    return {'items': [], 'missing': missing, 'warnings': warnings, 'reason': '暂无法组成合理搭配'}
