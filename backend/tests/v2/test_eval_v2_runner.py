import io
from dataclasses import replace

import pytest
from PIL import Image


def photo(tmp_path):
    output = io.BytesIO()
    Image.new('RGB', (24, 20), 'white').save(output, format='JPEG')
    path = tmp_path / 'shirt.jpg'
    path.write_bytes(output.getvalue())
    return path


def spec():
    from eval.recognition_v2.runner import ModelSpec
    return ModelSpec('baseline', 'qwen', 'fixed-model', 'https://example.test/v1', 'TEST_EVAL_KEY')


def test_cache_identity_tracks_content_model_endpoint_prompt_and_repeat(tmp_path, monkeypatch):
    from eval.recognition_v2 import runner
    config = spec()
    key = runner.cache_key(b'image A', config, 0)
    assert key == runner.cache_key(b'image A', config, 0)
    assert key != runner.cache_key(b'image B', config, 0)
    assert key != runner.cache_key(b'image A', replace(config, model='other-model'), 0)
    assert key != runner.cache_key(b'image A', replace(config, base_url='https://other.test/v1'), 0)
    assert key != runner.cache_key(b'image A', config, 1)
    monkeypatch.setattr(runner, 'PROMPT', runner.PROMPT + '\nextra rule')
    assert key != runner.cache_key(b'image A', config, 0)


def test_offline_cache_miss_cannot_create_provider_or_cache(tmp_path):
    from eval.recognition_v2.runner import run_one
    calls = []
    result = run_one(photo(tmp_path), spec(), tmp_path / 'cache',
                     provider_factory=lambda config: calls.append(config))
    assert result['source'] == 'offline_missing'
    assert result['status'] == 'offline_missing'
    assert calls == []
    assert not (tmp_path / 'cache').exists()


def test_live_calls_production_normalizer_and_offline_replays_versioned_cache(tmp_path):
    from eval.recognition_v2.runner import CallBudget, run_one
    calls = []

    class Provider:
        def recognize(self, image, content_type):
            calls.append((image, content_type))
            return {'candidates': [{'category': 'top', 'colors': ['white'], 'pattern': 'solid',
                                    'thickness': 'unknown', 'bbox': [0, 0, 1, 1]},
                                   {'category': 'bottom', 'colors': ['illegal'], 'bbox': None}],
                    '_trace': {'model': 'returned-fixed-model', 'usage': {'prompt_tokens': 12}}}

    path = photo(tmp_path)
    live = run_one(path, spec(), tmp_path / 'cache', offline=False,
                   budget=CallBudget(1), provider_factory=lambda config: Provider())
    assert live['status'] == 'ok'
    assert len(live['candidates']) == 2
    assert live['candidates'][1]['colors'] == ['unknown']
    assert live['model'] == 'returned-fixed-model'
    assert live['usage'] == {'prompt_tokens': 12}
    assert calls[0][1] == 'image/jpeg'
    cached = run_one(path, spec(), tmp_path / 'cache', provider_factory=lambda config: Provider())
    assert cached['source'] == 'cache'
    assert cached['candidates'] == live['candidates']
    assert cached['elapsed_ms'] == live['elapsed_ms']
    assert len(calls) == 1


def test_live_failure_is_recorded_and_never_cached(tmp_path):
    from app.v2.integrations.recognition import RecognitionFailure
    from eval.recognition_v2.runner import CallBudget, run_one

    class Provider:
        def recognize(self, *args):
            raise RecognitionFailure('RECOGNITION_UNCERTAIN', 'request outcome unknown', uncertain=True)

    budget = CallBudget(1)
    result = run_one(photo(tmp_path), spec(), tmp_path / 'cache', offline=False,
                     budget=budget, provider_factory=lambda config: Provider())
    assert result['status'] == 'error'
    assert result['error']['code'] == 'RECOGNITION_UNCERTAIN'
    assert result['error']['uncertain'] is True
    assert budget.used == 1
    assert not list((tmp_path / 'cache').glob('*.json')) if (tmp_path / 'cache').exists() else True


def test_live_requires_budget_and_stops_before_provider_creation(tmp_path):
    from eval.recognition_v2.runner import CallBudget, CallLimitExceeded, run_one
    calls = []
    path = photo(tmp_path)
    with pytest.raises(ValueError, match='budget'):
        run_one(path, spec(), tmp_path / 'cache', offline=False)
    budget = CallBudget(1)
    budget.take()
    with pytest.raises(CallLimitExceeded):
        run_one(path, spec(), tmp_path / 'cache', offline=False, budget=budget,
                provider_factory=lambda config: calls.append(config))
    assert calls == []


def test_modified_or_corrupt_cache_is_offline_missing(tmp_path):
    import json
    from eval.recognition_v2.runner import cache_key, run_one
    path = photo(tmp_path)
    cache = tmp_path / 'cache'
    cache.mkdir()
    target = cache / (cache_key(path.read_bytes(), spec(), 0) + '.json')
    target.write_text(json.dumps({'identity': {}, 'status': 'ok', 'candidates': []}))
    assert run_one(path, spec(), cache)['status'] == 'offline_missing'
    target.write_text('{broken')
    assert run_one(path, spec(), cache)['status'] == 'offline_missing'


def test_invalid_image_does_not_consume_budget(tmp_path):
    from eval.recognition_v2.runner import CallBudget, run_one
    path = tmp_path / 'bad.jpg'
    path.write_bytes(b'not an image')
    budget = CallBudget(1)
    result = run_one(path, spec(), tmp_path / 'cache', offline=False, budget=budget)
    assert result['status'] == 'invalid_image'
    assert budget.used == 0


def test_adapter_code_change_invalidates_cache_identity(tmp_path, monkeypatch):
    from app.v2.integrations import qwen
    from eval.recognition_v2.runner import cache_key
    old = cache_key(b'image', spec(), 0)
    source = tmp_path / 'changed_adapter.py'
    source.write_text('changed transport or request parameters')
    monkeypatch.setattr(qwen, '__file__', str(source))
    assert cache_key(b'image', spec(), 0) != old


@pytest.mark.parametrize('field,value', [('elapsed_ms', float('nan')), ('elapsed_ms', 10 ** 400), ('usage', 'bad'),
                                        ('raw_candidates', {}), ('model', None), ('error', {'bad': True})])
def test_invalid_cached_metadata_is_rejected(tmp_path, field, value):
    import json
    from eval.recognition_v2.runner import CallBudget, cache_key, run_one

    class Provider:
        def recognize(self, *args):
            return {'candidates': []}

    path = photo(tmp_path)
    cache = tmp_path / 'cache'
    run_one(path, spec(), cache, offline=False, budget=CallBudget(1), provider_factory=lambda config: Provider())
    target = cache / (cache_key(path.read_bytes(), spec(), 0) + '.json')
    data = json.loads(target.read_text())
    data[field] = value
    target.write_text(json.dumps(data))
    assert run_one(path, spec(), cache)['status'] == 'offline_missing'


def test_decoder_resource_limit_does_not_escape_invalid_image_result(tmp_path, monkeypatch):
    from eval.recognition_v2 import runner
    path = photo(tmp_path)

    def fail(*args):
        raise Image.DecompressionBombError('too many pixels')

    monkeypatch.setattr(runner.Image, 'open', fail)
    budget = runner.CallBudget(1)
    assert runner.run_one(path, spec(), tmp_path / 'cache', offline=False, budget=budget)['status'] == 'invalid_image'
    assert budget.used == 0


def test_unbounded_model_coordinate_is_failed_result_not_aborted_experiment(tmp_path):
    from eval.recognition_v2.runner import CallBudget, run_one

    class Provider:
        def recognize(self, *args):
            return {'candidates': [{'bbox': [0, 0, 10 ** 400, 1], 'category': 'top'}]}

    result = run_one(photo(tmp_path), spec(), tmp_path / 'cache', offline=False,
                     budget=CallBudget(1), provider_factory=lambda config: Provider())
    assert result['status'] == 'error'
    assert result['error']['code'] == 'EVAL_INVALID_RESULT'


def test_invalid_result_retains_known_usage_for_cost_review(tmp_path):
    from eval.recognition_v2.runner import CallBudget, run_one

    class Provider:
        def recognize(self, *args):
            return {'candidates': 'malformed', '_trace': {'model': 'returned-model', 'usage': {'prompt_tokens': 123}}}

    result = run_one(photo(tmp_path), spec(), tmp_path / 'cache', offline=False,
                     budget=CallBudget(1), provider_factory=lambda config: Provider())
    assert result['status'] == 'error'
    assert result['usage'] == {'prompt_tokens': 123}
    assert result['model'] == 'returned-model'


def test_source_content_change_is_rejected_before_model_call(tmp_path):
    from eval.recognition_v2.runner import CallBudget, run_one
    calls = []
    budget = CallBudget(1)
    result = run_one(photo(tmp_path), spec(), tmp_path / 'cache', offline=False, budget=budget,
                     expected_sha256='0' * 64, provider_factory=lambda config: calls.append(config))
    assert result['status'] == 'invalid_image'
    assert result['error']['code'] == 'EVAL_IMAGE_CHANGED'
    assert calls == [] and budget.used == 0
