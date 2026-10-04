import hashlib
import io
import json

from PIL import Image


def write_inputs(tmp_path, reviewed=True):
    images = tmp_path / 'images'
    images.mkdir()
    output = io.BytesIO()
    Image.new('RGB', (20, 20), 'white').save(output, format='JPEG')
    image = output.getvalue()
    (images / 'one.jpg').write_bytes(image)
    truth = {'id': 'garment-1', 'bbox': [0, 0, 1, 1], 'category': 'top', 'colors': ['white'],
             'pattern': 'solid', 'thickness': None, 'observable': ['category', 'colors', 'pattern']}
    entry = {'image': 'one.jpg', 'sha256': hashlib.sha256(image).hexdigest(), 'group_id': 'family-1',
             'split': 'test', 'scene': 'single', 'reviewed': reviewed, 'objects': [truth]}
    labels = tmp_path / 'labels.json'
    labels.write_text(json.dumps({'schema_version': 1, 'entries': [entry]}))
    models = tmp_path / 'models.json'
    models.write_text(json.dumps({'schema_version': 1, 'models': [
        {'name': 'model A', 'provider': 'qwen', 'model': 'fixed-model',
         'base_url': 'https://example.test/v1', 'api_key_env': 'TEST_EVAL_KEY'}]}))
    return images, labels, models


def compare_args(tmp_path, images, labels, models):
    return ['compare', '--images', str(images), '--manifest', str(labels), '--models', str(models),
            '--cache-dir', str(tmp_path / 'cache'), '--out', str(tmp_path / 'report.md'),
            '--json-out', str(tmp_path / 'results.json')]


def test_audit_and_scaffold_preserve_input_and_leave_labels_unreviewed(tmp_path):
    from eval.recognition_v2.compare import main
    images, _, _ = write_inputs(tmp_path)
    (images / 'copy.jpg').write_bytes((images / 'one.jpg').read_bytes())
    (images / 'bad.png').write_bytes(b'bad')
    audit = tmp_path / 'audit.json'
    assert main(['audit', '--images', str(images), '--out', str(audit)]) == 0
    assert json.loads(audit.read_text())['unique_valid'] == 1
    scaffold = tmp_path / 'draft.json'
    assert main(['scaffold', '--images', str(images), '--out', str(scaffold)]) == 0
    entry = json.loads(scaffold.read_text())['entries'][0]
    assert entry['reviewed'] is False and entry['objects'] is None
    assert len(list(images.iterdir())) == 3
    before = scaffold.read_bytes()
    assert main(['scaffold', '--images', str(images), '--out', str(scaffold)]) == 2
    assert scaffold.read_bytes() == before


def test_default_compare_missing_cache_never_constructs_provider(tmp_path, monkeypatch):
    from eval.recognition_v2 import compare
    images, labels, models = write_inputs(tmp_path)
    calls = []
    monkeypatch.setattr(compare, 'create_provider', lambda config: calls.append(config))
    assert compare.main(compare_args(tmp_path, images, labels, models)) == 3
    assert calls == []
    report = (tmp_path / 'report.md').read_text()
    assert '离线缓存不完整' in report
    assert 'precision：' not in report
    assert not (tmp_path / 'cache').exists()


def test_unreviewed_labels_fail_before_outputs_or_providers(tmp_path, monkeypatch):
    from eval.recognition_v2 import compare
    images, labels, models = write_inputs(tmp_path, reviewed=False)
    calls = []
    monkeypatch.setattr(compare, 'create_provider', lambda config: calls.append(config))
    assert compare.main(compare_args(tmp_path, images, labels, models)) == 2
    assert calls == []
    assert not (tmp_path / 'report.md').exists()


def test_live_requires_explicit_cap_and_preflights_before_calling(tmp_path, monkeypatch):
    from eval.recognition_v2 import compare
    images, labels, models = write_inputs(tmp_path)
    calls = []
    monkeypatch.setattr(compare, 'create_provider', lambda config: calls.append(config))
    args = compare_args(tmp_path, images, labels, models) + ['--live']
    assert compare.main(args) == 2
    assert compare.main(args + ['--max-calls', '1', '--repeat', '2']) == 2
    assert calls == []


def test_fake_live_roundtrip_records_scores_then_offline_replays(tmp_path, monkeypatch):
    from eval.recognition_v2 import compare
    images, labels, models = write_inputs(tmp_path)
    calls = []
    monkeypatch.setenv('TEST_EVAL_KEY', 'fixture-only')

    class Provider:
        def recognize(self, *args):
            calls.append(1)
            return {'candidates': [{'category': 'top', 'colors': ['white'], 'pattern': 'solid',
                                    'thickness': 'unknown', 'bbox': [0, 0, 1, 1]}],
                    '_trace': {'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}}

    monkeypatch.setattr(compare, 'create_provider', lambda config: Provider())
    args = compare_args(tmp_path, images, labels, models)
    assert compare.main(args + ['--live', '--max-calls', '1']) == 0
    records = json.loads((tmp_path / 'results.json').read_text())['models'][0]['records']
    assert records[0]['score']['joint_accuracy'] == 1.0
    assert len(calls) == 1
    assert compare.main(args + ['--overwrite']) == 0
    assert len(calls) == 1
    records = json.loads((tmp_path / 'results.json').read_text())['models'][0]['records']
    assert records[0]['source'] == 'cache'


def test_existing_output_stops_before_live_call(tmp_path, monkeypatch):
    from eval.recognition_v2 import compare
    images, labels, models = write_inputs(tmp_path)
    calls = []
    monkeypatch.setattr(compare, 'create_provider', lambda config: calls.append(config))
    (tmp_path / 'report.md').write_text('existing report')
    assert compare.main(compare_args(tmp_path, images, labels, models) + ['--live', '--max-calls', '1']) == 2
    assert calls == []
    assert (tmp_path / 'report.md').read_text() == 'existing report'


def test_model_file_rejects_secret_field_and_duplicate_names(tmp_path):
    import pytest
    from eval.recognition_v2.compare import load_model_specs
    _, _, models = write_inputs(tmp_path)
    data = json.loads(models.read_text())
    data['models'][0]['api_key'] = 'must-not-be-output'
    models.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_model_specs(models)
    data['models'][0].pop('api_key')
    data['models'].append(dict(data['models'][0]))
    models.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='name'):
        load_model_specs(models)


def test_compare_cannot_overwrite_unselected_source_photo(tmp_path):
    from eval.recognition_v2.compare import main
    images, labels, models = write_inputs(tmp_path)
    heldout = images / 'heldout.jpg'
    output = io.BytesIO()
    Image.new('RGB', (20, 20), 'red').save(output, format='JPEG')
    heldout.write_bytes(output.getvalue())
    manifest = json.loads(labels.read_text())
    entry = dict(manifest['entries'][0], image='heldout.jpg', sha256=hashlib.sha256(heldout.read_bytes()).hexdigest(),
                 group_id='family-2', split='calibration')
    manifest['entries'].append(entry)
    labels.write_text(json.dumps(manifest))
    args = compare_args(tmp_path, images, labels, models)
    args[args.index('--out') + 1] = str(heldout)
    before = heldout.read_bytes()
    assert main(args + ['--overwrite']) == 2
    assert heldout.read_bytes() == before


def test_scaffold_cannot_overwrite_nested_source_photo(tmp_path):
    from eval.recognition_v2.compare import main
    images, _, _ = write_inputs(tmp_path)
    nested = images / 'nested'
    nested.mkdir()
    target = nested / 'source.jpg'
    target.write_bytes((images / 'one.jpg').read_bytes())
    before = target.read_bytes()
    assert main(['scaffold', '--images', str(images), '--out', str(target), '--overwrite']) == 2
    assert target.read_bytes() == before
