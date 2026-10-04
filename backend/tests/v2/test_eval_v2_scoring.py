from __future__ import annotations

import importlib
import math

import pytest


def api():
    try:
        scorer = importlib.import_module('eval.recognition_v2.scorer')
        report = importlib.import_module('eval.recognition_v2.report')
    except ModuleNotFoundError:
        pytest.fail('V2 object scorer and report are not implemented yet')
    return scorer.score_image, scorer.aggregate_scores, report.format_report


def truth(identifier='a', bbox=None, **overrides):
    value = {'id': identifier, 'bbox': bbox or [0, 0, .4, .4], 'category': 'top',
             'colors': ['red'], 'pattern': 'solid', 'thickness': None,
             'observable': ['category', 'colors', 'pattern']}
    value.update(overrides)
    return value


def prediction(bbox=None, **overrides):
    value = {'bbox': bbox or [0, 0, .4, .4], 'category': 'top', 'colors': ['red'],
             'pattern': 'solid', 'thickness': 'unknown'}
    value.update(overrides)
    return value


def record(score, *, image='image.jpg', source='live', status='ok', **overrides):
    value = {'image': image, 'group_id': 'group-1', 'scene': 'flat', 'split': 'test',
             'source': source, 'status': status, 'candidates': [prediction()],
             'truths': [truth()], 'elapsed_ms': 1000, 'return_ms': 10,
             'usage': {'input_tokens': 10, 'output_tokens': 5}, 'score': score}
    value.update(overrides)
    return value


def test_missing_garments_remain_in_every_applicable_denominator():
    score_image, _, _ = api()
    result = score_image([prediction()], [truth(), truth('b', [.6, .6, 1, 1])])
    assert result['counts']['tp'] == 1
    assert result['counts']['fn'] == 1
    assert result['recall'] == .5
    assert result['counts']['joint_total'] == 2
    assert result['joint_accuracy'] == .5
    assert result['fields']['category'] == {'correct': 1, 'answered': 1, 'total': 2,
                                           'accuracy': .5, 'coverage': .5}
    assert result['counts']['count_correct'] is False
    assert any(error['type'] == 'missed' for error in result['errors'])


def test_extra_and_duplicate_predictions_are_false_positives():
    score_image, _, _ = api()
    result = score_image([prediction(), prediction(), prediction([.6, .6, 1, 1])], [truth()])
    assert result['counts']['tp'] == 1
    assert result['counts']['fp'] == 2
    assert result['precision'] == pytest.approx(1 / 3)
    assert len(result['matches']) == 1


@pytest.mark.parametrize('bbox', [None, [], [0, 0, 0, 1], [0, 0, 1, 0],
                                   [-.1, 0, .3, .4], [0, 0, 1.1, 1],
                                   [0, 0, 10 ** 400, 1],
                                   [0, 0, math.nan, .4], [False, 0, .4, .4]])
def test_missing_and_invalid_prediction_boxes_are_unlocalized(bbox):
    score_image, _, _ = api()
    candidate = prediction()
    candidate['bbox'] = bbox
    result = score_image([candidate], [truth()])
    assert result['counts']['unlocalized'] == 1
    assert result['counts']['fp'] == result['counts']['fn'] == 1
    assert result['counts']['raw_count_correct'] is True
    assert result['counts']['count_correct'] is False
    assert result['matches'] == []


def test_geometry_matches_even_when_every_semantic_field_is_wrong():
    score_image, _, _ = api()
    result = score_image([prediction(category='dress', colors=['blue'], pattern='plaid')], [truth()])
    assert result['counts']['tp'] == 1
    assert result['counts']['count_correct'] is True
    assert result['counts']['joint_correct'] == 0
    for field in ('category', 'colors', 'pattern'):
        assert result['fields'][field]['answered'] == 1
        assert result['fields'][field]['correct'] == 0
    assert {error['field'] for error in result['errors'] if error['type'] == 'field_wrong'} == {
        'category', 'colors', 'pattern'}


def test_unknown_and_illegal_values_lower_coverage():
    score_image, _, _ = api()
    result = score_image([prediction(category=None, colors=['red', 'unknown'], pattern='cartoon')], [truth()])
    for field in ('category', 'colors', 'pattern'):
        assert result['fields'][field]['answered'] == 0
        assert result['fields'][field]['coverage'] == 0


def test_colors_use_exact_sets_without_order_or_duplicate_penalties():
    score_image, _, _ = api()
    truth_value = truth(colors=['red', 'white'])
    good = score_image([prediction(colors=['white', 'red', 'red'])], [truth_value])
    bad = score_image([prediction(colors=['red'])], [truth_value])
    assert good['fields']['colors']['correct'] == 1
    assert bad['fields']['colors']['correct'] == 0


def test_hidden_thickness_is_not_scored_and_assignment_is_unsupported():
    score_image, _, _ = api()
    result = score_image([prediction(thickness='thick')], [truth()])
    assert result['fields']['thickness']['total'] == 0
    assert result['fields']['thickness']['accuracy'] is None
    assert result['fields']['thickness']['coverage'] is None
    assert result['counts']['unsupported'] == 1
    assert result['counts']['unobservable_total'] == 1
    assert result['joint_accuracy'] == 1
    assert any(error['type'] == 'unsupported' and error['field'] == 'thickness' for error in result['errors'])


def test_unobservable_only_object_cannot_be_vacuously_joint_correct():
    score_image, _, _ = api()
    result = score_image([prediction()], [truth(observable=[])])
    assert result['counts']['joint_correct'] == 0
    assert result['counts']['joint_total'] == 1
    assert result['joint_accuracy'] == 0


def test_failed_request_does_not_score_retained_candidates():
    score_image, _, _ = api()
    result = score_image([prediction()], [truth()], status='provider_error')
    assert result['status'] == 'provider_error'
    assert result['counts']['tp'] == 0
    assert result['counts']['fn'] == 1
    assert result['counts']['count_correct'] is False
    assert result['fields']['category']['total'] == 1
    assert result['fields']['category']['answered'] == 0
    assert result['joint_accuracy'] == 0


def test_successful_empty_negative_has_correct_count_but_no_attribute_accuracy():
    score_image, _, _ = api()
    result = score_image([], [])
    assert result['counts']['count_correct'] is True
    assert result['precision'] is None
    assert result['recall'] is None
    assert result['joint_accuracy'] is None
    assert all(field['accuracy'] is None for field in result['fields'].values())
    assert score_image([], [], status='provider_error')['counts']['count_correct'] is False


def test_matching_maximizes_cardinality_before_iou_instead_of_greedy():
    score_image, _, _ = api()
    truths = [truth('a', [0, 0, .5, 1]), truth('b', [.2, 0, .7, 1])]
    candidates = [prediction([.05, 0, .55, 1]), prediction([0, 0, .3, 1])]
    result = score_image(candidates, truths)
    assert result['counts']['tp'] == 2
    assert {(match['truth_index'], match['prediction_index']) for match in result['matches']} == {(0, 1), (1, 0)}


def test_matching_uses_maximum_total_iou_for_equal_cardinality():
    score_image, _, _ = api()
    truths = [truth('a', [0, 0, .5, 1]), truth('b', [.1, 0, .6, 1])]
    result = score_image([prediction([.1, 0, .6, 1]), prediction([0, 0, .5, 1])], truths)
    assert [(match['truth_index'], match['prediction_index']) for match in result['matches']] == [(0, 1), (1, 0)]
    assert sum(match['iou'] for match in result['matches']) == 2


def test_aggregation_uses_counts_and_includes_failures_and_negatives():
    score_image, aggregate_scores, _ = api()
    results = [score_image([prediction()], [truth()]),
               score_image([], [truth(), truth('b')], status='provider_error'), score_image([], [])]
    aggregate = aggregate_scores(results)
    assert aggregate['images'] == 3
    assert aggregate['counts']['joint_total'] == 3
    assert aggregate['joint_accuracy'] == pytest.approx(1 / 3)
    assert aggregate['fields']['category']['accuracy'] == pytest.approx(1 / 3)
    assert aggregate['count_accuracy'] == pytest.approx(2 / 3)
    assert aggregate['status_counts'] == {'ok': 2, 'provider_error': 1}
    assert aggregate_scores([])['count_accuracy'] is None


def test_report_blocks_accuracy_conclusion_when_offline_cache_is_incomplete():
    score_image, _, format_report = api()
    records = [record(score_image([prediction()], [truth()]), source='cached'),
               record(score_image([], [truth()], status='offline_missing'), image='missing.jpg',
                      source='offline_missing', status='offline_missing')]
    markdown = format_report(records, title='离线报告')
    assert '离线缓存不完整，不能形成准确率结论' in markdown
    assert 'missing.jpg' in markdown
    assert '100.0%' not in markdown
    assert '联合正确率' not in markdown


def test_report_identifies_groups_sources_errors_cache_time_and_usage():
    score_image, _, format_report = api()
    records = [record(score_image([prediction()], [truth()]), source='cached'),
               record(score_image([], [truth()], status='provider_error'), image='failed.jpg',
                      source='live', status='provider_error', candidates=[], elapsed_ms=2000)]
    markdown = format_report(records, title='测试')
    for expected in ('测试', '样本数：2', '独立 group 数：1', 'cached', 'provider_error',
                     '历史模型调用耗时', '本次返回耗时', 'P50', 'P95', 'input_tokens',
                     '20', 'flat', 'top', 'failed.jpg', '漏件', '字段覆盖', '联合正确率'):
        assert expected in markdown
    assert 'live 烟测通过' not in markdown


def test_report_handles_zero_records_without_fabricated_perfect_rates():
    _, _, format_report = api()
    markdown = format_report([], title='空报告')
    assert '样本数：0' in markdown
    assert '无分母' in markdown
    assert '100.0%' not in markdown


def test_report_preserves_the_actual_configured_iou_threshold():
    score_image, _, format_report = api()
    score = score_image([prediction()], [truth()], iou_threshold=.3)
    assert score['iou_threshold'] == .3
    markdown = format_report([record(score)], title='自定义阈值')
    assert 'IoU ≥ 0.3' in markdown
    assert 'IoU ≥ 0.5' not in markdown


@pytest.mark.parametrize('threshold', [0, 1.1, math.nan, math.inf, True, 10 ** 400],
                         ids=['zero', 'above-one', 'nan', 'infinity', 'boolean', 'huge-integer'])
def test_invalid_iou_threshold_is_rejected_consistently(threshold):
    score_image, _, _ = api()
    with pytest.raises(ValueError, match='iou_threshold'):
        score_image([], [], iou_threshold=threshold)


def test_report_ignores_unrepresentable_cache_time_and_usage_numbers():
    score_image, _, format_report = api()
    malformed = record(score_image([prediction()], [truth()]), source='cache',
                       elapsed_ms=10 ** 400, return_ms=10 ** 400, usage={'input_tokens': 10 ** 400})
    markdown = format_report([malformed], title='坏元数据')
    assert '无可用记录' in markdown
    assert str(10 ** 400) not in markdown
