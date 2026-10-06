"""Evaluation-only color roles, exercising the real HTTP response adapter."""
import copy
import hashlib
import importlib
import io
import json
from dataclasses import replace
from typing import get_args

import httpx
import pytest
from PIL import Image


def api():
    return importlib.import_module('eval.recognition_v2.color_prompt')


def config(provider='qwen'):
    from eval.recognition_v2.runner import ModelSpec
    return ModelSpec('baseline', provider, 'fixed-model', 'https://example.test/v1', 'TEST_EVAL_KEY')


def candidate(**updates):
    return {'name': '儿童上衣', 'category': 'top', 'primary_colors': ['white'],
            'secondary_colors': ['blue'], 'accent_colors': ['red'], 'pattern': 'solid',
            'thickness': 'unknown', 'bbox': [0, 0, 1, 1], **updates}


def completion(candidates, *, finish_reason='stop', content=None):
    return {'model': 'returned-model', 'usage': {'prompt_tokens': 12, 'completion_tokens': 7,
                                              'total_tokens': 19, 'secret_usage': 'ignored'},
            'choices': [{'finish_reason': finish_reason,
                         'message': {'content': content if content is not None else
                                     json.dumps({'candidates': candidates}, ensure_ascii=False)}}]}


def photo(tmp_path):
    output = io.BytesIO()
    Image.new('RGB', (24, 20), 'white').save(output, format='JPEG')
    path = tmp_path / 'shirt.jpg'
    path.write_bytes(output.getvalue())
    return path


def run_live(tmp_path, *, candidates=None, prompt=None, cache=None, spec=None, budget=None):
    from eval.recognition_v2 import runner
    prompt = api().COLOR_ROLE_PROMPT if prompt is None else prompt
    spec = config() if spec is None else spec
    cache = tmp_path / 'cache' if cache is None else cache
    budget = runner.CallBudget(1) if budget is None else budget
    candidates = [candidate()] if candidates is None else candidates
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=completion(candidates))

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        factory = lambda spec, *, prompt: api().create_color_provider(spec, 'test-key', client, prompt=prompt)
        record = runner.run_one(photo(tmp_path), spec, cache, offline=False, budget=budget,
                                provider_factory=factory, prompt=prompt)
    return record, requests, budget


def test_runner_identity_accepts_explicit_prompt_and_keeps_default_shape():
    from eval.recognition_v2 import runner
    default = runner.cache_identity(b'image', config(), 0)
    custom = runner.cache_identity(b'image', config(), 0, prompt='explicit color roles prompt')
    assert set(default) == {'schema_version', 'image_sha256', 'provider', 'requested_model',
                            'base_url', 'prompt_sha256', 'parameters', 'pipeline', 'run_index'}
    assert custom['prompt_sha256'] == hashlib.sha256(b'explicit color roles prompt').hexdigest()
    assert custom['evaluation_variant'] == 'color_roles_v1'
    assert custom['pipeline']['evaluation_adapter']
    assert 'evaluation_adapter' not in default['pipeline']
    assert custom != default


def test_prompt_defines_roles_and_generic_visual_rules():
    from app.v2.wardrobe.schemas import Color
    prompt = api().COLOR_ROLE_PROMPT
    assert all(field in prompt for field in ('name', 'category', 'pattern', 'thickness', 'bbox',
                                            'primary_colors', 'secondary_colors', 'accent_colors'))
    assert all(color in prompt for color in get_args(Color))
    assert all(rule in prompt for rule in ('逐一', '领口', '袖口', '门襟', '包边', '细长',
                                           '针织', '褶皱', '阴影', '重复次数', '多个', '互斥'))


@pytest.mark.parametrize('provider', ['qwen', 'ark'])
def test_actual_http_body_uses_full_custom_prompt_and_unchanged_parameters(provider):
    from app.v2.integrations.recognition import PROMPT
    from app.v2.recognition.normalize import normalize_result
    from eval.recognition_v2.runner import request_parameters
    captured = []
    prompt = api().COLOR_ROLE_PROMPT + '\n保持完整中文与末尾规则。'

    def transport(request):
        captured.append(request)
        return httpx.Response(200, json=completion([candidate(selected=True, id=42)]))

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        provider_instance = api().create_color_provider(config(provider), 'test-key', client, prompt=prompt)
        result = provider_instance.recognize(b'jpeg-input', 'image/jpeg')
        assert not client.is_closed
    assert len(captured) == 1
    assert str(captured[0].url) == 'https://example.test/v1/chat/completions'
    assert captured[0].headers['Authorization'] == 'Bearer test-key'
    body = json.loads(captured[0].content)
    assert body['model'] == 'fixed-model'
    assert body['messages'][0]['content'][0]['text'] == prompt
    assert body['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert {key: body[key] for key in request_parameters(provider)} == request_parameters(provider)
    assert result['candidates'] == [dict(candidate(), colors=['white', 'blue'])]
    assert normalize_result(result)[0]['colors'] == ['white', 'blue']
    assert result['_trace']['prompt_hash'] == hashlib.sha256(prompt.encode()).hexdigest()
    assert json.loads(result['_trace']['raw_json'])['candidates'][0]['accent_colors'] == ['red']
    assert result['_trace']['usage'] == {'prompt_tokens': 12, 'completion_tokens': 7, 'total_tokens': 19}
    assert result['_trace']['provider'] == provider
    assert 'primary_colors' not in PROMPT


@pytest.mark.parametrize('colors', [
    {'primary_colors': ['unknown'], 'secondary_colors': [], 'accent_colors': []},
    {'primary_colors': ['white', 'blue'], 'secondary_colors': [], 'accent_colors': []},
    {'primary_colors': ['beige'], 'secondary_colors': ['brown', 'black'], 'accent_colors': ['pink']},
])
def test_valid_roles_support_unknown_empty_arrays_and_multiple_primary(colors):
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=completion([candidate(**colors)])))) as client:
        result = api().create_color_provider(config(), 'test-key', client).recognize(b'image')
    raw = result['candidates'][0]
    assert all(raw[field] == value for field, value in colors.items())
    assert raw['colors'] == list(dict.fromkeys(colors['primary_colors'] + colors['secondary_colors']))


INVALID_ROLES = [
    ('missing_primary', {'primary_colors': None}),
    ('missing_secondary', {'secondary_colors': None}),
    ('missing_accent', {'accent_colors': None}),
    ('empty_primary', {'primary_colors': []}),
    ('scalar_role', {'secondary_colors': 'blue'}),
    ('illegal_enum', {'accent_colors': ['navy']}),
    ('nonstring_color', {'secondary_colors': [True]}),
    ('unhashable_color', {'accent_colors': [{}]}),
    ('duplicate_within', {'primary_colors': ['white', 'white']}),
    ('primary_secondary_overlap', {'secondary_colors': ['white']}),
    ('primary_accent_overlap', {'accent_colors': ['white']}),
    ('secondary_accent_overlap', {'accent_colors': ['blue']}),
    ('unknown_mixed', {'primary_colors': ['unknown', 'white']}),
    ('unknown_with_secondary', {'primary_colors': ['unknown']}),
    ('secondary_unknown', {'secondary_colors': ['unknown']}),
    ('accent_unknown', {'accent_colors': ['unknown']}),
]


@pytest.mark.parametrize('name,updates', INVALID_ROLES, ids=[item[0] for item in INVALID_ROLES])
def test_invalid_or_missing_roles_fail_explicitly_without_retry(name, updates):
    from app.v2.integrations.recognition import RecognitionFailure
    raw = candidate(**updates)
    if name.startswith('missing_'):
        raw = {key: value for key, value in raw.items() if value is not None}
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=completion([raw]))

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(RecognitionFailure) as failure:
            api().create_color_provider(config(), 'test-key', client).recognize(b'image')
    assert failure.value.code == 'EVAL_INVALID_COLOR_ROLES'
    assert len(requests) == 1


@pytest.mark.parametrize('status,payload,code', [
    (200, completion([candidate()], finish_reason='length'), 'RECOGNITION_INVALID_RESPONSE'),
    (200, completion([], content='{broken'), 'RECOGNITION_INVALID_RESPONSE'),
    (200, completion([], content='{"candidates":[null]}'), 'RECOGNITION_INVALID_RESPONSE'),
    (200, completion([], content='{"candidates":[{"bbox":[NaN]}]}'), 'RECOGNITION_INVALID_RESPONSE'),
    (429, {}, 'RECOGNITION_RATE_LIMITED'),
    (503, {}, 'RECOGNITION_UNAVAILABLE'),
    (401, {}, 'RECOGNITION_CONFIGURATION_ERROR'),
])
def test_adapter_reuses_production_envelope_http_and_json_failures(status, payload, code):
    from app.v2.integrations.recognition import RecognitionFailure
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(status, json=payload)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(RecognitionFailure) as failure:
            api().create_color_provider(config(), 'test-key', client).recognize(b'image')
    assert failure.value.code == code
    assert len(requests) == 1


def test_cache_isolated_by_full_prompt_and_evaluation_adapter_source(tmp_path, monkeypatch):
    from eval.recognition_v2 import runner
    prompt = api().COLOR_ROLE_PROMPT
    key = runner.cache_key(b'image', config(), 0, prompt=prompt)
    assert key != runner.cache_key(b'image', config(), 0)
    assert key != runner.cache_key(b'image', config(), 0, prompt=prompt + '\n规则')
    assert key != runner.cache_key(b'image', config(), 1, prompt=prompt)
    assert key != runner.cache_key(b'image', replace(config(), model='other'), 0, prompt=prompt)
    default_key = runner.cache_key(b'image', config(), 0)
    source = tmp_path / 'changed_color_adapter.py'
    source.write_text('different color role adapter')
    monkeypatch.setattr(api(), '__file__', str(source))
    assert key != runner.cache_key(b'image', config(), 0, prompt=prompt)
    assert default_key == runner.cache_key(b'image', config(), 0)


def test_live_roles_preserved_and_offline_replay_scores_legacy_colors(tmp_path):
    from eval.recognition_v2 import runner
    from eval.recognition_v2.crop_pilot import score_crop
    live, requests, budget = run_live(tmp_path)
    assert live['status'] == 'ok'
    assert live['raw_candidates'][0]['primary_colors'] == ['white']
    assert live['raw_candidates'][0]['secondary_colors'] == ['blue']
    assert live['raw_candidates'][0]['accent_colors'] == ['red']
    assert live['raw_candidates'][0]['colors'] == live['candidates'][0]['colors'] == ['white', 'blue']
    assert 'accent_colors' not in live['candidates'][0]
    assert score_crop(live['candidates'], {'category': 'top', 'colors': ['white', 'blue'],
                                         'pattern': 'solid'})['joint_correct'] == 1
    cached = runner.run_one(photo(tmp_path), config(), tmp_path / 'cache', prompt=api().COLOR_ROLE_PROMPT,
                            provider_factory=lambda *args, **kwargs: pytest.fail('offline network'))
    assert cached['source'] == 'cache'
    assert cached['raw_candidates'] == live['raw_candidates']
    assert cached['candidates'] == live['candidates']
    assert budget.used == len(requests) == 1
    assert runner.run_one(photo(tmp_path), config(), tmp_path / 'cache')['source'] == 'offline_missing'
    assert runner.run_one(photo(tmp_path), config(), tmp_path / 'cache',
                          prompt=api().COLOR_ROLE_PROMPT + '\n新规则')['source'] == 'offline_missing'


@pytest.mark.parametrize('tamper', ['missing_role', 'overlap', 'illegal', 'duplicate',
                                  'derived_color', 'normalized_color', 'unknown_mixed'])
def test_custom_cache_rejects_role_and_derived_color_tampering(tmp_path, tamper):
    from eval.recognition_v2 import runner
    live, _, _ = run_live(tmp_path)
    target = next((tmp_path / 'cache').glob('*.json'))
    record = copy.deepcopy(live)
    raw = record['raw_candidates'][0]
    if tamper == 'missing_role':
        del raw['accent_colors']
    elif tamper == 'overlap':
        raw['accent_colors'] = ['white']
    elif tamper == 'illegal':
        raw['secondary_colors'] = ['navy']
    elif tamper == 'duplicate':
        raw['primary_colors'] = ['white', 'white']
    elif tamper == 'derived_color':
        raw['colors'] = ['white', 'blue', 'red']
    elif tamper == 'normalized_color':
        record['candidates'][0]['colors'] = ['white']
    else:
        raw['primary_colors'] = ['unknown', 'white']
    target.write_text(json.dumps(record))
    replay = runner.run_one(photo(tmp_path), config(), tmp_path / 'cache', prompt=api().COLOR_ROLE_PROMPT)
    assert replay['status'] == 'offline_missing'


def test_default_mode_replays_cache_with_the_preexisting_identity_structure(tmp_path):
    from app.v2.integrations.recognition import PROMPT
    from app.v2.recognition.normalize import normalize_result
    from eval.recognition_v2 import runner
    path = photo(tmp_path)
    spec = config()
    identity = {'schema_version': 1, 'image_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'provider': spec.provider, 'requested_model': spec.model, 'base_url': spec.base_url,
                'prompt_sha256': hashlib.sha256(PROMPT.encode()).hexdigest(),
                'parameters': runner.request_parameters(spec.provider), 'pipeline': runner.pipeline_fingerprint(),
                'run_index': 0}
    raw = [{'name': '上衣', 'category': 'top', 'colors': ['white'], 'pattern': 'solid',
            'thickness': 'unknown', 'bbox': None}]
    record = {'identity': identity, 'source': 'live', 'status': 'ok',
              'candidates': normalize_result({'candidates': raw}), 'raw_candidates': raw,
              'model': spec.model, 'elapsed_ms': 1, 'return_ms': 2, 'usage': {}, 'error': None}
    key = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / (key + '.json')).write_text(json.dumps(record))
    replay = runner.run_one(path, spec, cache)
    assert replay['source'] == 'cache'
    assert replay['candidates'] == record['candidates']


def test_custom_offline_mode_never_creates_provider_or_cache(tmp_path):
    from eval.recognition_v2 import runner
    record = runner.run_one(photo(tmp_path), config(), tmp_path / 'cache', prompt=api().COLOR_ROLE_PROMPT,
                            provider_factory=lambda *args, **kwargs: pytest.fail('offline provider'))
    assert record['status'] == 'offline_missing'
    assert not (tmp_path / 'cache').exists()


def test_custom_cache_write_failure_precedes_provider_and_paid_budget(tmp_path):
    from eval.recognition_v2 import runner
    cache = tmp_path / 'blocked'
    cache.write_text('cannot be a cache directory')
    budget = runner.CallBudget(1)
    with pytest.raises(OSError):
        runner.run_one(photo(tmp_path), config(), cache, prompt=api().COLOR_ROLE_PROMPT,
                       offline=False, budget=budget,
                       provider_factory=lambda *args, **kwargs: pytest.fail('provider created before preflight'))
    assert budget.used == 0


def test_custom_exhausted_budget_and_changed_source_precede_provider(tmp_path):
    from eval.recognition_v2 import runner
    path = photo(tmp_path)
    budget = runner.CallBudget(1)
    budget.take()
    factory = lambda *args, **kwargs: pytest.fail('provider must not be created')
    with pytest.raises(runner.CallLimitExceeded):
        runner.run_one(path, config(), tmp_path / 'cache', prompt=api().COLOR_ROLE_PROMPT,
                       offline=False, budget=budget, provider_factory=factory)
    assert not (tmp_path / 'cache').exists()
    unchanged_budget = runner.CallBudget(1)
    record = runner.run_one(path, config(), tmp_path / 'cache', prompt=api().COLOR_ROLE_PROMPT,
                            offline=False, budget=unchanged_budget, expected_sha256='0' * 64,
                            provider_factory=factory)
    assert record['error']['code'] == 'EVAL_IMAGE_CHANGED'
    assert unchanged_budget.used == 0


def test_bad_role_output_is_charged_once_but_not_successfully_cached(tmp_path):
    live, requests, budget = run_live(tmp_path, candidates=[candidate(accent_colors=['blue'])])
    assert live['status'] == 'error'
    assert live['error']['code'] == 'EVAL_INVALID_COLOR_ROLES'
    assert live['usage'] == {'prompt_tokens': 12, 'completion_tokens': 7, 'total_tokens': 19}
    assert live['model'] == 'returned-model'
    assert len(requests) == budget.used == 1
    assert not list((tmp_path / 'cache').glob('*.json'))


def test_custom_provider_prompt_mismatch_cannot_pollute_cache(tmp_path):
    from eval.recognition_v2 import runner
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=completion([candidate()])))) as client:
        record = runner.run_one(photo(tmp_path), config(), tmp_path / 'cache',
                                prompt=api().COLOR_ROLE_PROMPT + '\n新规则', offline=False,
                                budget=runner.CallBudget(1), provider_factory=lambda spec, *, prompt:
                                api().create_color_provider(spec, 'test-key', client))
    assert record['status'] == 'error'
    assert record['error']['code'] == 'EVAL_PROMPT_MISMATCH'
    assert not list((tmp_path / 'cache').glob('*.json'))


@pytest.mark.parametrize('prompt', ['', '  ', 123])
def test_invalid_custom_prompt_rejected_before_input_or_provider(tmp_path, prompt):
    from eval.recognition_v2 import runner
    with pytest.raises(ValueError, match='prompt'):
        runner.run_one(tmp_path / 'absent.jpg', config(), tmp_path / 'cache', prompt=prompt)


def test_import_and_provider_creation_do_not_load_environment_or_open_connections(monkeypatch):
    from eval.recognition_v2 import runner
    module = api()

    def forbidden(*args, **kwargs):
        pytest.fail('environment or connection touched before live recognize')

    with monkeypatch.context() as patch:
        patch.setattr(httpx, 'Client', forbidden)
        patch.setattr(runner.os, 'getenv', forbidden)
        patch.setattr(type(runner.os.environ), 'get', forbidden)
        importlib.reload(module)
        importlib.reload(runner)
        instance = module.create_color_provider(config(), 'test-key')
        assert instance.http_client is None
