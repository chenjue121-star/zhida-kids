from eval.outfits_v2.report import summarize, blind_review_templates


def test_missing_arms_never_produce_comparative_quality():
    cases = [{'id': 'case1', 'baseline_ids': ['1', '2']}]
    records = [{'case_id': 'case1', 'arm': arm, 'status': 'offline_missing',
                'source': 'offline_missing', 'selection': None, 'chosen_ids': [],
                'usable_ids': [], 'fallback': False, 'usage': {}, 'elapsed_ms': None}
               for arm in ('attributes', 'photos')]
    report = summarize(cases, records, live_calls=0)
    assert report['complete_pairs'] == 0
    assert report['comparison_ready'] is False
    assert report['quality_result'] is None
    assert report['live_calls'] == 0
    assert report['arms']['photos']['statuses'] == {'offline_missing': 1}


def test_equivalent_scenarios_count_once():
    cases = [{'id': 'unknown', 'request_group': 'same', 'baseline_ids': ['1']},
             {'id': 'warm', 'request_group': 'same', 'baseline_ids': ['1']}]
    records = [{'case_id': case['id'], 'arm': arm, 'status': 'ok',
                'selection': {'valid': True}, 'usable_ids': ['1'], 'fallback': False}
               for case in cases for arm in ('attributes', 'photos')]
    report = summarize(cases, records)
    assert report['scenario_count'] == 2
    assert report['independent_input_count'] == 1
    assert report['complete_pairs'] == 1
    assert report['arms']['photos']['valid_model_selections'] == 1


def test_blind_template_hides_source_and_preserves_preference():
    cases = [{'id': 'x', 'styles': {'clean_daily': 1}, 'baseline_ids': ['1']}]
    records = [{'case_id': 'x', 'arm': arm, 'status': 'ok', 'chosen_ids': ids, 'model': 'same'}
               for arm, ids in (('attributes', ['1']), ('photos', ['2']))]
    template, key = blind_review_templates(cases, records)
    assert len(template['pairs']) == 3
    assert all(pair['target_styles'] == {'clean_daily': 1} for pair in template['pairs'])
    assert all(pair['winner'] is None for pair in template['pairs'])
    import json
    rendered = json.dumps(template)
    assert 'attributes' not in rendered and 'photos' not in rendered and 'reason' not in rendered
    assert len(key['pairs']) == 3


def test_actual_model_mismatch_is_not_a_ready_visual_comparison():
    cases = [{'id': 'x', 'styles': {}, 'baseline_ids': ['1']}]
    records = [{'case_id': 'x', 'arm': arm, 'status': 'ok', 'chosen_ids': ['1'],
                'usable_ids': ['1'], 'fallback': False, 'selection': {'valid': True}, 'model': model}
               for arm, model in (('attributes', 'version1'), ('photos', 'version2'))]
    report = summarize(cases, records)
    assert report['model_version_consistent'] is False
    assert report['comparison_ready'] is False
    template, key = blind_review_templates(cases, records)
    primary = next(pair for pair in key['pairs'] if {pair['left_source'], pair['right_source']} == {'attributes', 'photos'})
    assert next(pair for pair in template['pairs'] if pair['pair_id'] == primary['pair_id'])['status'] == 'actual_model_mismatch'


def test_fallback_not_counted_as_model_success_or_human_win():
    cases = [{'id': 'case1', 'baseline_ids': ['1', '2']}]
    records = [{'case_id': 'case1', 'arm': 'attributes', 'status': 'invalid_selection',
                'source': 'live', 'selection': {'valid': False}, 'chosen_ids': ['999'],
                'usable_ids': ['1', '2'], 'fallback': True, 'usage': {}, 'elapsed_ms': 12},
               {'case_id': 'case1', 'arm': 'photos', 'status': 'ok', 'source': 'cache',
                'selection': {'valid': True}, 'chosen_ids': ['1', '2'],
                'usable_ids': ['1', '2'], 'fallback': False, 'usage': {}, 'elapsed_ms': 10}]
    report = summarize(cases, records, live_calls=1)
    assert report['arms']['attributes']['valid_model_selections'] == 0
    assert report['arms']['attributes']['usable_with_fallback'] == 1
    assert report['arms']['photos']['valid_model_selections'] == 1
    assert report['complete_pairs'] == 1
    assert report['quality_result'] is None
