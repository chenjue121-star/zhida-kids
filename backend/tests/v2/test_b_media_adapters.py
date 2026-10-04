from __future__ import annotations

import base64
import hashlib
import io
import json
import stat

import httpx
import pytest
from PIL import Image, PngImagePlugin

from app.v2.core.errors import DomainError


def image_bytes(mode='RGB', size=(12, 8), image_format='PNG', **save_kwargs):
    output = io.BytesIO()
    Image.new(mode, size, 0).save(output, format=image_format, **save_kwargs)
    return output.getvalue()


def test_normalize_verifies_pixels_and_returns_rgb_jpeg_with_verified_hash():
    from app.v2.media.service import normalize_image
    raw = image_bytes(mode='P')
    normalized, digest, width, height = normalize_image(raw, 'image/png')
    with Image.open(io.BytesIO(normalized)) as result:
        assert result.format == 'JPEG'
        assert result.mode == 'RGB'
        assert result.size == (width, height) == (12, 8)
    assert digest == hashlib.sha256(normalized).hexdigest()
    assert normalize_image(raw, 'image/png') == (normalized, digest, width, height)


def test_normalize_corrects_exif_rotation_and_removes_exif():
    from app.v2.media.service import normalize_image
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = 'Private photo metadata'
    raw = image_bytes(image_format='JPEG', exif=exif)
    normalized, _, width, height = normalize_image(raw, 'image/jpeg')
    assert (width, height) == (8, 12)
    with Image.open(io.BytesIO(normalized)) as result:
        assert not result.getexif()


def test_normalize_discards_png_metadata():
    from app.v2.media.service import normalize_image
    info = PngImagePlugin.PngInfo()
    info.add_text('location', 'Private place')
    normalized, _, _, _ = normalize_image(image_bytes(pnginfo=info), 'image/png')
    with Image.open(io.BytesIO(normalized)) as result:
        assert 'location' not in result.info


def test_normalize_composites_transparent_pixels_on_white():
    from app.v2.media.service import normalize_image
    normalized, _, _, _ = normalize_image(image_bytes(mode='RGBA'), 'image/png')
    with Image.open(io.BytesIO(normalized)) as result:
        assert all(channel >= 250 for channel in result.getpixel((0, 0)))


@pytest.mark.parametrize('raw', [b'', b'not an image', image_bytes()[:25]])
def test_normalize_rejects_empty_invalid_and_truncated_content(raw):
    from app.v2.media.service import normalize_image
    with pytest.raises(DomainError) as error:
        normalize_image(raw, 'image/png')
    assert error.value.status == 422


@pytest.mark.parametrize('content_type', ['text/plain', 'image/gif', 'image/jpeg'])
def test_normalize_rejects_unsupported_or_mismatched_content_type(content_type):
    from app.v2.media.service import normalize_image
    with pytest.raises(DomainError) as error:
        normalize_image(image_bytes(), content_type)
    assert error.value.status == 422


def test_normalize_enforces_size_before_decode():
    from app.v2.media.service import normalize_image
    with pytest.raises(DomainError) as error:
        normalize_image(b'not even an image', 'image/png', max_bytes=4)
    assert error.value.status == 413


def test_normalize_rejects_decompression_bomb(monkeypatch):
    from app.v2.media.service import normalize_image
    raw = image_bytes(size=(30, 30))
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 100)
    with pytest.raises(DomainError) as error:
        normalize_image(raw, 'image/png')
    assert error.value.status == 413


def test_normalize_rejects_animated_webp():
    from app.v2.media.service import normalize_image
    output = io.BytesIO()
    Image.new('RGB', (8, 8), 'red').save(
        output, format='WEBP', save_all=True,
        append_images=[Image.new('RGB', (8, 8), 'blue')], duration=50, loop=0,
    )
    with pytest.raises(DomainError) as error:
        normalize_image(output.getvalue(), 'image/webp')
    assert error.value.status == 422


def test_file_storage_reuses_hash_only_within_a_family_and_keeps_private_permissions(tmp_path):
    from app.v2.media.storage import FileStorage
    storage = FileStorage(tmp_path / 'private')
    content = b'normalized jpeg fixture'
    digest = hashlib.sha256(content).hexdigest()
    first = storage.put(7, digest, content)
    assert storage.put(7, digest, content) == first
    second = storage.put(8, digest, content)
    assert second != first
    assert storage.get(first) == storage.get(second) == content
    assert not stat.S_IMODE((tmp_path / 'private' / first).stat().st_mode) & 0o077


@pytest.mark.parametrize('key', ['../outside', '/etc/passwd', 'families/7/../8/file.jpg', r'..\outside', 'https://example.com/image.jpg'])
def test_file_storage_rejects_path_traversal(tmp_path, key):
    from app.v2.media.storage import FileStorage
    with pytest.raises(DomainError) as error:
        FileStorage(tmp_path).get(key)
    assert error.value.status == 422


def test_file_storage_rejects_symlink_escape(tmp_path):
    from app.v2.media.storage import FileStorage
    private = tmp_path / 'private'
    outside = tmp_path / 'outside'
    outside.mkdir()
    storage = FileStorage(private)
    content = b'jpeg fixture'
    digest = hashlib.sha256(content).hexdigest()
    key = storage.put(7, digest, content)
    destination = private / key
    destination.unlink()
    (outside / 'secret').write_bytes(b'secret')
    destination.symlink_to(outside / 'secret')
    with pytest.raises(DomainError) as error:
        storage.get(key)
    assert error.value.status == 422


def test_file_storage_rejects_symlink_alias_into_another_family(tmp_path):
    from app.v2.media.storage import FileStorage
    storage = FileStorage(tmp_path)
    content = b'jpeg fixture'
    digest = hashlib.sha256(content).hexdigest()
    first = storage.put(7, digest, content)
    second = storage.put(8, digest, content)
    destination = tmp_path / first
    destination.unlink()
    destination.symlink_to(tmp_path / second)
    with pytest.raises(DomainError) as error:
        storage.get(first)
    assert error.value.status == 422
    with pytest.raises(DomainError):
        storage.put(7, digest, content)


def test_file_storage_rejects_family_directory_symlink_before_writing(tmp_path):
    from app.v2.media.storage import FileStorage
    storage = FileStorage(tmp_path)
    content = b'jpeg fixture'
    digest = hashlib.sha256(content).hexdigest()
    storage.put(8, digest, content)
    (tmp_path / 'families' / '7').symlink_to(tmp_path / 'families' / '8', target_is_directory=True)
    with pytest.raises(DomainError) as error:
        storage.put(7, digest, content)
    assert error.value.status == 422


def test_file_storage_concurrent_hash_publication_is_atomic(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.v2.media.storage import FileStorage
    storage = FileStorage(tmp_path)
    content = b'jpeg fixture' * 1000
    digest = hashlib.sha256(content).hexdigest()
    barrier = Barrier(4)
    def publish():
        barrier.wait(timeout=5)
        return storage.put(7, digest, content)
    with ThreadPoolExecutor(max_workers=4) as pool:
        keys = list(pool.map(lambda unused: publish(), range(4)))
    assert len(set(keys)) == 1
    assert storage.get(keys[0]) == content
    assert not list(tmp_path.rglob('.upload-*'))


def test_file_storage_rejects_unverified_digest_and_invalid_family(tmp_path):
    from app.v2.media.storage import FileStorage
    storage = FileStorage(tmp_path)
    for family, digest in [(0, 'a' * 64), (7, '../outside'), (7, 'a' * 64)]:
        with pytest.raises(DomainError) as error:
            storage.put(family, digest, b'actual content')
        assert error.value.status == 422


def test_missing_storage_asset_is_domain_not_found(tmp_path):
    from app.v2.media.storage import FileStorage
    with pytest.raises(DomainError) as error:
        FileStorage(tmp_path).get('families/7/aa/' + 'a' * 64 + '.jpg')
    assert error.value.status == 404


def provider_type(name):
    if name == 'qwen':
        from app.v2.integrations.qwen import QwenProvider
        return QwenProvider
    from app.v2.integrations.ark import ArkProvider
    return ArkProvider


def completion(content, finish_reason='stop'):
    return {'choices': [{'message': {'content': content}, 'finish_reason': finish_reason}]}


@pytest.mark.parametrize('name', ['qwen', 'ark'])
def test_provider_sends_inline_image_and_enum_prompt_without_creating_or_selecting(name):
    seen = []
    result = {'candidates': [{'name': '蓝色上衣', 'category': 'top', 'colors': ['blue'], 'pattern': 'unknown', 'thickness': 'unknown'}]}
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json=completion(json.dumps(result)))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        provider = provider_type(name)('fake-key', 'frozen-model', 'https://example.test/v1/', http_client=client)
        recognized = provider.recognize(b'image fixture')
        assert recognized['candidates'] == result['candidates']
        assert recognized['_trace']['model'] == 'frozen-model'
        assert not client.is_closed
    assert len(seen) == 1
    request = seen[0]
    assert str(request.url) == 'https://example.test/v1/chat/completions'
    assert request.headers['Authorization'] == 'Bearer fake-key'
    body = json.loads(request.content)
    assert body['model'] == 'frozen-model'
    assert body['response_format'] == {'type': 'json_object'}
    parts = [part for message in body['messages'] for part in message['content'] if isinstance(part, dict)]
    url = next(part['image_url']['url'] for part in parts if part['type'] == 'image_url')
    assert url == 'data:image/jpeg;base64,' + base64.b64encode(b'image fixture').decode('ascii')
    prompt = ' '.join(part['text'] for part in parts if part['type'] == 'text')
    assert 'JSON' in prompt and '童' in prompt
    for enum in ['outerwear', 'multicolor', 'plaid', 'unknown', 'thickness', 'bbox']:
        assert enum in prompt
    if name == 'qwen':
        assert body['enable_thinking'] is False
    else:
        assert body['thinking'] == {'type': 'disabled'}


def test_provider_discards_model_selection_ownership_and_identity_fields():
    original = {'candidates': [{
        'name': '上衣', 'category': 'top', 'colors': ['unknown'],
        'pattern': 'unknown', 'thickness': 'unknown', 'bbox': None,
        'selected': True, 'owners': [{'child_id': '9'}], 'state': 'ready',
        'id': '10', 'confirmed_garment_id': '11',
    }], 'selected': True}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=completion(json.dumps(original))))) as client:
        result = provider_type('qwen')('fake-key', 'model', 'https://example.test/v1', http_client=client).recognize(b'image fixture')
    assert set(result) == {'candidates', '_trace'}
    assert set(result['candidates'][0]) == {'name', 'category', 'colors', 'pattern', 'thickness', 'bbox'}


@pytest.mark.parametrize('name', ['qwen', 'ark'])
@pytest.mark.parametrize('status, retryable', [(429, True), (500, True), (503, True), (400, False), (401, False), (403, False)])
def test_provider_classifies_http_errors_without_echoing_secrets(name, status, retryable):
    from app.v2.integrations.recognition import RecognitionFailure
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, text='fake-key and provider diagnostics'))) as client:
        provider = provider_type(name)('fake-key', 'model', 'https://example.test/v1', http_client=client)
        with pytest.raises(RecognitionFailure) as error:
            provider.recognize(b'image fixture')
    assert error.value.retryable is retryable
    assert error.value.uncertain is False
    assert 'fake-key' not in error.value.message


@pytest.mark.parametrize('name', ['qwen', 'ark'])
@pytest.mark.parametrize('exception, retryable, uncertain', [
    (httpx.ReadTimeout, False, True),
    (httpx.WriteTimeout, False, True),
    (httpx.ReadError, False, True),
    (httpx.ConnectTimeout, True, False),
    (httpx.ConnectError, True, False),
])
def test_provider_does_not_retry_lost_response(name, exception, retryable, uncertain):
    from app.v2.integrations.recognition import RecognitionFailure
    calls = []
    def respond(request):
        calls.append(request)
        raise exception('fake-key should not be exposed', request=request)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        provider = provider_type(name)('fake-key', 'model', 'https://example.test/v1', http_client=client)
        with pytest.raises(RecognitionFailure) as error:
            provider.recognize(b'image fixture')
    assert len(calls) == 1
    assert error.value.retryable is retryable
    assert error.value.uncertain is uncertain
    assert 'fake-key' not in error.value.message


@pytest.mark.parametrize('body', [
    {}, {'choices': [1]}, {'choices': [[]]},
    completion('not json'), completion('```json\n{"candidates": []}\n```'),
    completion('{"candidates": null}'), completion('{"candidates": [1]}'),
    completion('{"candidates": [{"bbox": [NaN, 0, 1, 1]}]}'),
    completion('{"candidates": []}', finish_reason='length'),
])
def test_provider_rejects_malformed_or_truncated_model_output(body):
    from app.v2.integrations.recognition import RecognitionFailure
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        provider = provider_type('qwen')('fake-key', 'model', 'https://example.test/v1', http_client=client)
        with pytest.raises(RecognitionFailure) as error:
            provider.recognize(b'image fixture')
    assert error.value.code == 'RECOGNITION_INVALID_RESPONSE'
    assert not error.value.retryable and not error.value.uncertain


def test_unconfigured_provider_fails_honestly_without_returning_candidates():
    from app.v2.integrations.recognition import RecognitionFailure, UnconfiguredProvider
    with pytest.raises(RecognitionFailure) as error:
        UnconfiguredProvider().recognize(b'image fixture')
    assert error.value.code == 'RECOGNITION_UNCONFIGURED'
    assert not error.value.retryable and not error.value.uncertain


@pytest.mark.parametrize('name', ['qwen', 'ark'])
def test_empty_configuration_and_invalid_input_never_call_http(name):
    from app.v2.integrations.recognition import RecognitionFailure
    def unexpected(request):
        pytest.fail('Invalid or missing configuration must not send an HTTP request')
    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        for key, model, image, content_type in [('', 'model', b'image', 'image/jpeg'), ('key', '', b'image', 'image/jpeg'), ('key', 'model', b'', 'image/jpeg'), ('key', 'model', b'image', 'text/plain')]:
            provider = provider_type(name)(key, model, 'https://example.test/v1', http_client=client)
            with pytest.raises(RecognitionFailure) as error:
                provider.recognize(image, content_type)
            assert not error.value.retryable and not error.value.uncertain
