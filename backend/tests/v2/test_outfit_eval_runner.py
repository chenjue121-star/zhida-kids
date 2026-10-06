import hashlib
import importlib
import io
import json
from copy import deepcopy
from dataclasses import replace

import httpx
from PIL import Image
import pytest

from eval.recognition_v2.runner import CallBudget, CallLimitExceeded, ModelSpec
from tests.v2.test_outfit_eval_protocol import case


def runner():
    try:
        return importlib.import_module('eval.outfits_v2.runner')
    except ModuleNotFoundError:
        pytest.fail('Outfit evaluation runner is not implemented')


def spec():
    return ModelSpec('mock', 'qwen', 'fixed-model', 'https://example.test/v1', 'OUTFIT_EVAL_TEST_KEY')


def with_photos(tmp_path):
    value = case()
    value['photos'] = {}
    for gid, color in [('1', 'red'), ('2', 'blue'), ('3', 'white')]:
        output = io.BytesIO()
        Image.new('RGB', (12, 10), color).save(output, format='JPEG')
        raw = output.getvalue()
        (tmp_path / f'{gid}.jpg').write_bytes(raw)
        value['photos'][gid] = {'path': f'{gid}.jpg', 'sha256': hashlib.sha256(raw).hexdigest()}
    return value


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)


def response(content='{"garment_ids":["1","2"],"reason":"配色协调"}'):
    return httpx.Response(200, json={'model': 'returned-model', 'usage': {'prompt_tokens': 13},
                                   'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})


@pytest.mark.parametrize('provider,thinking', [
    ('qwen', {'enable_thinking': False}),
    ('ark', {'thinking': {'type': 'disabled'}}),
])
@pytest.mark.parametrize('arm', ['attributes', 'photos'])
def test_both_arms_disable_thinking_with_fixed_generation_limits(tmp_path, provider, thinking, arm):
    value = with_photos(tmp_path)
    model = replace(spec(), provider=provider)
    body = runner()._body(value, model, arm, runner()._photos(value, tmp_path))
    parameters = {key: item for key, item in body.items() if key not in {'model', 'messages'}}
    assert parameters == {'temperature': .2, 'max_tokens': 500, **thinking}


def test_ark_thinking_parameters_are_part_of_offline_cache_identity(tmp_path, monkeypatch):
    value = with_photos(tmp_path)
    model = replace(spec(), provider='ark')
    original = runner().run_one(value, model, tmp_path, tmp_path/'cache', arm='photos')
    assert original['status'] == 'offline_missing'
    assert original['identity']['parameters'] == {
        'temperature': .2, 'max_tokens': 500, 'thinking': {'type': 'disabled'},
    }
    monkeypatch.setattr(runner(), 'request_parameters', lambda provider, output_mode='prompt_only': {
        'temperature': .2, 'max_tokens': 500, 'thinking': {'type': 'enabled'},
    })
    changed = runner().run_one(value, model, tmp_path, tmp_path/'cache', arm='photos')
    assert changed['status'] == 'offline_missing'
    assert changed['identity'] != original['identity']
    assert hashlib.sha256(runner()._json(changed['identity']).encode()).hexdigest() != \
        hashlib.sha256(runner()._json(original['identity']).encode()).hexdigest()


@pytest.mark.parametrize('provider', ['qwen', 'ark'])
def test_explicit_prompt_only_preserves_the_default_request_body(tmp_path, provider):
    value, model = with_photos(tmp_path), replace(spec(), provider=provider)
    photos = runner()._photos(value, tmp_path)
    for arm in ('attributes', 'photos'):
        default = runner()._body(value, model, arm, photos)
        explicit = runner()._body(value, model, arm, photos, output_mode='prompt_only')
        assert explicit == default
        assert explicit['messages'][0]['content'] == runner()._prompt()
        assert 'response_format' not in explicit


@pytest.mark.parametrize('provider', ['qwen', 'ark'])
def test_json_object_arms_share_constraints_and_text_with_only_photo_difference(tmp_path, provider):
    value, model = with_photos(tmp_path), replace(spec(), provider=provider)
    photos = runner()._photos(value, tmp_path)
    attr, photo = [runner()._body(value, model, arm, photos, output_mode='json_object')
                   for arm in ('attributes', 'photos')]
    assert attr['response_format'] == photo['response_format'] == {'type': 'json_object'}
    assert {key: value for key, value in attr.items() if key != 'messages'} == \
        {key: value for key, value in photo.items() if key != 'messages'}
    assert attr['temperature'] == .2 and attr['max_tokens'] == 500
    expected_thinking = {'enable_thinking': False} if provider == 'qwen' else {'thinking': {'type': 'disabled'}}
    assert {key: attr[key] for key in expected_thinking} == expected_thinking
    assert attr['messages'][0] == photo['messages'][0]
    prompt = attr['messages'][0]['content']
    assert prompt.startswith(runner()._prompt())
    assert '{"garment_ids":["ID_A","ID_B"],"reason":"简短中文理由"}' in prompt
    assert '抽象占位' in prompt and '字符串数组' in prompt and '代码围栏' in prompt
    assert '原候选' in prompt and '整组' in prompt
    assert '33' not in prompt and '54' not in prompt
    assert attr['messages'][1]['content'] == [block for block in photo['messages'][1]['content']
                                            if block['type'] == 'text']
    assert len([block for block in photo['messages'][1]['content'] if block['type'] == 'image_url']) == 3


def test_output_mode_cache_identity_matches_the_sent_prompt_and_parameters(tmp_path):
    value, model = with_photos(tmp_path), replace(spec(), provider='ark')
    identities = []
    for mode in ('prompt_only', 'json_object'):
        record = runner().run_one(value, model, tmp_path, tmp_path/'cache', arm='photos', output_mode=mode)
        body = runner()._body(value, model, 'photos', runner()._photos(value, tmp_path), output_mode=mode)
        identity = record['identity']
        assert record['status'] == 'offline_missing'
        assert identity['output_mode'] == mode
        assert identity['prompt_sha256'] == hashlib.sha256(body['messages'][0]['content'].encode()).hexdigest()
        assert identity['parameters'] == {key: item for key, item in body.items() if key not in {'model', 'messages'}}
        identities.append(identity)
    assert identities[0]['prompt_sha256'] != identities[1]['prompt_sha256']
    assert identities[0]['parameters'] != identities[1]['parameters']


def test_switching_output_mode_cannot_replay_a_prompt_only_cache(tmp_path):
    value, model = with_photos(tmp_path), spec()
    original = runner().run_one(value, model, tmp_path, tmp_path/'cache', arm='attributes', output_mode='prompt_only')
    selection = runner().validate_selection(value, {'garment_ids': ['1', '2']})
    frozen = {**original, 'source': 'live', 'status': 'ok', 'selection': selection,
              'chosen_ids': ['1', '2'], 'usable_ids': ['1', '2'], 'fallback': False,
              'elapsed_ms': 1, 'return_ms': 1, 'error': None}
    path = tmp_path/'cache'/(hashlib.sha256(runner()._json(original['identity']).encode()).hexdigest() + '.json')
    runner()._write_cache(path, frozen)
    assert runner().run_one(value, model, tmp_path, tmp_path/'cache', arm='attributes', output_mode='prompt_only')['source'] == 'cache'
    changed = runner().run_one(value, model, tmp_path, tmp_path/'cache', arm='attributes', output_mode='json_object')
    assert changed['status'] == changed['source'] == 'offline_missing'
    assert changed['identity'] != original['identity']


@pytest.mark.parametrize('mode', ['', 'json_schema', None])
def test_invalid_output_mode_is_rejected_before_input_or_environment_access(tmp_path, monkeypatch, mode):
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid output mode must not read inputs or call HTTP')
    monkeypatch.setattr(runner(), '_photos', forbidden)
    budget = CallBudget(1)
    with pytest.raises(ValueError, match='output_mode'):
        runner().request_parameters('ark', output_mode=mode)
    with pytest.raises(ValueError, match='output_mode'):
        runner().run_one({}, spec(), tmp_path, tmp_path/'cache', arm='photos', output_mode=mode,
                         offline=False, budget=budget, http_client=object())
    assert budget.used == 0 and not (tmp_path/'cache').exists()


@pytest.mark.parametrize('content,status,code', [
    ('{"garment_ids":["1","2"],"reason":"配色协调"}', 'ok', 'OK'),
    ('{"garment_ids":["ID_A","ID_B"]}', 'invalid_selection', 'INVALID_IDS'),
    ('{"garment_ids":"1,2"}', 'invalid_selection', 'INVALID_IDS'),
    ('{"garment_ids":["1","3"]}', 'invalid_selection', 'NOT_DISPLAYED_COMBINATION'),
    ('```json\n{"garment_ids":["1","2"]}\n```', 'invalid_json', 'INVALID_JSON'),
])
def test_json_object_mode_sends_format_and_keeps_strict_selection_validation(tmp_path, monkeypatch, content, status, code):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value = with_photos(tmp_path)
    def handler(request):
        body = json.loads(request.content)
        assert body['response_format'] == {'type': 'json_object'}
        assert '抽象占位' in body['messages'][0]['content']
        return response(content)
    with client(handler) as http:
        result = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='photos',
                                  output_mode='json_object', offline=False, budget=CallBudget(1), http_client=http)
    assert result['status'] == status and result['selection']['code'] == code
    assert result['identity']['parameters']['response_format'] == {'type': 'json_object'}
    assert result['chosen_ids'] == (['1', '2'] if status == 'ok' else [])
    assert result['fallback'] is (status != 'ok')


def test_unsupported_json_object_is_not_retried_as_prompt_only(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value, calls, budget = with_photos(tmp_path), [], CallBudget(2)
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(400, text='response format unsupported')
    with client(handler) as http:
        result = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='attributes',
                                  output_mode='json_object', offline=False, budget=budget, http_client=http)
    assert result['status'] == 'http_error'
    assert budget.used == len(calls) == 1
    assert calls[0]['response_format'] == {'type': 'json_object'}


def test_attribute_and_photo_arms_have_identical_text_and_unique_bound_images(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value, requests = with_photos(tmp_path), []
    value['combinations'].append(['1', '2', '4'])
    value['photos']['4'] = dict(value['photos']['3'])
    def handler(request):
        requests.append(json.loads(request.content))
        return response()
    with client(handler) as http:
        for arm in ('attributes', 'photos'):
            result = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm=arm,
                                      offline=False, budget=CallBudget(1), http_client=http)
            assert result['status'] == 'ok'
    attr, photo = requests
    assert attr['messages'][0] == photo['messages'][0]
    assert attr['temperature'] == photo['temperature'] == .2
    assert attr['max_tokens'] == photo['max_tokens'] == 500
    content_a, content_p = attr['messages'][1]['content'], photo['messages'][1]['content']
    assert content_a == [block for block in content_p if block['type'] == 'text']
    assert len([block for block in content_p if block['type'] == 'image_url']) == 4
    assert sum(block['text'] == 'garment_id=1' for block in content_a) == 1
    assert all(block['image_url']['url'].startswith('data:image/jpeg;base64,')
               for block in content_p if block['type'] == 'image_url')
    assert 'must-not-leak' not in json.dumps(requests)


def test_offline_missing_never_calls_http_or_reads_environment(tmp_path, monkeypatch):
    value, calls = with_photos(tmp_path), []
    monkeypatch.setattr('eval.recognition_v2.runner.os.environ', {})
    with client(lambda request: calls.append(request)) as http:
        result = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='photos', http_client=http)
    assert result['status'] == result['source'] == 'offline_missing'
    assert result['usable_ids'] == [] and calls == []
    assert not (tmp_path/'cache').exists()


@pytest.mark.parametrize('content,status,code', [
    ('not JSON SECRET-response', 'invalid_json', 'INVALID_JSON'),
    ('{"garment_ids":["1","1"]}', 'invalid_selection', 'DUPLICATE_IDS'),
    ('{"garment_ids":["999"]}', 'invalid_selection', 'UNKNOWN_IDS'),
])
def test_failed_model_results_are_cached_replayed_and_fall_back_without_model_success(tmp_path, monkeypatch, content, status, code):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'SECRET-fixture-key')
    value, calls = with_photos(tmp_path), []
    def handler(request):
        calls.append(1)
        return response(content)
    with client(handler) as http:
        live = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='attributes',
                                offline=False, budget=CallBudget(1), http_client=http)
        cached = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='attributes', http_client=http)
    assert live['status'] == cached['status'] == status
    assert live['selection']['code'] == code
    assert live['fallback'] is True and live['chosen_ids'] == [] and live['usable_ids'] == value['baseline_ids']
    assert cached['source'] == 'cache' and live['elapsed_ms'] == cached['elapsed_ms']
    assert live['usage'] == {'prompt_tokens': 13} and live['model'] == 'returned-model'
    assert len(calls) == 1
    assert 'SECRET' not in json.dumps(live) and 'SECRET' not in next((tmp_path/'cache').glob('*.json')).read_text()


def test_http_error_is_cached_and_safe_without_automatic_retry(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value, calls, budget = with_photos(tmp_path), [], CallBudget(2)
    def handler(request):
        calls.append(1)
        return httpx.Response(429, text='private server response')
    with client(handler) as http:
        result = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='photos',
                                  offline=False, budget=budget, http_client=http)
        cached = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='photos', http_client=http)
    assert result['status'] == cached['status'] == 'http_error'
    assert budget.used == len(calls) == 1 and cached['source'] == 'cache'
    assert 'private server response' not in json.dumps(result)


@pytest.mark.parametrize('change', ['hash', 'traversal', 'absolute', 'missing', 'symlink'])
def test_photo_mutation_or_unsafe_path_blocks_both_arms_before_spending(tmp_path, monkeypatch, change):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value, calls = with_photos(tmp_path), []
    if change == 'hash':
        value['photos']['1']['sha256'] = '0'*64
    elif change == 'traversal':
        value['photos']['1']['path'] = '../1.jpg'
    elif change == 'absolute':
        value['photos']['1']['path'] = str(tmp_path/'1.jpg')
    elif change == 'missing':
        (tmp_path/'1.jpg').unlink()
    else:
        (tmp_path/'escape.jpg').symlink_to(tmp_path.parent/'outside.jpg')
        value['photos']['1']['path'] = 'escape.jpg'
    with client(lambda request: calls.append(request)) as http:
        for arm in ('attributes', 'photos'):
            budget = CallBudget(1)
            result = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm=arm,
                                      offline=False, budget=budget, http_client=http)
            assert result['status'] == 'invalid_input' and budget.used == 0
    assert calls == [] and not (tmp_path/'cache').exists()


def test_empty_case_stops_without_photos_key_or_budget(tmp_path):
    value = case()
    value.update(combinations=[], baseline_ids=[], photos={})
    result = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='photos', offline=False)
    assert result['status'] == 'no_candidates' and result['chosen_ids'] == result['usable_ids'] == []


def test_live_requires_budget_and_cap_is_checked_before_client_call(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value = with_photos(tmp_path)
    with pytest.raises(ValueError, match='budget'):
        runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='attributes', offline=False)
    budget = CallBudget(1)
    budget.take()
    with pytest.raises(CallLimitExceeded):
        runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='attributes', offline=False, budget=budget)


def test_case_model_arm_and_repeat_changes_invalidate_cache(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value = with_photos(tmp_path)
    with client(lambda request: response()) as http:
        live = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='attributes',
                                offline=False, budget=CallBudget(1), http_client=http)
    reversed_case = deepcopy(value)
    reversed_case['combinations'].reverse()
    for frozen, model, arm, repeat in [(reversed_case, spec(), 'attributes', 0),
                                       (value, replace(spec(), model='new-model'), 'attributes', 0),
                                       (value, spec(), 'photos', 0), (value, spec(), 'attributes', 1)]:
        result = runner().run_one(frozen, model, tmp_path, tmp_path/'cache', arm=arm, run_index=repeat)
        assert result['status'] == 'offline_missing' and result['identity'] != live['identity']


def test_modified_cache_selection_cannot_be_replayed_as_success(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value = with_photos(tmp_path)
    with client(lambda request: response()) as http:
        runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='attributes',
                          offline=False, budget=CallBudget(1), http_client=http)
    path = next((tmp_path/'cache').glob('*.json'))
    data = json.loads(path.read_text())
    data['selection']['garment_ids'] = ['999']
    path.write_text(json.dumps(data))
    assert runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='attributes')['status'] == 'offline_missing'


def test_nontext_completion_is_not_accepted_as_model_json(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value = with_photos(tmp_path)
    def handler(request):
        return httpx.Response(200, json={'usage': {'prompt_tokens': 9}, 'choices': [
            {'message': {'content': {'garment_ids': ['1', '2']}}}]})
    with client(handler) as http:
        result = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='attributes',
                                  offline=False, budget=CallBudget(1), http_client=http)
    assert result['status'] == 'invalid_json' and result['usage'] == {'prompt_tokens': 9}


def test_cache_rejects_a_boolean_combination_index(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value = with_photos(tmp_path)
    with client(lambda request: response()) as http:
        runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='attributes',
                          offline=False, budget=CallBudget(1), http_client=http)
    path = next((tmp_path/'cache').glob('*.json'))
    data = json.loads(path.read_text())
    data['selection']['combination_index'] = False
    path.write_text(json.dumps(data))
    assert runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='attributes')['status'] == 'offline_missing'


def test_timeout_is_safe_cached_and_not_retried(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value, calls, budget = with_photos(tmp_path), [], CallBudget(2)
    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout('PRIVATE-secret-response', request=request)
    with client(handler) as http:
        live = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='photos',
                                offline=False, budget=budget, http_client=http)
        cached = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='photos', http_client=http)
    assert live['status'] == cached['status'] == 'request_error'
    assert cached['source'] == 'cache' and len(calls) == budget.used == 1
    assert 'PRIVATE' not in json.dumps(live)


def test_unwritable_cache_path_blocks_http_before_budget_is_consumed(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value, calls, budget = with_photos(tmp_path), [], CallBudget(1)
    cache_file = tmp_path / 'cache-is-file'
    cache_file.write_text('original bytes')
    def handler(request):
        calls.append(1)
        return response()
    with client(handler) as http:
        result = runner().run_one(value, spec(), tmp_path, cache_file, arm='attributes',
                                  offline=False, budget=budget, http_client=http)
    assert result['status'] == 'invalid_input'
    assert result['error'] == {'code': 'CACHE_UNWRITABLE'}
    assert calls == [] and budget.used == 0
    assert cache_file.read_text() == 'original bytes'


def test_cache_write_failure_after_call_keeps_the_model_result(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTFIT_EVAL_TEST_KEY', 'fixture-key')
    value, calls, budget = with_photos(tmp_path), [], CallBudget(1)
    def handler(request):
        calls.append(1)
        return response()
    def fail_cache_write(*args):
        raise OSError('PRIVATE-filesystem-details')
    monkeypatch.setattr(runner(), '_write_cache', fail_cache_write)
    with client(handler) as http:
        result = runner().run_one(value, spec(), tmp_path, tmp_path/'cache', arm='attributes',
                                  offline=False, budget=budget, http_client=http)
    assert result['status'] == 'ok' and result['chosen_ids'] == ['1', '2']
    assert result['cache_error'] == {'code': 'CACHE_WRITE_FAILED'}
    assert result['usage'] == {'prompt_tokens': 13} and budget.used == len(calls) == 1
    assert 'PRIVATE' not in json.dumps(result)
