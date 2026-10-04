import importlib.util


def rules():
    assert importlib.util.find_spec('app.v2.outfits') is not None, 'C outfits rule module is missing'
    from app.v2.outfits import rules
    return rules


def item(identifier, category, **changes):
    return {'id': str(identifier), 'garment_id': str(identifier), 'category': category,
            'fit': 'fit', 'state': 'ready', 'archived_at': None, 'thickness': 'medium',
            'pattern': 'solid', 'colors': ['blue'], **changes}


def generate(items, **changes):
    return rules().generate(items, scene='daily', age_months=24,
        weather={'status': 'unknown'}, comfort={}, styles=[], **changes)


def test_daily_dress_and_baby_onesie_are_complete_without_fixed_three_items():
    assert generate([item(1, 'dress')])['items']
    result = rules().generate([item(1, 'onesie')], scene='outdoor', age_months=6,
                              weather={'status': 'unknown'}, comfort={}, styles=[])
    assert result['items']
    assert not generate([item(1, 'top')])['items']


def test_unknown_fit_excluded_and_unavailable_locked_kept_as_missing_reason():
    assert not generate([item(1, 'top', fit='unknown'), item(2, 'bottom')])['items']
    result = generate([item(1, 'top', state='washing'), item(2, 'bottom'), item(3, 'top')], locked_ids=['1'])
    assert result['items'] == [] and result['missing'][0]['code'] == 'LOCKED_UNAVAILABLE'


def test_switch_excludes_exact_combo_and_preserves_locked_identity():
    items = [item(1, 'top'), item(2, 'bottom'), item(3, 'top'), item(4, 'bottom')]
    first = generate(items, locked_ids=['1'])
    ids = [i['garment_id'] for i in first['items']]
    second = generate(items, locked_ids=['1'], exclude_combination=ids)
    assert '1' in [i['garment_id'] for i in second['items']]
    assert sorted(ids) != sorted(i['garment_id'] for i in second['items'])


def test_outdoor_walking_child_needs_shoes_sport_avoids_dress_and_cold_requires_layer():
    r = rules()
    result = r.generate([item(1, 'dress')], scene='outdoor', age_months=24,
                        weather={'status': 'unknown'}, comfort={}, styles=[])
    assert not result['items'] and any(m['code'] == 'MISSING_SHOES' for m in result['missing'])
    result = r.generate([item(1, 'dress'), item(2, 'shoes')], scene='sport', age_months=24,
                        weather={'status': 'unknown'}, comfort={}, styles=[])
    assert not result['items']
    cold = r.generate([item(1, 'top'), item(2, 'bottom')], scene='daily', age_months=24,
                       weather={'status': 'known', 'temp_min': 4, 'temp_max': 8}, comfort={}, styles=[])
    assert not cold['items'] and any(m['code'] == 'MISSING_OUTERWEAR' for m in cold['missing'])


def test_style_ranking_cannot_override_shared_comfort_or_occupancy():
    items = [item(1, 'top', thickness='thick', pattern='print'), item(2, 'top', thickness='thin'),
             item(3, 'bottom', thickness='thin')]
    r = rules()
    result = r.generate(items, scene='daily', age_months=24,
                        weather={'status': 'known', 'temp_min': 28, 'temp_max': 33},
                        comfort={'thermal_preference': 'runs_warm'}, styles=['playful_print'])
    assert '1' not in [i['garment_id'] for i in result['items']]
    assert not generate(items, occupied_ids=['1', '2'])['items']


def test_hot_day_does_not_add_optional_layers_for_style_points():
    result = rules().generate([item(1, 'top'), item(2, 'bottom'), item(3, 'outerwear')],
        scene='outdoor', age_months=6, weather={'status': 'known', 'temp_min': 31, 'temp_max': 36},
        comfort={}, styles=['clean_daily'])
    assert result['items'] and 'outerwear' not in [i['category'] for i in result['items']]


def test_unavailable_or_small_existing_items_are_distinguished_from_absent_items():
    for attributes, expected in [({'state': 'washing'}, 'GARMENT_STATE_REVIEW'),
                                 ({'fit': 'small'}, 'FIT_REVIEW_REQUIRED')]:
        result = generate([item(1, 'top'), item(2, 'bottom', **attributes)])
        assert any(m['code'] == expected and m['garment_id'] == '2' for m in result['missing'])


def test_partial_adjustment_can_leave_cold_layers_pending_while_final_review_stays_strict():
    r = rules()
    weather = {'status': 'known', 'temp_min': 4, 'temp_max': 8}
    body = [item(1, 'top', thickness='thin'), item(2, 'bottom', thickness='thin')]
    assert not r.validate_partial(body, 'daily', 24, weather, {})
    assert any(e['code'] == 'MISSING_OUTERWEAR' for e in r.validate(body, 'daily', 24, weather, {}))
    complete = body + [item(3, 'outerwear', thickness='thin')]
    assert any(e['code'] == 'INSUFFICIENT_WARMTH' for e in r.validate_partial(complete, 'daily', 24, weather, {}))


def test_unfinished_adjustment_still_rejects_incompatible_structure_scene_and_patterns():
    r = rules()
    cases = [[item(1, 'top'), item(2, 'top')], [item(1, 'top'), item(2, 'dress')],
             [item(1, 'top', pattern='plaid'), item(2, 'bottom', pattern='print')]]
    for combination in cases:
        assert r.validate_partial(combination, 'daily', 24, {'status': 'unknown'}, {})
    assert r.validate_partial([item(1, 'dress')], 'sport', 24, {'status': 'unknown'}, {})
