"""Frozen display-pool validation and the production categorical payload."""
from __future__ import annotations

import json
import math
import re
from typing import get_args

from app.v2.outfits import rules
from app.v2.outfits.schemas import Scene
from app.v2.wardrobe.schemas import Category, Color, Pattern, Thickness, State, Fit

FIELDS = ('garment_id', 'category', 'colors', 'pattern', 'thickness')
INVALID_SELECTION_CODES = frozenset({'INVALID_JSON', 'INVALID_RESULT', 'MISSING_IDS', 'INVALID_IDS',
                                    'DUPLICATE_IDS', 'UNKNOWN_IDS', 'OUTSIDE_DISPLAY_POOL',
                                    'INCOMPLETE_COMBINATION', 'NOT_DISPLAYED_COMBINATION'})


def garment_id(value) -> str:
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', value) or int(value) > 9223372036854775807:
        raise ValueError('garment IDs must be positive numeric identifiers')
    return value


def _ids(values) -> list[str]:
    if not isinstance(values, list):
        raise ValueError('ID collections must be lists')
    result = [garment_id(value) for value in values]
    if len(set(result)) != len(result):
        raise ValueError('duplicate garment ID')
    return result


def indexed_garments(case) -> dict:
    result = {}
    if not isinstance(case.get('garments'), list):
        raise ValueError('garments must be a list')
    for item in case['garments']:
        if not isinstance(item, dict):
            raise ValueError('garments must contain objects')
        gid = garment_id(item.get('garment_id', item.get('id')))
        if 'id' in item and garment_id(item['id']) != gid:
            raise ValueError('id and garment_id disagree')
        if gid in result:
            raise ValueError('duplicate inventory ID')
        result[gid] = item
    return result


def validate_case(case: dict) -> dict:
    """Validate without mutating the case; null thickness must be adapted upstream."""
    if not isinstance(case, dict) or not isinstance(case.get('id'), str) or not case['id'].strip():
        raise ValueError('case requires an id')
    if case.get('scene') not in get_args(Scene):
        raise ValueError('unsupported scene')
    if type(case.get('age_months')) is not int or case['age_months'] < 0:
        raise ValueError('age_months must be a nonnegative integer')
    for field in ('styles', 'weather', 'comfort', 'photos'):
        if not isinstance(case.get(field), dict):
            raise ValueError(field + ' must be an object')
    styles = case['styles']
    if any(key not in ('clean_daily', 'playful_print', 'soft_natural', 'sporty') or
           type(value) not in (int, float) or not -1 <= value <= 1 or not math.isfinite(value)
           for key, value in styles.items()):
        raise ValueError('invalid style weights')
    weather = case['weather']
    if weather.get('status') not in ('unknown', 'known'):
        raise ValueError('invalid weather status')
    if weather['status'] == 'known':
        low, high = weather.get('temp_min'), weather.get('temp_max')
        if any(type(value) not in (int, float) or not -100 <= value <= 100 for value in (low, high)) or low > high:
            raise ValueError('invalid weather temperatures')
    inventory = indexed_garments(case)
    for item in inventory.values():
        if item.get('category') not in get_args(Category) or item.get('pattern') not in get_args(Pattern) or \
                item.get('thickness') not in get_args(Thickness):
            raise ValueError('garment attributes must use V2 enums; thickness cannot be null')
        colors = item.get('colors')
        if not isinstance(colors, list) or not colors or any(color not in get_args(Color) for color in colors):
            raise ValueError('invalid colors')
        if item.get('state') not in get_args(State) or item.get('fit') not in get_args(Fit):
            raise ValueError('invalid garment state or fit')
    constraints = {name: set(_ids(case.get(name, []))) for name in ('locked_ids', 'excluded_ids', 'occupied_ids')}
    if any(not ids <= inventory.keys() for ids in constraints.values()):
        raise ValueError('constraint references an unknown garment')
    combinations = case.get('combinations')
    if not isinstance(combinations, list) or len(combinations) > 20:
        raise ValueError('display pool must contain at most 20 combinations')
    seen = set()
    for combination in combinations:
        ids = _ids(combination)
        identities = frozenset(ids)
        if not identities or not identities <= inventory.keys() or identities in seen:
            raise ValueError('display combination is empty, duplicated or references unknown inventory')
        seen.add(identities)
        if not constraints['locked_ids'] <= identities or identities & (constraints['excluded_ids'] | constraints['occupied_ids']):
            raise ValueError('display pool violates locked, excluded or occupied constraints')
        # Only existing rule fields participate. Descriptive text is never model input.
        items = [{**inventory[gid], 'id': gid, 'garment_id': gid} for gid in ids]
        if rules.validate(items, case['scene'], case['age_months'], weather, case['comfort']):
            raise ValueError('display combination violates production rules')
    baseline = frozenset(_ids(case.get('baseline_ids', [])))
    if (combinations and baseline not in seen) or (not combinations and baseline):
        raise ValueError('baseline must be an exact displayed combination, or empty for no candidates')
    return case


def safe_payload(case: dict) -> dict:
    """Mirror production's five categorical fields; never expose product prose."""
    inventory = indexed_garments(case)
    combinations = []
    for combination in case['combinations'][:20]:
        items = []
        for raw_id in combination:
            gid = garment_id(raw_id)
            item = inventory[gid]
            items.append({'garment_id': gid, 'category': item.get('category'),
                          'colors': list(item.get('colors') or ['unknown']),
                          'pattern': item.get('pattern') or 'unknown',
                          'thickness': item.get('thickness') or 'unknown'})
        combinations.append(items)
    return {'scene': case['scene'], 'styles': dict(case['styles']), 'combinations': combinations}


def reject_constant(value):
    raise ValueError('non-finite JSON number')


def validate_selection(case: dict, result) -> dict:
    validate_case(case)
    selection = {'valid': False, 'code': 'INVALID_RESULT', 'garment_ids': [], 'combination_index': None}
    if isinstance(result, str):
        try:
            result = json.loads(result, parse_constant=reject_constant)
        except (ValueError, TypeError):
            return {**selection, 'code': 'INVALID_JSON'}
    if not isinstance(result, dict):
        return selection
    if 'garment_ids' not in result:
        return {**selection, 'code': 'MISSING_IDS'}
    raw_ids = result['garment_ids']
    if not isinstance(raw_ids, list):
        return {**selection, 'code': 'INVALID_IDS'}
    try:
        ids = [garment_id(gid) for gid in raw_ids]
    except ValueError:
        return {**selection, 'code': 'INVALID_IDS'}
    selection['garment_ids'] = ids
    if len(ids) != len(set(ids)):
        return {**selection, 'code': 'DUPLICATE_IDS'}
    chosen = set(ids)
    if not chosen <= indexed_garments(case).keys():
        return {**selection, 'code': 'UNKNOWN_IDS'}
    pool = [{garment_id(gid) for gid in combo} for combo in case['combinations']]
    displayed = set().union(*pool) if pool else set()
    if not chosen <= displayed:
        return {**selection, 'code': 'OUTSIDE_DISPLAY_POOL'}
    for index, combination in enumerate(pool):
        if chosen == combination:
            return {'valid': True, 'code': 'OK',
                    'garment_ids': [garment_id(gid) for gid in case['combinations'][index]], 'combination_index': index}
    return {**selection, 'code': 'INCOMPLETE_COMBINATION' if any(chosen < combo for combo in pool)
            else 'NOT_DISPLAYED_COMBINATION'}
