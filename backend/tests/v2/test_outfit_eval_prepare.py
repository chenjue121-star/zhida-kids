import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from eval.outfits_v2.prepare import PILOT_IMAGES, freeze_cases, prepare_bundle


def make_inventory(tmp_path):
    root = tmp_path / 'sources'
    root.mkdir()
    items = []
    categories = ['outerwear', 'bottom', 'onesie', 'top',
                  'dress', 'top', 'top', 'top', 'top', 'top', 'dress', 'dress',
                  'dress', 'bottom', 'dress', 'onesie']
    for index, (name, category) in enumerate(zip(PILOT_IMAGES, categories), 1):
        path = root / name
        Image.new('RGB', (80, 100), (index * 10, 50, 100)).save(path)
        items.append({'id': str(index), 'draft_id': f'obj-{index}', 'source_image': name,
                      'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      'bbox': [.1, .1, .9, .9], 'category': category, 'colors': ['blue'],
                      'pattern': 'solid', 'thickness': None, 'description': 'DO NOT SEND THIS'})
    path = tmp_path / 'garments.json'
    path.write_text(json.dumps({'schema_version': 1, 'kind': 'confirmed_main_product_inventory',
                                'confirmed_on': '2026-10-05', 'items': items}))
    return path, root


def test_prepare_produces_matched_cases_and_preserves_unknown_inventory(tmp_path):
    inventory, root = make_inventory(tmp_path)
    output = tmp_path / 'prepared'
    bundle = prepare_bundle(inventory, root, output)
    assert len(bundle['cases']) == 12
    assert len(bundle['photos']) == 16
    assert all(len(case['combinations']) <= 20 for case in bundle['cases'])
    assert all(case['baseline_ids'] in case['combinations'] for case in bundle['cases'])
    assert all(g['thickness'] == 'unknown' for case in bundle['cases'] for g in case['garments'])
    assert all(g['thickness'] is None for g in json.loads(inventory.read_text())['items'])
    assert all('description' not in g for case in bundle['cases'] for g in case['garments'])
    assert all(photo['sha256'] == hashlib.sha256((output / photo['path']).read_bytes()).hexdigest()
               for photo in bundle['photos'].values())
    assert all(not case['combinations'] for case in bundle['boundary_cases'])
    assert (output / 'cases.json').is_file()


def test_prepare_refuses_mutated_source_before_generating_output(tmp_path):
    inventory, root = make_inventory(tmp_path)
    (root / PILOT_IMAGES[0]).write_bytes(b'changed')
    output = tmp_path / 'prepared'
    with pytest.raises(ValueError, match='hash'):
        prepare_bundle(inventory, root, output)
    assert not output.exists()


def test_prepare_preserves_existing_output(tmp_path):
    inventory, root = make_inventory(tmp_path)
    output = tmp_path / 'prepared'
    output.mkdir()
    marker = output / 'keep.txt'
    marker.write_text('original')
    with pytest.raises(ValueError, match='empty'):
        prepare_bundle(inventory, root, output)
    assert marker.read_text() == 'original'


def test_prepare_rejects_unconfirmed_inventory(tmp_path):
    inventory, root = make_inventory(tmp_path)
    document = json.loads(inventory.read_text())
    document['kind'] = 'ai_annotation_review_draft'
    inventory.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='confirmed'):
        prepare_bundle(inventory, root, tmp_path / 'prepared')


def test_freeze_rejects_null_category_and_unknown_pattern_in_pilot(tmp_path):
    inventory, root = make_inventory(tmp_path)
    document = json.loads(inventory.read_text())
    document['items'][0]['category'] = None
    inventory.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='category'):
        prepare_bundle(inventory, root, tmp_path / 'prepared')


def test_prepare_refuses_writing_into_source_directory(tmp_path):
    inventory, root = make_inventory(tmp_path)
    with pytest.raises(ValueError, match='source'):
        prepare_bundle(inventory, root, root / 'derived')


def test_prepare_rejects_traversal_id_before_any_file_write(tmp_path):
    inventory, root = make_inventory(tmp_path)
    document = json.loads(inventory.read_text())
    document['items'][0]['id'] = '../../victim'
    inventory.write_text(json.dumps(document))
    victim = tmp_path / 'victim.jpg'
    victim.write_bytes(b'keep-original')
    output = tmp_path / 'prepared'
    with pytest.raises(ValueError):
        prepare_bundle(inventory, root, output)
    assert victim.read_bytes() == b'keep-original'
    assert not output.exists()
