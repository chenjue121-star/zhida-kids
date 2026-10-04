from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import subprocess
import sys
import types

import pytest


def legacy_module(monkeypatch, name):
    # A blocked stand-in makes the red tests safe even before lazy import exists.
    provider = types.ModuleType('app.services.recognition.recognize')

    async def forbidden(*args, **kwargs):
        raise AssertionError('A test must never call a real recognizer')

    provider.recognize_image = forbidden
    monkeypatch.setitem(sys.modules, provider.__name__, provider)
    return importlib.import_module(f'eval.recognition.{name}')


def arguments(tmp_path, **changes):
    return argparse.Namespace(
        baseline='baseline', variant='variant_example', repeat=1, limit=0,
        out=str(tmp_path / 'report.md'), yes=False, dry_run=True, **changes,
    )


def test_legacy_import_does_not_load_provider_or_real_settings():
    script = '''
import builtins
original_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name in {'app.services.recognition.recognize', 'app.config'}:
        raise AssertionError('Importing legacy evaluation must not load provider/config')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded
import eval.recognition.runner
import eval.recognition.ab_compare
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_legacy_offline_cache_miss_never_reads_image_or_calls_recognizer(tmp_path, monkeypatch):
    runner = legacy_module(monkeypatch, 'runner')
    calls = []

    async def recognizer(*args):
        calls.append(args)
        return {'type': 'top'}

    with pytest.raises(runner.OfflineCacheMiss, match='cache|缓存'):
        asyncio.run(runner.run_recognition(
            tmp_path / 'missing.jpg', 'missing.jpg', 'prompt', 0,
            tmp_path / 'cache', recognizer=recognizer, offline=True,
        ))
    assert calls == []


def test_legacy_offline_cache_hit_keeps_old_cache_key_and_needs_no_image(tmp_path, monkeypatch):
    runner = legacy_module(monkeypatch, 'runner')
    cache = tmp_path / 'cache'
    cache.mkdir()
    expected = {'type': 'top', 'main_color': 'white', 'thickness': 'thin'}
    key = runner.cache_key('missing.jpg', 'prompt A', 0)
    (cache / f'{key}.json').write_text(json.dumps(expected), encoding='utf-8')

    result = asyncio.run(runner.run_recognition(
        tmp_path / 'missing.jpg', 'missing.jpg', 'prompt A', 0, cache, offline=True,
    ))
    assert result == expected


def test_legacy_offline_cannot_be_bypassed_by_disabling_cache(tmp_path, monkeypatch):
    runner = legacy_module(monkeypatch, 'runner')
    calls = []

    async def recognizer(*args):
        calls.append(args)
        return {'type': 'top'}

    with pytest.raises(runner.OfflineCacheMiss):
        asyncio.run(runner.run_recognition(
            tmp_path / 'missing.jpg', 'missing.jpg', 'prompt', 0,
            tmp_path / 'cache', recognizer=recognizer, offline=True, use_cache=False,
        ))
    assert calls == []


def test_legacy_online_fake_recognizer_still_populates_compatible_cache(tmp_path, monkeypatch):
    runner = legacy_module(monkeypatch, 'runner')
    image = tmp_path / 'sample.jpg'
    image.write_bytes(b'local fixture bytes')
    calls = []

    async def recognizer(data_url, prompt):
        calls.append((data_url, prompt))
        return {'type': 'top', 'main_color': 'white'}

    expected = asyncio.run(runner.run_recognition(image, image.name, 'prompt', 0, tmp_path / 'cache', recognizer=recognizer))
    assert len(calls) == 1 and calls[0][0].startswith('data:image/jpeg;base64,')
    assert asyncio.run(runner.run_recognition(tmp_path / 'missing.jpg', image.name, 'prompt', 0, tmp_path / 'cache', offline=True)) == expected


def test_legacy_score_prompt_forwards_offline_to_every_run(tmp_path, monkeypatch):
    compare = legacy_module(monkeypatch, 'ab_compare')
    calls = []

    async def cached(**kwargs):
        calls.append(kwargs)
        return {'type': 'top', 'main_color': 'white', 'thickness': 'thin'}

    monkeypatch.setattr(compare, 'run_recognition', cached)
    labels = [{'image': 'sample.jpg', 'type': 'top', 'main_color': 'white', 'thickness': 'thin'}]
    asyncio.run(compare._score_prompt('prompt', labels, 2, True, offline=True))
    assert [call['offline'] for call in calls] == [True, True]


@pytest.mark.parametrize('yes', [False, True])
def test_legacy_dry_run_missing_cache_returns_nonzero_without_partial_report(tmp_path, monkeypatch, capsys, yes):
    compare = legacy_module(monkeypatch, 'ab_compare')
    runner = legacy_module(monkeypatch, 'runner')
    args = arguments(tmp_path)
    args.yes = yes
    labels = [{'image': 'sample.jpg', 'type': 'top', 'main_color': 'white', 'thickness': 'thin'}]
    monkeypatch.setattr(compare, 'load_labels', lambda path: labels)
    monkeypatch.setattr(compare, '_load_prompt', lambda name: name)
    calls = []

    async def score(prompt, labels, repeat, use_cache, *, offline=False):
        calls.append(offline)
        raise runner.OfflineCacheMiss('missing cached response')

    def forbid_partial_report(*args):
        raise AssertionError('A missing cache must not produce a score report')

    monkeypatch.setattr(compare, '_score_prompt', score)
    monkeypatch.setattr(compare, 'format_comparison', forbid_partial_report)

    assert asyncio.run(compare._run(args)) != 0
    assert calls == [True]
    assert not (tmp_path / 'report.md').exists()
    output = capsys.readouterr().out
    assert 'cache' in output.lower() or '缓存' in output


@pytest.mark.parametrize(('field', 'value'), [('repeat', 0), ('repeat', -1), ('limit', -1)])
def test_legacy_validates_repeat_and_limit_before_loading_labels(tmp_path, monkeypatch, field, value):
    compare = legacy_module(monkeypatch, 'ab_compare')
    args = arguments(tmp_path)
    setattr(args, field, value)

    def forbidden(path):
        raise AssertionError('Invalid run options must stop before reading labels')

    monkeypatch.setattr(compare, 'load_labels', forbidden)
    assert asyncio.run(compare._run(args)) != 0


def test_legacy_scaffold_preserves_existing_human_labels(tmp_path, monkeypatch):
    compare = legacy_module(monkeypatch, 'ab_compare')
    labels = tmp_path / 'labels.yaml'
    labels.write_text('existing human annotations', encoding='utf-8')
    monkeypatch.setattr(compare, 'LABELS', labels)
    monkeypatch.setattr(compare, 'IMAGES', tmp_path)
    with pytest.raises(FileExistsError):
        compare.scaffold_labels()
    assert labels.read_text(encoding='utf-8') == 'existing human annotations'


def test_legacy_scaffold_overwrite_requires_explicit_option(tmp_path, monkeypatch):
    compare = legacy_module(monkeypatch, 'ab_compare')
    labels = tmp_path / 'labels.yaml'
    labels.write_text('previous annotations', encoding='utf-8')
    (tmp_path / 'sample.jpg').write_bytes(b'fixture')
    monkeypatch.setattr(compare, 'LABELS', labels)
    monkeypatch.setattr(compare, 'IMAGES', tmp_path)
    compare.scaffold_labels(overwrite=True)
    assert '- image: sample.jpg' in labels.read_text(encoding='utf-8')


@pytest.mark.parametrize('content', ['{broken', '[1, 2]'])
def test_legacy_unusable_cache_is_offline_miss_without_recognizer_call(tmp_path, monkeypatch, content):
    runner = legacy_module(monkeypatch, 'runner')
    cache = tmp_path / 'cache'
    cache.mkdir()
    key = runner.cache_key('missing.jpg', 'prompt', 0)
    (cache / f'{key}.json').write_text(content)
    calls = []

    async def recognizer(*args):
        calls.append(args)
        return {'type': 'top'}

    with pytest.raises(runner.OfflineCacheMiss):
        asyncio.run(runner.run_recognition(tmp_path / 'missing.jpg', 'missing.jpg', 'prompt', 0, cache,
                                           recognizer=recognizer, offline=True))
    assert calls == []
