import json
from hashlib import sha256

import httpx
import pytest

from app.v2.core.config import V2Settings
from app.v2.integrations.ark import ArkProvider
from app.v2.integrations.qwen import QwenProvider
from app.v2.integrations.recognition import PROMPT, RecognitionFailure, UnconfiguredProvider
from app.v2.jobs.worker import provider_from_settings


@pytest.fixture
def settings_factory(monkeypatch):
    # Exercise defaults without reading a developer's .env or using real keys.
    import os
    for name in tuple(os.environ):
        if name.startswith('V2_'):
            monkeypatch.delenv(name)

    def build(**overrides):
        return V2Settings(_env_file=None, database_url='sqlite://', jwt_secret='test-only',
                          **overrides)
    return build


def test_default_recognition_builds_the_selected_lite_provider(settings_factory):
    settings = settings_factory(ark_api_key='fake-ark-key')
    provider = provider_from_settings(settings)

    assert isinstance(provider, ArkProvider)
    assert provider.model == 'doubao-seed-2-1-lite-260915'
    assert provider.base_url == 'https://ark.cn-beijing.volces.com/api/v3'
    assert settings.outfit_provider == 'disabled'


def test_default_lite_request_keeps_original_prompt_and_safe_trace(settings_factory):
    key = 'NEVER_PERSIST_LITE_KEY'
    settings = settings_factory(ark_api_key=key, qwen_api_key='fake-qwen-key')
    provider = provider_from_settings(settings)
    seen = []
    candidate = {'name': '蓝色上衣', 'category': 'top', 'colors': ['blue'],
                 'pattern': 'solid', 'thickness': 'unknown', 'bbox': None}

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={
            'model': 'doubao-seed-2-1-lite-260915',
            'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30,
                      'unexpected': key},
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'candidates': [{**candidate, 'owners': ['model-invented-owner'], 'selected': True}],
            })}}],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        provider.http_client = client
        result = provider.recognize(b'private-photo-marker')

    assert len(seen) == 1
    request = seen[0]
    body = json.loads(request.content)
    assert str(request.url) == 'https://ark.cn-beijing.volces.com/api/v3/chat/completions'
    assert request.headers['Authorization'] == 'Bearer ' + key
    assert body['model'] == 'doubao-seed-2-1-lite-260915'
    assert body['messages'][0]['content'][0] == {'type': 'text', 'text': PROMPT}
    assert body['response_format'] == {'type': 'json_object'}
    assert body['thinking'] == {'type': 'disabled'}
    assert body['stream'] is False
    assert body['temperature'] == 0
    assert 'enable_thinking' not in body
    assert result['candidates'] == [candidate]
    trace = result['_trace']
    assert trace['provider'] == 'ark'
    assert trace['prompt_hash'] == sha256(PROMPT.encode()).hexdigest()
    assert trace['usage'] == {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30}
    assert json.loads(trace['raw_json']) == {'candidates': [candidate]}
    serialized_trace = json.dumps(trace)
    assert key not in serialized_trace
    assert 'private-photo-marker' not in serialized_trace
    assert 'image_url' not in serialized_trace


def test_default_without_ark_key_returns_honest_manual_result(settings_factory):
    # A Qwen key alone must not silently change the chosen provider.
    provider = provider_from_settings(settings_factory(qwen_api_key='fake-qwen-key'))
    assert isinstance(provider, UnconfiguredProvider)
    with pytest.raises(RecognitionFailure) as caught:
        provider.recognize(b'photo')
    assert caught.value.code == 'RECOGNITION_UNCONFIGURED'
    assert '手动填写' in caught.value.message
    assert caught.value.retryable is False
    assert caught.value.uncertain is False


def test_explicit_qwen_remains_available(settings_factory):
    provider = provider_from_settings(settings_factory(
        recognition_provider='qwen', recognition_model='qwen3.8-flash',
        qwen_api_key='fake-qwen-key', ark_api_key='fake-ark-key'))
    assert isinstance(provider, QwenProvider)
    assert provider.model == 'qwen3.8-flash'
    assert provider.extra_payload() == {'enable_thinking': False}


def test_explicit_disabled_keeps_manual_filling_even_with_keys(settings_factory):
    provider = provider_from_settings(settings_factory(
        recognition_provider='disabled', ark_api_key='fake-ark-key', qwen_api_key='fake-qwen-key'))
    assert isinstance(provider, UnconfiguredProvider)
