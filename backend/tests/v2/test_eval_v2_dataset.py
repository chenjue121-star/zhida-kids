from __future__ import annotations

import hashlib
import importlib
import json
from copy import deepcopy

import pytest
from PIL import Image


def dataset():
    try:
        return importlib.import_module('eval.recognition_v2.dataset')
    except ModuleNotFoundError:
        pytest.fail('The V2 dataset audit and manifest contract has not been implemented')


def image_file(path, *, color='red', size=(40, 20), orientation=None):
    image = Image.new('RGB', size, color)
    kwargs = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[274] = orientation
        kwargs['exif'] = exif
    image.save(path, **kwargs)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def garment(**changes):
    return {
        'id': 'garment-1',
        'bbox': [0.1, 0.2, 0.8, 0.9],
        'category': 'top',
        'colors': ['red', 'white'],
        'pattern': 'stripe',
        'thickness': None,
        'observable': ['category', 'colors', 'pattern'],
        **changes,
    }


@pytest.fixture
def sample(tmp_path):
    images = tmp_path / 'images'
    images.mkdir()
    sha256 = image_file(images / 'sample.png')
    entry = {
        'image': 'sample.png', 'sha256': sha256, 'group_id': 'family-garment-1',
        'split': 'test', 'scene': 'flat_lay', 'reviewed': True,
        'objects': [garment()],
    }
    return images, entry


def write_manifest(tmp_path, entries, *, schema_version=1):
    path = tmp_path / 'labels.json'
    path.write_text(json.dumps({'schema_version': schema_version, 'entries': entries}), encoding='utf-8')
    return path


def test_audit_decodes_images_and_retains_bad_files_without_mutation(tmp_path):
    image_file(tmp_path / 'b.PNG')
    image_file(tmp_path / 'a.jpg', color='blue')
    (tmp_path / 'broken.webp').write_bytes(b'not an image')
    (tmp_path / 'ignored.txt').write_text('ignored', encoding='utf-8')
    nested = tmp_path / 'nested'
    nested.mkdir()
    image_file(nested / 'nested.png')
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}

    audit = dataset().audit_images(tmp_path)

    assert {key: audit[key] for key in ('total', 'valid', 'unique_valid', 'invalid', 'duplicates')} == {
        'total': 3, 'valid': 2, 'unique_valid': 2, 'invalid': 1, 'duplicates': 0,
    }
    assert [entry['image'] for entry in audit['entries']] == ['a.jpg', 'b.PNG', 'broken.webp']
    assert audit['entries'][0]['format'] == 'JPEG'
    assert audit['entries'][1]['format'] == 'PNG'
    broken = audit['entries'][2]
    assert broken['valid'] is False
    assert broken['error']
    assert broken['sha256'] == hashlib.sha256(b'not an image').hexdigest()
    assert broken['width'] is None and broken['height'] is None
    assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}


def test_audit_uses_original_bytes_for_duplicates_and_exif_dimensions(tmp_path):
    sha256 = image_file(tmp_path / 'a.jpg', orientation=6)
    (tmp_path / 'b.jpeg').write_bytes((tmp_path / 'a.jpg').read_bytes())

    audit = dataset().audit_images(tmp_path)

    assert audit['valid'] == 2
    assert audit['unique_valid'] == 1
    assert audit['duplicates'] == 1
    first, second = audit['entries']
    assert first['sha256'] == second['sha256'] == sha256
    assert first['width'] == 20 and first['height'] == 40
    assert first['duplicate_of'] is None
    assert second['duplicate_of'] == 'a.jpg'


def test_audit_rejects_symlink_escape_without_reading_external_image(tmp_path):
    images = tmp_path / 'images'
    images.mkdir()
    image_file(tmp_path / 'outside.png')
    (images / 'escape.png').symlink_to(tmp_path / 'outside.png')

    entry = dataset().audit_images(images)['entries'][0]

    assert entry['valid'] is False
    assert entry['sha256'] is None
    assert 'outside' in entry['error'].lower() or 'escape' in entry['error'].lower()


def test_scaffold_only_includes_unique_valid_images_and_never_infers_labels(tmp_path):
    image_file(tmp_path / 'a.png')
    (tmp_path / 'b.png').write_bytes((tmp_path / 'a.png').read_bytes())
    (tmp_path / 'bad.jpg').write_bytes(b'bad')
    module = dataset()

    manifest = module.scaffold_manifest(module.audit_images(tmp_path))

    assert manifest == {'schema_version': 1, 'entries': [{
        'image': 'a.png', 'sha256': hashlib.sha256((tmp_path / 'a.png').read_bytes()).hexdigest(),
        'group_id': None, 'split': None, 'scene': None, 'reviewed': False, 'objects': None,
    }]}


def test_manifest_preserves_reviewed_record_and_accepts_explicit_negative(tmp_path, sample):
    images, entry = sample
    entry['objects'] = []
    entry['annotation_note'] = 'Human verified no garment'
    path = write_manifest(tmp_path, [entry])

    assert dataset().load_manifest(path, images) == [entry]


def test_manifest_accepts_observable_truth_and_missing_unobservable_fields(tmp_path, sample):
    images, entry = sample
    del entry['objects'][0]['thickness']
    path = write_manifest(tmp_path, [entry])

    assert dataset().load_manifest(path, images, split='test') == [entry]
    assert dataset().load_manifest(path, images, split='development') == []


@pytest.mark.parametrize('reviewed', [False, None, 1, 'true'])
def test_manifest_rejects_unreviewed_records_even_when_objects_are_empty(tmp_path, sample, reviewed):
    images, entry = sample
    entry.update(reviewed=reviewed, objects=[])
    with pytest.raises(dataset().ManifestError, match='reviewed'):
        dataset().load_manifest(write_manifest(tmp_path, [entry]), images)


def test_manifest_rejects_changed_image_bytes(tmp_path, sample):
    images, entry = sample
    image_file(images / 'sample.png', color='blue')
    with pytest.raises(dataset().ManifestError, match='sha256|hash'):
        dataset().load_manifest(write_manifest(tmp_path, [entry]), images)


def test_manifest_rejects_corrupt_image_even_when_hash_matches(tmp_path, sample):
    images, entry = sample
    (images / 'sample.png').write_bytes(b'broken image')
    entry['sha256'] = hashlib.sha256(b'broken image').hexdigest()
    with pytest.raises(dataset().ManifestError, match='decode|image|图片'):
        dataset().load_manifest(write_manifest(tmp_path, [entry]), images)


@pytest.mark.parametrize('name', ['../outside.png', '/tmp/outside.png', 'nested/../../outside.png', r'..\outside.png', 'C:/outside.png'])
def test_manifest_rejects_unsafe_image_paths(tmp_path, sample, name):
    images, entry = sample
    entry['image'] = name
    with pytest.raises(dataset().ManifestError, match='image|path'):
        dataset().load_manifest(write_manifest(tmp_path, [entry]), images)


def test_manifest_rejects_symlink_escape(tmp_path, sample):
    images, entry = sample
    entry['sha256'] = image_file(tmp_path / 'outside.png')
    (images / 'escape.png').symlink_to(tmp_path / 'outside.png')
    entry['image'] = 'escape.png'
    with pytest.raises(dataset().ManifestError, match='image|path'):
        dataset().load_manifest(write_manifest(tmp_path, [entry]), images)


def test_manifest_accepts_safe_nested_relative_image(tmp_path, sample):
    images, entry = sample
    (images / 'nested').mkdir()
    (images / 'sample.png').rename(images / 'nested' / 'sample.png')
    entry['image'] = 'nested/sample.png'
    assert dataset().load_manifest(write_manifest(tmp_path, [entry]), images) == [entry]


def test_manifest_rejects_repeated_image_names(tmp_path, sample):
    images, entry = sample
    with pytest.raises(dataset().ManifestError, match='duplicate'):
        dataset().load_manifest(write_manifest(tmp_path, [entry, deepcopy(entry)]), images)


def test_manifest_rejects_same_contents_under_different_names(tmp_path, sample):
    images, entry = sample
    (images / 'copy.png').write_bytes((images / 'sample.png').read_bytes())
    copy = {**deepcopy(entry), 'image': 'copy.png', 'group_id': 'another-group'}
    with pytest.raises(dataset().ManifestError, match='duplicate'):
        dataset().load_manifest(write_manifest(tmp_path, [entry, copy]), images)


def test_manifest_checks_group_leakage_before_split_filter(tmp_path, sample):
    images, entry = sample
    other = {**deepcopy(entry), 'image': 'other.png', 'split': 'calibration'}
    other['sha256'] = image_file(images / 'other.png', color='blue')
    with pytest.raises(dataset().ManifestError, match='group_id|split'):
        dataset().load_manifest(write_manifest(tmp_path, [entry, other]), images, split='test')


def test_manifest_checks_unselected_records_before_split_filter(tmp_path, sample):
    images, entry = sample
    other = {**deepcopy(entry), 'image': 'other.png', 'split': 'development', 'group_id': 'other', 'reviewed': False}
    other['sha256'] = image_file(images / 'other.png', color='blue')
    with pytest.raises(dataset().ManifestError, match='reviewed'):
        dataset().load_manifest(write_manifest(tmp_path, [entry, other]), images, split='test')


@pytest.mark.parametrize(('key', 'value'), [
    ('group_id', None), ('group_id', '  '), ('scene', ''), ('scene', 3),
    ('split', 'training'), ('objects', None), ('objects', {}),
])
def test_manifest_rejects_incomplete_record_metadata(tmp_path, sample, key, value):
    images, entry = sample
    entry[key] = value
    with pytest.raises(dataset().ManifestError, match=key):
        dataset().load_manifest(write_manifest(tmp_path, [entry]), images)


@pytest.mark.parametrize('schema_version', [None, True, '1', 2])
def test_manifest_requires_exact_schema_version(tmp_path, sample, schema_version):
    images, entry = sample
    with pytest.raises(dataset().ManifestError, match='schema_version'):
        dataset().load_manifest(write_manifest(tmp_path, [entry], schema_version=schema_version), images)


@pytest.mark.parametrize('bbox', [
    [0, 0, 0, 1], [0.8, 0, 0.2, 1], [0, 0, 1, 2], [-0.1, 0, 1, 1],
    [0, 0, float('nan'), 1], [0, 0, float('inf'), 1], [False, 0, 1, 1],
    [0, 0, '1', 1], [0, 0, 1], [0, 0, 10 ** 400, 1], None,
])
def test_manifest_requires_finite_normalized_nonempty_bbox(tmp_path, sample, bbox):
    images, entry = sample
    entry['objects'][0]['bbox'] = bbox
    with pytest.raises(dataset().ManifestError, match='bbox'):
        dataset().load_manifest(write_manifest(tmp_path, [entry]), images)


@pytest.mark.parametrize(('field', 'value'), [
    ('category', 'shirt'), ('category', None), ('colors', ['unknown']), ('colors', []),
    ('colors', ['red', 'red']), ('colors', 'red'), ('colors', ['cream']),
    ('pattern', 'unknown'), ('pattern', None), ('pattern', 'floral'),
])
def test_manifest_rejects_invalid_observable_attribute(tmp_path, sample, field, value):
    images, entry = sample
    entry['objects'][0][field] = value
    with pytest.raises(dataset().ManifestError, match=field):
        dataset().load_manifest(write_manifest(tmp_path, [entry]), images)


@pytest.mark.parametrize('value', ['thin', 'unknown', [], False])
def test_manifest_rejects_values_for_unobservable_attribute(tmp_path, sample, value):
    images, entry = sample
    entry['objects'][0]['thickness'] = value
    with pytest.raises(dataset().ManifestError, match='thickness'):
        dataset().load_manifest(write_manifest(tmp_path, [entry]), images)


@pytest.mark.parametrize('observable', [None, 'category', ['season'], ['category', 'category']])
def test_manifest_rejects_missing_unknown_or_repeated_observable_fields(tmp_path, sample, observable):
    images, entry = sample
    entry['objects'][0]['observable'] = observable
    with pytest.raises(dataset().ManifestError, match='observable'):
        dataset().load_manifest(write_manifest(tmp_path, [entry]), images)


def test_manifest_accepts_unobservable_category_and_valid_observable_thickness(tmp_path, sample):
    images, entry = sample
    entry['objects'] = [garment(category=None, thickness='medium', observable=['colors', 'pattern', 'thickness'])]
    assert dataset().load_manifest(write_manifest(tmp_path, [entry]), images) == [entry]


@pytest.mark.parametrize('objects', [[garment(), garment()], [garment(id='')], [garment(id=1)], [garment(id=f'g-{index}') for index in range(31)]])
def test_manifest_requires_unique_object_ids_and_at_most_30_objects(tmp_path, sample, objects):
    images, entry = sample
    entry['objects'] = objects
    with pytest.raises(dataset().ManifestError, match='id|30|objects'):
        dataset().load_manifest(write_manifest(tmp_path, [entry]), images)


def test_manifest_wraps_malformed_json_as_manifest_error(tmp_path, sample):
    images, _ = sample
    path = tmp_path / 'broken.json'
    path.write_text('{broken', encoding='utf-8')
    with pytest.raises(dataset().ManifestError, match='JSON|json'):
        dataset().load_manifest(path, images)
