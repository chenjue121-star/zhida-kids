"""Versioned evaluation runs. Importing this module never loads secrets or an app."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import get_args
from urllib.parse import urlsplit

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from app.v2.integrations.recognition import PROMPT, RecognitionFailure
from app.v2.integrations import ark, qwen, recognition as adapter
from app.v2.media import service as image_service
from app.v2.recognition import normalize as normalization
from app.v2.wardrobe.schemas import Category, Color, Pattern, Thickness

CACHE_SCHEMA = 1


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str
    model: str
    base_url: str
    api_key_env: str

    def __post_init__(self):
        if self.provider not in ('qwen', 'ark'):
            raise ValueError('provider must be qwen or ark')
        if not all(isinstance(value, str) and value.strip() and '\n' not in value
                   for value in (self.name, self.model, self.base_url, self.api_key_env)):
            raise ValueError('model configuration fields must be non-empty strings')
        url = urlsplit(self.base_url)
        if url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
            raise ValueError('base_url must be an HTTPS API URL without credentials or query')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', self.api_key_env):
            raise ValueError('api_key_env must name one environment variable')


class CallLimitExceeded(RuntimeError):
    pass


class CallBudget:
    def __init__(self, max_calls: int):
        if type(max_calls) is not int or max_calls <= 0:
            raise ValueError('max_calls must be a positive integer')
        self.max_calls = max_calls
        self.used = 0

    def take(self):
        if self.used >= self.max_calls:
            raise CallLimitExceeded('model call budget exhausted')
        self.used += 1


def request_parameters(provider):
    extra = {'enable_thinking': False} if provider == 'qwen' else {'thinking': {'type': 'disabled'}}
    return {'max_tokens': 4096, 'temperature': 0, 'response_format': {'type': 'json_object'},
            'stream': False, **extra}


def pipeline_fingerprint():
    return {
        'preprocessing': hashlib.sha256(Path(image_service.__file__).read_bytes()).hexdigest(),
        'normalization': hashlib.sha256(Path(normalization.__file__).read_bytes()).hexdigest(),
        'adapters': {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                     for name, module in (('chat', adapter), ('qwen', qwen), ('ark', ark))},
        'taxonomy': {'category': list(get_args(Category)), 'colors': list(get_args(Color)),
                     'pattern': list(get_args(Pattern)), 'thickness': list(get_args(Thickness))},
    }


def cache_identity(image: bytes, spec: ModelSpec, run_index: int, *, prompt=None):
    if type(run_index) is not int or run_index < 0:
        raise ValueError('run_index must be non-negative')
    pipeline = pipeline_fingerprint()
    if prompt is not None:
        from eval.recognition_v2 import color_prompt
        color_prompt.validate_prompt(prompt)
        pipeline['evaluation_adapter'] = hashlib.sha256(Path(color_prompt.__file__).read_bytes()).hexdigest()
    identity = {'schema_version': CACHE_SCHEMA, 'image_sha256': hashlib.sha256(image).hexdigest(),
            'provider': spec.provider, 'requested_model': spec.model, 'base_url': spec.base_url.rstrip('/'),
            'prompt_sha256': hashlib.sha256((PROMPT if prompt is None else prompt).encode()).hexdigest(),
            'parameters': request_parameters(spec.provider), 'pipeline': pipeline,
            'run_index': run_index}
    if prompt is not None:
        identity['evaluation_variant'] = color_prompt.VARIANT
    return identity


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def cache_key(image: bytes, spec: ModelSpec, run_index: int, *, prompt=None):
    return hashlib.sha256(_json(cache_identity(image, spec, run_index, prompt=prompt)).encode()).hexdigest()


def create_provider(spec: ModelSpec, *, prompt=None):
    if prompt is not None:
        from eval.recognition_v2.color_prompt import create_color_provider, validate_prompt
        validate_prompt(prompt)
    key = os.environ.get(spec.api_key_env, '')
    if not key.strip():
        raise ValueError(f'missing API key environment variable: {spec.api_key_env}')
    if prompt is not None:
        return create_color_provider(spec, key, prompt=prompt)
    if spec.provider == 'qwen':
        from app.v2.integrations.qwen import QwenProvider
        return QwenProvider(key, spec.model, spec.base_url)
    from app.v2.integrations.ark import ArkProvider
    return ArkProvider(key, spec.model, spec.base_url)


def _read_cache(path, identity):
    try:
        if path.stat().st_size > 512 * 1024:
            return None
        record = json.loads(path.read_text(encoding='utf-8'), parse_constant=_reject_constant)
        if not isinstance(record, dict) or record.get('status') != 'ok' or record.get('identity') != identity:
            return None
        if set(record) != {'identity', 'source', 'status', 'candidates', 'raw_candidates', 'model',
                           'elapsed_ms', 'return_ms', 'usage', 'error'}:
            return None
        if record['source'] != 'live' or record['error'] is not None or not isinstance(record['model'], str) or not record['model'].strip():
            return None
        if any(type(record[field]) not in (int, float) or not math.isfinite(record[field]) or record[field] < 0
               for field in ('elapsed_ms', 'return_ms')):
            return None
        if not isinstance(record['usage'], dict) or _usage({'usage': record['usage']}) != record['usage']:
            return None
        if identity.get('evaluation_variant') is not None:
            from eval.recognition_v2.color_prompt import validate_adapted_candidates
            validate_adapted_candidates(record['raw_candidates'])
        candidates = normalization.normalize_result({'candidates': record.get('candidates')})
        if candidates != record['candidates'] or normalization.normalize_result({'candidates': record['raw_candidates']}) != candidates:
            return None
        return record
    except (OSError, ValueError, TypeError, OverflowError, RecognitionFailure):
        return None


def _reject_constant(value):
    raise ValueError('non-finite number in cached JSON')


def _write_cache(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.stem + '.', suffix='.tmp', delete=False) as target:
            temporary = Path(target.name)
            target.write(_json(record))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _check_cache_writable(path):
    """Probe custom-run cache storage before reserving a paid model request."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix=path.stem + '.', suffix='.probe') as target:
        target.write('{}')
        target.flush()


def _usage(trace):
    allowed = ('prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens', 'output_tokens',
               'cached_tokens', 'image_tokens')
    values = trace.get('usage') if isinstance(trace, dict) else None
    return {key: value for key, value in values.items() if key in allowed and type(value) is int and value >= 0} \
        if isinstance(values, dict) else {}


def run_one(image_path, spec: ModelSpec, cache_dir, *, run_index=0, offline=True,
            budget: CallBudget | None = None, provider_factory=None, expected_sha256=None, prompt=None):
    """Run/replay recognition with an optional evaluation color-role prompt.

    Default factories keep their existing ``factory(spec)`` contract. A custom
    prompt selects color_roles_v1 and calls ``factory(spec, prompt=prompt)``;
    that provider must return validated roles, derived colors and the actual
    sent-prompt hash in _trace. All identity hashes use the full prompt text.
    """
    started = time.perf_counter()
    if prompt is not None:
        from eval.recognition_v2.color_prompt import validate_adapted_candidates, validate_prompt
        validate_prompt(prompt)
    if not offline and budget is None:
        raise ValueError('live runs require an explicit call budget')
    raw = Path(image_path).read_bytes()
    identity = cache_identity(raw, spec, run_index, prompt=prompt)
    path = Path(cache_dir) / (hashlib.sha256(_json(identity).encode()).hexdigest() + '.json')
    record = {'identity': identity, 'source': 'validation', 'status': 'invalid_image',
              'candidates': [], 'raw_candidates': [], 'model': spec.model,
              'elapsed_ms': None, 'return_ms': None, 'usage': {}, 'error': None}
    if expected_sha256 is not None and identity['image_sha256'] != expected_sha256:
        record['error'] = {'code': 'EVAL_IMAGE_CHANGED', 'message': '照片内容在审核后发生变化，请重新核对标签'}
        record['return_ms'] = round((time.perf_counter() - started) * 1000, 3)
        return record
    try:
        with Image.open(io.BytesIO(raw)) as image:
            mime = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}.get(image.format)
        if mime is None:
            raise ValueError('unsupported image format')
        processed, _, _, _ = image_service.normalize_image(raw, mime)
    except (HTTPException, UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        record['error'] = {'code': 'EVAL_INVALID_IMAGE', 'message': '图片不符合生产识别输入要求'}
        record['return_ms'] = round((time.perf_counter() - started) * 1000, 3)
        return record
    cached = _read_cache(path, identity)
    if cached is not None:
        cached['source'] = 'cache'
        cached['return_ms'] = round((time.perf_counter() - started) * 1000, 3)
        return cached
    if offline:
        record.update(source='offline_missing', status='offline_missing',
                      error={'code': 'EVAL_OFFLINE_CACHE_MISS', 'message': '当前输入版本没有有效缓存，未联网'})
        record['return_ms'] = round((time.perf_counter() - started) * 1000, 3)
        return record
    if budget.used >= budget.max_calls:
        raise CallLimitExceeded('model call budget exhausted')
    factory = provider_factory or create_provider
    if prompt is not None:
        _check_cache_writable(path)
        provider = factory(spec, prompt=prompt)
    else:
        provider = factory(spec)
    budget.take()
    record.update(source='live', status='error')
    called = time.perf_counter()
    try:
        result = provider.recognize(processed, 'image/jpeg')
        trace = result.get('_trace', {}) if isinstance(result, dict) else {}
        model = trace.get('model') if isinstance(trace, dict) else None
        record.update(usage=_usage(trace), model=model if isinstance(model, str) and model.strip() else spec.model)
        if prompt is not None:
            if not isinstance(trace, dict) or trace.get('prompt_hash') != identity['prompt_sha256']:
                raise RecognitionFailure('EVAL_PROMPT_MISMATCH', '评测请求提示词与缓存身份不一致')
            validate_adapted_candidates(result['candidates'])
        candidates = normalization.normalize_result(result)
        record.update(status='ok', candidates=candidates, raw_candidates=result['candidates'])
    except RecognitionFailure as error:
        if prompt is not None and isinstance(error.trace, dict):
            model = error.trace.get('model')
            record.update(usage=_usage(error.trace),
                          model=model if isinstance(model, str) and model.strip() else spec.model)
        record['error'] = {'code': error.code, 'message': error.message,
                           'retryable': error.retryable, 'uncertain': error.uncertain}
    except (TypeError, ValueError, KeyError, OverflowError):
        record['error'] = {'code': 'EVAL_INVALID_RESULT', 'message': '模型结果无法评分'}
    record['elapsed_ms'] = round((time.perf_counter() - called) * 1000, 3)
    record['return_ms'] = round((time.perf_counter() - started) * 1000, 3)
    if record['status'] == 'ok':
        _write_cache(path, record)
    return record
