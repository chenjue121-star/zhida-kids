import copy
import hashlib
import importlib
import json
import math
from pathlib import Path

import pytest
from PIL import Image


def api():
    try:
        return importlib.import_module('eval.recognition_v2.crop_pilot')
    except ModuleNotFoundError:
        pytest.fail('independent crop attribute pilot is not implemented yet')


def write_json(path, document):
    path.write_text(json.dumps(document), encoding='utf-8')


def inputs(tmp_path):
    images = tmp_path / 'prepared'
    (images / 'images').mkdir(parents=True)
    items, photos = [], {}
    for number in range(1, 76):
        gid = str(number)
        item = {'id': gid, 'source_image': f'source-{number % 47}.jpg',
                'source_sha256': f'{number:064x}', 'bbox': [.1, .2, .9, .9],
                'category': 'top', 'colors': ['blue', 'white'], 'pattern': 'stripe',
                'thickness': None, 'group_id': 'one-source', 'split': 'development'}
        items.append(item)
        if number <= 16:
            path = images / 'images' / f'{gid}.jpg'
            Image.new('RGB', (20, 24), (number * 10, 20, 30)).save(path)
            photos[gid] = {'path': f'images/{gid}.jpg',
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'source_image': item['source_image'], 'source_sha256': item['source_sha256'],
                           'bbox': item['bbox'], 'width': 20, 'height': 24}
    confirmation = tmp_path / 'confirmation.json'
    inventory = tmp_path / 'garments.json'
    frozen = tmp_path / 'cases.json'
    write_json(confirmation, {'schema_version': 1, 'kind': 'user_main_product_dataset_confirmation',
                             'confirmation_method': 'single_user_overall_confirmation_of_ai_assisted_main_product_annotations',
                             'confirmed_by': 'user_in_current_chat', 'reviewer_count': 1,
                             'independent_dual_review': False, 'source_image_count': 47,
                             'inventory_object_count': 75, 'inventory_file': inventory.name,
                             'source_annotations_sha256': 'a' * 64,
                             'is_full_screenshot_end_to_end_recognition_ground_truth': False})
    write_json(inventory, {'schema_version': 1, 'kind': 'confirmed_main_product_inventory',
                          'confirmation_record': confirmation.name,
                          'source_annotations_sha256': 'a' * 64, 'items': items})
    write_json(frozen, {'schema_version': 1, 'kind': 'frozen_outfit_development_comparison',
                       'inventory_sha256': hashlib.sha256(inventory.read_bytes()).hexdigest(),
                       'inventory_objects': 75, 'pilot_objects': 16,
                       'visual_review': 'codex_checked', 'photos': photos})
    return inventory, frozen, images, confirmation


def derive(paths):
    inventory, frozen, images, confirmation = paths
    return api().derive_crop_pilot(inventory, frozen, images, confirmation_path=confirmation)


def truth():
    return {'category': 'top', 'colors': ['blue', 'white'], 'pattern': 'stripe', 'thickness': None}


def prediction(**changes):
    value = {'category': 'top', 'colors': ['white', 'blue'], 'pattern': 'stripe',
             'thickness': 'thick', 'bbox': [.9, .9, 1, 1]}
    value.update(changes)
    return value


def test_derivation_uses_all_frozen_crops_and_records_overall_confirmation(tmp_path):
    paths = inputs(tmp_path)
    before = {path: path.read_bytes() for path in (paths[0], paths[1], paths[3])}
    pilot = derive(paths)
    assert len(pilot['entries']) == 16
    assert pilot['scored_fields'] == ['category', 'colors', 'pattern']
    assert pilot['unscored_fields'] == ['thickness']
    assert pilot['split'] == 'development'
    provenance = pilot['provenance']
    assert provenance['inventory_object_count'] == 75
    assert provenance['source_image_count'] == 47
    assert provenance['reviewer_count'] == 1
    assert provenance['independent_dual_review'] is False
    assert provenance['is_full_screenshot_end_to_end_recognition_ground_truth'] is False
    assert provenance['confirmation_method'].startswith('single_user_overall_confirmation')
    assert provenance['confirmation_sha256'] == hashlib.sha256(paths[3].read_bytes()).hexdigest()
    assert len({entry['garment_id'] for entry in pilot['entries']}) == 16
    for entry in pilot['entries']:
        assert entry['sha256'] == hashlib.sha256((paths[2] / entry['image']).read_bytes()).hexdigest()
        assert entry['truth'] == truth()
        assert 'bbox' not in entry['truth']
    assert all(path.read_bytes() == content for path, content in before.items())


def test_derivation_refuses_changed_image_and_inventory(tmp_path):
    paths = inputs(tmp_path)
    (paths[2] / 'images/1.jpg').write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash'):
        derive(paths)
    paths = inputs(tmp_path / 'second')
    document = json.loads(paths[0].read_text())
    document['items'][0]['pattern'] = 'solid'
    write_json(paths[0], document)
    with pytest.raises(ValueError, match='inventory.*hash'):
        derive(paths)


def test_derivation_refuses_missing_annotation_hash_even_when_both_inputs_omit_it(tmp_path):
    paths = inputs(tmp_path)
    for path in (paths[0], paths[3]):
        document = json.loads(path.read_text())
        document.pop('source_annotations_sha256')
        write_json(path, document)
    frozen = json.loads(paths[1].read_text())
    frozen['inventory_sha256'] = hashlib.sha256(paths[0].read_bytes()).hexdigest()
    write_json(paths[1], frozen)
    with pytest.raises(ValueError, match='provenance'):
        derive(paths)


@pytest.mark.parametrize('field,value', [('category', None), ('colors', ['unknown']), ('pattern', 'unknown')])
def test_derivation_requires_known_attribute_truth(tmp_path, field, value):
    paths = inputs(tmp_path)
    document = json.loads(paths[0].read_text())
    document['items'][0][field] = value
    write_json(paths[0], document)
    frozen = json.loads(paths[1].read_text())
    frozen['inventory_sha256'] = hashlib.sha256(paths[0].read_bytes()).hexdigest()
    write_json(paths[1], frozen)
    with pytest.raises(ValueError, match=field):
        derive(paths)


@pytest.mark.parametrize('change', ['unreviewed', 'too_few', 'unsafe_path', 'wrong_source'])
def test_derivation_refuses_unverified_or_changed_crop_mapping(tmp_path, change):
    paths = inputs(tmp_path)
    frozen = json.loads(paths[1].read_text())
    if change == 'unreviewed':
        frozen['visual_review'] = 'pending'
    elif change == 'too_few':
        frozen['photos'].pop('16')
    elif change == 'unsafe_path':
        frozen['photos']['1']['path'] = '../outside.jpg'
    else:
        frozen['photos']['1']['source_sha256'] = 'b' * 64
    write_json(paths[1], frozen)
    with pytest.raises(ValueError):
        derive(paths)


def test_attribute_score_allows_null_bbox_and_never_scores_iou_or_thickness():
    score = api().score_crop([prediction(bbox=None)], truth())
    assert score['eligible'] is True
    assert score['joint_correct'] == 1
    assert score['joint_total'] == 1
    assert set(score['fields']) == {'category', 'colors', 'pattern'}
    assert all(field['correct'] == 1 for field in score['fields'].values())
    assert score['bbox_available'] is False
    assert score['bbox_invalid'] is False
    assert 'iou' not in score and 'precision' not in score and 'recall' not in score


def test_valid_bbox_is_reported_without_becoming_an_attribute_matching_rule():
    score = api().score_crop([prediction()], truth())
    assert score['joint_correct'] == 1
    assert score['bbox_available'] is True and score['bbox_invalid'] is False


def test_missing_bbox_is_an_allowed_attribute_result():
    value = prediction()
    value.pop('bbox')
    score = api().score_crop([value], truth())
    assert score['joint_correct'] == 1
    assert score['bbox_available'] is False and score['bbox_invalid'] is False


def test_colors_require_exact_set_equality():
    scorer = api().score_crop
    assert scorer([prediction(colors=['blue', 'white', 'blue'])], truth())['fields']['colors']['correct'] == 1
    score = scorer([prediction(colors=['blue'])], truth())
    assert score['fields']['colors']['correct'] == 0
    assert score['joint_correct'] == 0


@pytest.mark.parametrize('field,value', [('category', 'dress'), ('colors', ['red']), ('pattern', 'solid')])
def test_wrong_attribute_is_counted_separately_and_breaks_joint(tmp_path, field, value):
    score = api().score_crop([prediction(**{field: value})], truth())
    assert score['eligible'] is True
    assert score['fields'][field]['correct'] == 0
    assert sum(item['correct'] for item in score['fields'].values()) == 2
    assert score['joint_correct'] == 0


@pytest.mark.parametrize('bbox', [None, [], [0, 0, 0, 1], [-.1, 0, 1, 1], [0, 0, 1.1, 1],
                                  [False, 0, 1, 1], [0, 0, math.nan, 1], [0, 0, math.inf, 1],
                                  [0, 0, 10 ** 400, 1]])
def test_bbox_quality_does_not_change_attribute_scores_or_denominators(bbox):
    score = api().score_crop([prediction(bbox=bbox)], truth())
    assert score['eligible'] is True
    assert score['joint_correct'] == 1 and score['joint_total'] == 1
    assert score['bbox_available'] is False
    assert score['bbox_invalid'] is (bbox is not None)
    assert all(item['correct'] == 1 and item['total'] == 1 for item in score['fields'].values())


@pytest.mark.parametrize('field,value', [('category', None), ('colors', ['unknown']), ('pattern', 'unknown')])
def test_unknown_attributes_fail_their_fixed_field_and_joint_denominators(field, value):
    score = api().score_crop([prediction(**{field: value})], truth())
    assert score['fields'][field]['correct'] == 0
    assert score['fields'][field]['answered'] == 0
    assert score['fields'][field]['total'] == 1
    assert score['joint_correct'] == 0 and score['joint_total'] == 1


@pytest.mark.parametrize('predictions,status', [([], 'ok'), ([prediction(), prediction()], 'ok'),
                                               ([prediction()], 'error'), (None, 'ok'), ([None], 'ok')])
def test_missing_extra_failed_and_invalid_results_remain_failures(predictions, status):
    score = api().score_crop(predictions, truth(), status=status)
    assert score['status'] == status
    assert score['eligible'] is False
    assert score['joint_correct'] == 0 and score['joint_total'] == 1
    assert all(item['total'] == 1 and item['correct'] == 0 for item in score['fields'].values())


def test_pilot_scoring_retains_extra_and_failed_results_and_all_16_samples(tmp_path):
    pilot = derive(inputs(tmp_path))
    entries = pilot['entries']
    records = [{'image': entries[0]['image'], 'status': 'ok', 'candidates': [prediction()], 'source': 'live',
                'raw_candidates': [prediction(colors=['white', 'blue', 'blue'])]},
               {'image': entries[1]['image'], 'status': 'ok', 'candidates': [prediction(), prediction()]},
               {'image': entries[2]['image'], 'status': 'error', 'candidates': [prediction()],
                'error': {'code': 'REQUEST_FAILED'}, 'usage': {'prompt_tokens': 25}}]
    before = copy.deepcopy(records)
    result = api().score_pilot(pilot, records)
    assert result['images'] == result['joint_total'] == len(result['records']) == 16
    assert result['independent_groups'] == 1
    assert result['joint_correct'] == 1
    assert result['joint_accuracy'] == 1 / 16
    assert result['status_counts']['missing_result'] == 13
    assert all(item['total'] == 16 and item['accuracy'] == 1 / 16 for item in result['fields'].values())
    assert len(result['records'][1]['candidates']) == 2
    assert result['records'][2]['error'] == {'code': 'REQUEST_FAILED'}
    assert result['records'][2]['usage'] == {'prompt_tokens': 25}
    assert result['records'][0]['raw_candidates'] == records[0]['raw_candidates']
    assert result['bbox_available'] == 1 and result['bbox_invalid'] == 0
    assert result['provenance'] == pilot['provenance']
    assert records == before


def test_raw_invalid_bbox_is_visible_after_normalization_without_penalizing_attributes(tmp_path):
    pilot = derive(inputs(tmp_path))
    records = [{'image': pilot['entries'][0]['image'], 'status': 'ok',
                'candidates': [prediction(bbox=None)], 'raw_candidates': [prediction(bbox=[-1, 0, 1, 1])]}]
    result = api().score_pilot(pilot, records)
    assert result['joint_correct'] == 1
    assert result['bbox_available'] == 0 and result['bbox_invalid'] == 1
    assert result['records'][0]['raw_candidates'][0]['bbox'] == [-1, 0, 1, 1]


@pytest.mark.parametrize('problem', ['duplicate', 'unknown'])
def test_pilot_scoring_refuses_ambiguous_result_alignment(tmp_path, problem):
    pilot = derive(inputs(tmp_path))
    record = {'image': pilot['entries'][0]['image'], 'status': 'ok', 'candidates': [prediction()]}
    records = [record, dict(record)] if problem == 'duplicate' else [dict(record, image='other.jpg')]
    with pytest.raises(ValueError):
        api().score_pilot(pilot, records)


@pytest.mark.parametrize('location', ['sha256', 'identity'])
def test_pilot_scoring_rejects_mismatched_result_hash_instead_of_relabeling_it(tmp_path, location):
    pilot = derive(inputs(tmp_path))
    record = {'image': pilot['entries'][0]['image'], 'status': 'ok', 'candidates': [prediction()]}
    if location == 'sha256':
        record['sha256'] = '0' * 64
    else:
        record['identity'] = {'image_sha256': '0' * 64}
    with pytest.raises(ValueError, match='hash'):
        api().score_pilot(pilot, [record])


def test_real_frozen_crop_inventory_is_a_16_sample_development_diagnostic():
    root = Path(__file__).resolve().parents[2] / 'eval/outfits_v2/dataset/desktop-2026-10-05'
    pilot = api().derive_crop_pilot(root / 'garments.json', root / 'prepared/cases.json', root / 'prepared',
                                  confirmation_path=root / 'confirmation.json')
    assert len(pilot['entries']) == 16
    assert all(entry['truth']['thickness'] is None for entry in pilot['entries'])
    assert pilot['provenance']['inventory_object_count'] == 75
    assert len({entry['group_id'] for entry in pilot['entries']}) == 1
