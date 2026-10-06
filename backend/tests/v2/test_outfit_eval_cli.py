import json
import hashlib
from pathlib import Path

from app.v2.outfits import rules
from eval.outfits_v2.__main__ import main
from eval.outfits_v2.__main__ import _output_guard
from eval.outfits_v2.prepare import fingerprint
from eval.outfits_v2.protocol import safe_payload
from tests.v2.test_outfit_eval_runner import with_photos
import pytest


def test_cli_live_requires_budget_without_writing(tmp_path):
    output = tmp_path / 'run'
    result = main(['--cases', str(tmp_path / 'missing.json'), '--models', 'missing.json',
                   '--images', str(tmp_path), '--output', str(output), '--live'])
    assert result == 2
    assert not output.exists()


def test_cli_does_not_overwrite_existing_output(tmp_path):
    output = tmp_path / 'run'
    output.mkdir()
    marker = output / 'keep.txt'
    marker.write_text('original')
    result = main(['--cases', str(tmp_path / 'missing.json'), '--models', 'missing.json',
                   '--images', str(tmp_path), '--output', str(output)])
    assert result == 2
    assert marker.read_text() == 'original'


def test_cli_rejects_cache_file_and_cache_inside_inputs_before_calls(tmp_path):
    images = tmp_path / 'prepared'
    images.mkdir()
    cases = images / 'cases.json'
    models = tmp_path / 'models.json'
    output = tmp_path / 'run'
    cache = tmp_path / 'cache-file'
    cache.write_text('preserve')
    with pytest.raises(ValueError, match='cache'):
        _output_guard(output, cases, models, images, cache)
    with pytest.raises(ValueError, match='cache'):
        _output_guard(output, cases, models, images, images / 'cache')
    assert not output.exists()
    assert cache.read_text() == 'preserve'


@pytest.mark.parametrize('mode', [None, 'prompt_only', 'json_object'])
def test_cli_output_mode_reaches_records_and_both_reports_without_live_calls(tmp_path, mode):
    images = tmp_path/'images'
    images.mkdir()
    value = with_photos(images)
    value['request_group'] = fingerprint({'text': safe_payload(value),
                                          'photos': {gid: p['sha256'] for gid, p in value['photos'].items()}})
    bundle = {'schema_version': 1, 'kind': 'frozen_outfit_development_comparison',
              'rule_sha256': hashlib.sha256(Path(rules.__file__).read_bytes()).hexdigest(),
              'pilot_objects': 3, 'cases': [value, {**value, 'id': 'equivalent-case'}]}
    cases = images/'cases.json'
    cases.write_text(json.dumps(bundle))
    models = tmp_path/'models.json'
    models.write_text(json.dumps({'schema_version': 1, 'models': [{
        'name': 'offline model', 'provider': 'ark', 'model': 'fixed-model',
        'base_url': 'https://example.test/v1', 'api_key_env': 'OUTFIT_EVAL_TEST_KEY',
    }]}))
    output = tmp_path/'run'
    argv = ['--cases', str(cases), '--images', str(images), '--models', str(models),
            '--cache-dir', str(tmp_path/'cache'), '--output', str(output)]
    if mode is not None:
        argv += ['--output-mode', mode]
    assert main(argv) == 0
    report = json.loads((output/'report.json').read_text())
    expected = mode or 'prompt_only'
    assert report['output_mode'] == expected and report['live_calls'] == 0
    assert all(record['identity']['output_mode'] == expected for record in report['records'])
    assert sum(record['source'] == 'equivalent_reuse' for record in report['records']) == 2
    assert expected in (output/'report.md').read_text()
    assert not (tmp_path/'cache').exists()


def test_cli_rejects_unknown_output_mode_before_reading_or_writing(tmp_path):
    output = tmp_path/'run'
    with pytest.raises(SystemExit) as error:
        main(['--cases', 'missing.json', '--models', 'missing.json', '--images', str(tmp_path),
              '--output', str(output), '--output-mode', 'json_schema'])
    assert error.value.code == 2
    assert not output.exists()
