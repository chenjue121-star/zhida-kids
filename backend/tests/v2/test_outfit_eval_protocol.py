from copy import deepcopy
import importlib

import pytest


def api():
    try:
        return importlib.import_module('eval.outfits_v2.protocol')
    except ModuleNotFoundError:
        pytest.fail('Outfit evaluation protocol is not implemented')


def case():
    def item(gid, category):
        return {'id': gid, 'garment_id': gid, 'category': category, 'colors': ['white'],
                'pattern': 'solid', 'thickness': 'unknown', 'state': 'ready', 'fit': 'fit',
                'name': 'must-not-leak', 'description': 'private product text', 'score': 99}
    return {'id': 'daily-1', 'scene': 'daily', 'styles': {'clean_daily': 1},
            'weather': {'status': 'unknown'}, 'comfort': {}, 'age_months': 36,
            'garments': [item('1', 'top'), item('2', 'bottom'), item('3', 'dress'), item('4', 'accessory')],
            'combinations': [['1', '2'], ['3']], 'baseline_ids': ['1', '2'], 'photos': {},
            'locked_ids': [], 'excluded_ids': [], 'occupied_ids': []}


def test_payload_matches_production_safe_fields_and_excludes_extra_context():
    value = case()
    value['garments'][0]['thickness'] = None
    safe = api().safe_payload(value)
    assert set(safe) == {'scene', 'styles', 'combinations'}
    assert safe['combinations'][0][0] == {'garment_id': '1', 'category': 'top', 'colors': ['white'],
                                         'pattern': 'solid', 'thickness': 'unknown'}
    assert 'must-not-leak' not in str(safe)
    assert 'weather' not in safe and 'age_months' not in safe
    assert value['garments'][0]['thickness'] is None


def test_selection_must_match_one_displayed_combination_even_with_reordered_ids():
    result = api().validate_selection(case(), {'garment_ids': ['2', '1'], 'reason': 'private reason'})
    assert result == {'valid': True, 'code': 'OK', 'garment_ids': ['1', '2'], 'combination_index': 0}
    assert api().validate_selection(case(), '{"garment_ids":["3"]}')['valid']


@pytest.mark.parametrize('result,code', [
    ('not json', 'INVALID_JSON'), ({}, 'MISSING_IDS'), ({'garment_ids': ['1', '1']}, 'DUPLICATE_IDS'),
    ({'garment_ids': ['999']}, 'UNKNOWN_IDS'), ({'garment_ids': ['4']}, 'OUTSIDE_DISPLAY_POOL'),
    ({'garment_ids': ['1']}, 'INCOMPLETE_COMBINATION'),
    ({'garment_ids': ['1', '3']}, 'NOT_DISPLAYED_COMBINATION'),
    ({'garment_ids': [True]}, 'INVALID_IDS'),
])
def test_illegal_selection_has_an_explicit_safe_code(result, code):
    selection = api().validate_selection(case(), result)
    assert selection['valid'] is False and selection['code'] == code


def test_baseline_can_remain_frozen_when_display_order_changes():
    value = case()
    value['combinations'].reverse()
    original = deepcopy(value)
    assert api().validate_case(value) == value
    assert value == original and value['baseline_ids'] == ['1', '2']


@pytest.mark.parametrize('change', ['null_thickness', 'unknown_reference', 'duplicate_item', 'duplicate_combo',
                                    'over_twenty', 'incomplete_body', 'bad_baseline', 'excluded', 'occupied', 'locked'])
def test_case_rejects_unfrozen_or_rule_invalid_combinations(change):
    value = case()
    if change == 'null_thickness':
        value['garments'][0]['thickness'] = None
    elif change == 'unknown_reference':
        value['combinations'][0].append('999')
    elif change == 'duplicate_item':
        value['combinations'][0].append('1')
    elif change == 'duplicate_combo':
        value['combinations'].append(['2', '1'])
    elif change == 'over_twenty':
        value['combinations'] *= 11
    elif change == 'incomplete_body':
        value['combinations'][0] = ['1']
    elif change == 'bad_baseline':
        value['baseline_ids'] = ['4']
    elif change in ('excluded', 'occupied'):
        value[change + '_ids'] = ['1']
    else:
        value['locked_ids'] = ['1']
    with pytest.raises(ValueError):
        api().validate_case(value)


def test_empty_rule_boundary_case_is_valid_and_has_no_baseline():
    value = case()
    value.update(combinations=[], baseline_ids=[], locked_ids=['1'], excluded_ids=['1'])
    assert api().validate_case(value) == value


@pytest.mark.parametrize('scene', ['outdoor', 'formal'])
def test_case_uses_actual_production_scenes(scene):
    value = case()
    value['scene'] = scene
    value['garments'][3]['category'] = 'shoes'
    value.update(combinations=[['3', '4']], baseline_ids=['3', '4'])
    assert api().validate_case(value) == value


def test_negative_inferred_preference_is_preserved_in_the_payload():
    value = case()
    value['styles'] = {'clean_daily': 1, 'playful_print': -.5}
    assert api().validate_case(value) == value
    assert api().safe_payload(value)['styles']['playful_print'] == -.5


@pytest.mark.parametrize('weight', [-1.1, 1.1, 2])
def test_style_weights_outside_production_effective_range_are_rejected(weight):
    value = case()
    value['styles'] = {'clean_daily': weight}
    with pytest.raises(ValueError, match='style'):
        api().validate_case(value)
