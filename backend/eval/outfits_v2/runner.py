"""Matched multimodal requests and guarded replay; no settings or implicit retries."""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import tempfile
import time

import httpx
from PIL import Image

from app.v2.integrations import outfits as production
from app.v2.outfits import rules
from eval.recognition_v2.runner import ModelSpec, CallBudget, CallLimitExceeded
from . import protocol
from .protocol import garment_id, safe_payload, validate_case, validate_selection

CACHE_SCHEMA = 1
ARMS = ('attributes', 'photos')
OUTPUT_MODES = ('prompt_only', 'json_object')
CACHE_STATUSES = frozenset({'ok', 'invalid_json', 'invalid_selection', 'http_error', 'request_error'})
_RECORD_KEYS = {'identity', 'case_id', 'arm', 'source', 'status', 'selection', 'chosen_ids', 'usable_ids',
                'fallback', 'model', 'usage', 'elapsed_ms', 'return_ms', 'error', 'cache_error'}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_output_mode(output_mode):
    if output_mode not in OUTPUT_MODES:
        raise ValueError('invalid output_mode')


def _prompt(output_mode='prompt_only'):
    _validate_output_mode(output_mode)
    # Extract the literal from the production request, without constructing settings.
    for node in ast.walk(ast.parse(Path(production.__file__).read_text(encoding='utf-8'))):
        if isinstance(node, ast.Dict):
            values = {key.value: value for key, value in zip(node.keys, node.values) if isinstance(key, ast.Constant)}
            role, content = values.get('role'), values.get('content')
            if isinstance(role, ast.Constant) and role.value == 'system' and isinstance(content, ast.Constant) and isinstance(content.value, str):
                prompt = content.value
                if output_mode == 'json_object':
                    prompt += ('\n输出结构示例：{"garment_ids":["ID_A","ID_B"],"reason":"简短中文理由"}。'
                               'ID_A、ID_B 是抽象占位 ID，不是可选衣物，必须替换为输入原候选中的实际 ID。'
                               'garment_ids 必须是字符串数组；只能选择原候选中的一个完整整组，不能混搭、增删或虚构 ID。'
                               '只返回一个 JSON 对象，不要代码围栏、前后说明或其他内容；reason 使用简短中文理由。')
                return prompt
    raise ValueError('production outfit system prompt is not a literal')


def request_parameters(provider, output_mode='prompt_only'):
    _validate_output_mode(output_mode)
    parameters = {'temperature': .2, 'max_tokens': 500}
    if provider == 'qwen':
        parameters['enable_thinking'] = False
    elif provider == 'ark':
        parameters['thinking'] = {'type': 'disabled'}
    if output_mode == 'json_object':
        parameters['response_format'] = {'type': 'json_object'}
    return parameters


def _photos(case, image_root):
    root, result = Path(image_root).resolve(), {}
    ids = dict.fromkeys(garment_id(gid) for combo in case['combinations'] for gid in combo)
    for gid in ids:
        photo = case['photos'].get(gid)
        if not isinstance(photo, dict):
            raise ValueError('missing referenced photo')
        name, expected = photo.get('path'), photo.get('sha256')
        if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
            raise ValueError('unsafe photo path')
        relative = PurePosixPath(name)
        if relative.is_absolute() or PureWindowsPath(name).drive or '..' in relative.parts or relative.suffix.lower() not in ('.jpg', '.jpeg'):
            raise ValueError('photo must have a safe relative JPEG path')
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('invalid photo identity')
        if path.stat().st_size > 12 * 1024 * 1024:
            raise ValueError('photo too large')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('photo changed after freezing')
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != 'JPEG' or image.width * image.height > 24_000_000:
                raise ValueError('invalid JPEG photo')
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
        result[gid] = raw
    return result


def _identity(case, spec, arm, run_index, photos, output_mode='prompt_only'):
    prompt = _prompt(output_mode)
    return {'schema_version': CACHE_SCHEMA, 'case_sha256': hashlib.sha256(_json(case).encode()).hexdigest(),
            'provider': spec.provider, 'requested_model': spec.model, 'base_url': spec.base_url.rstrip('/'),
            'arm': arm, 'run_index': run_index, 'output_mode': output_mode,
            'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
            'parameters': request_parameters(spec.provider, output_mode),
            'photos': {gid: hashlib.sha256(raw).hexdigest() for gid, raw in photos.items()},
            'sources': {'rules': _hash(rules.__file__), 'protocol': _hash(protocol.__file__),
                        'runner': _hash(__file__), 'production_outfits': _hash(production.__file__)}}


def _body(case, spec, arm, photos, output_mode='prompt_only'):
    _validate_output_mode(output_mode)
    content = [{'type': 'text', 'text': _json(safe_payload(case))}]
    for gid, raw in photos.items():
        content.append({'type': 'text', 'text': 'garment_id=' + gid})
        if arm == 'photos':
            content.append({'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')}})
    return {'model': spec.model, 'messages': [{'role': 'system', 'content': _prompt(output_mode)},
                                            {'role': 'user', 'content': content}], **request_parameters(spec.provider, output_mode)}


def _usage(value):
    allowed = {'prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens', 'output_tokens', 'cached_tokens', 'image_tokens'}
    return {key: item for key, item in value.items() if key in allowed and type(item) is int and 0 <= item <= 10**12} if isinstance(value, dict) else {}


def _number(value):
    try:
        return type(value) in (int, float) and value >= 0 and math.isfinite(value)
    except OverflowError:
        return False


def _read_cache(path, identity, case):
    try:
        if path.stat().st_size > 128 * 1024:
            return None
        record = json.loads(path.read_text(encoding='utf-8'), parse_constant=protocol.reject_constant)
        if not isinstance(record, dict) or set(record) != _RECORD_KEYS or record['identity'] != identity or \
                record['source'] != 'live' or record['status'] not in CACHE_STATUSES or record['case_id'] != case['id'] or record['arm'] != identity['arm']:
            return None
        if record['cache_error'] is not None:
            return None
        if not all(_number(record[field]) for field in ('elapsed_ms', 'return_ms')) or not isinstance(record['model'], str) or not record['model'].strip():
            return None
        if not isinstance(record['usage'], dict) or _usage(record['usage']) != record['usage'] or type(record['fallback']) is not bool:
            return None
        selection = record['selection']
        if not isinstance(selection, dict) or set(selection) != {'valid', 'code', 'garment_ids', 'combination_index'} or type(selection['valid']) is not bool:
            return None
        if record['status'] == 'ok':
            if type(selection['combination_index']) is not int or selection != validate_selection(case, {'garment_ids': selection['garment_ids']}) or not selection['valid'] or record['error'] is not None:
                return None
        else:
            if selection['valid'] or selection['code'] not in protocol.INVALID_SELECTION_CODES | {'HTTP_ERROR', 'REQUEST_ERROR'} or selection['combination_index'] is not None:
                return None
            if not isinstance(selection['garment_ids'], list) or any(garment_id(gid) != gid for gid in selection['garment_ids']):
                return None
            if record['status'] == 'invalid_selection':
                if selection['code'] not in protocol.INVALID_SELECTION_CODES - {'INVALID_JSON'}:
                    return None
                if selection['code'] not in {'INVALID_RESULT', 'MISSING_IDS', 'INVALID_IDS'} and \
                        selection != validate_selection(case, {'garment_ids': selection['garment_ids']}):
                    return None
            elif selection['code'] != {'invalid_json': 'INVALID_JSON', 'http_error': 'HTTP_ERROR', 'request_error': 'REQUEST_ERROR'}[record['status']]:
                return None
            error = record['error']
            if not isinstance(error, dict) or set(error) - {'code', 'http_status'} or error.get('code') != selection['code']:
                return None
            if 'http_status' in error and (type(error['http_status']) is not int or not 100 <= error['http_status'] <= 599):
                return None
        chosen = selection['garment_ids'] if selection['valid'] else []
        usable = chosen if selection['valid'] else [garment_id(gid) for gid in case['baseline_ids']]
        if record['chosen_ids'] != chosen or record['usable_ids'] != usable or record['fallback'] != (not selection['valid']):
            return None
        return record
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return None


def _write_cache(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, suffix='.tmp', delete=False) as target:
            temporary = Path(target.name)
            target.write(_json(record))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _probe_cache(directory):
    """Verify an actual write before charging a model request; remove the probe."""
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, prefix='.outfit-probe-', suffix='.tmp', mode='wb') as probe:
        probe.write(b'cache write probe')
        probe.flush()


def run_one(case, spec: ModelSpec, image_root, cache_dir, *, arm, run_index=0, offline=True,
            budget: CallBudget | None = None, http_client=None, output_mode='prompt_only'):
    _validate_output_mode(output_mode)
    started = time.perf_counter()
    if arm not in ARMS or type(run_index) is not int or run_index < 0:
        raise ValueError('invalid arm or run_index')
    record = {'identity': None, 'case_id': case.get('id') if isinstance(case, dict) else None, 'arm': arm,
              'source': 'validation', 'status': 'invalid_input', 'selection': None, 'chosen_ids': [],
              'usable_ids': [], 'fallback': False, 'model': spec.model, 'usage': {},
              'elapsed_ms': None, 'return_ms': None, 'error': None, 'cache_error': None}
    def returned():
        record['return_ms'] = round((time.perf_counter() - started) * 1000, 3)
        return record
    try:
        validate_case(case)
        photos = _photos(case, image_root)
        record['identity'] = _identity(case, spec, arm, run_index, photos, output_mode)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        record['error'] = {'code': 'INVALID_INPUT'}
        return returned()
    if not case['combinations']:
        record['status'] = 'no_candidates'
        return returned()
    path = Path(cache_dir) / (hashlib.sha256(_json(record['identity']).encode()).hexdigest() + '.json')
    cached = _read_cache(path, record['identity'], case)
    if cached is not None:
        cached['source'] = 'cache'
        cached['return_ms'] = round((time.perf_counter() - started) * 1000, 3)
        return cached
    if offline:
        record.update(source='offline_missing', status='offline_missing', error={'code': 'OFFLINE_CACHE_MISS'})
        return returned()
    if budget is None:
        raise ValueError('live requests require an explicit call budget')
    if budget.used >= budget.max_calls:
        raise CallLimitExceeded('model call budget exhausted')
    key = os.environ.get(spec.api_key_env, '')
    if not key.strip():
        record['error'] = {'code': 'MISSING_API_KEY'}
        return returned()
    try:
        _probe_cache(path.parent)
    except (OSError, ValueError):
        record['error'] = {'code': 'CACHE_UNWRITABLE'}
        return returned()
    body = _body(case, spec, arm, photos, output_mode)
    record.update(source='live', status='request_error')
    budget.take()
    called = time.perf_counter()
    selection = {'valid': False, 'code': 'REQUEST_ERROR', 'garment_ids': [], 'combination_index': None}
    error = {'code': 'REQUEST_ERROR'}
    try:
        headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
        if http_client is None:
            with httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=False, trust_env=False) as http:
                response = http.post(spec.base_url.rstrip('/') + '/chat/completions', headers=headers, json=body)
        else:
            response = http_client.post(spec.base_url.rstrip('/') + '/chat/completions', headers=headers, json=body,
                                        timeout=httpx.Timeout(60, connect=10), follow_redirects=False)
        if not 200 <= response.status_code < 300:
            record['status'] = 'http_error'
            selection['code'] = 'HTTP_ERROR'
            error = {'code': 'HTTP_ERROR', 'http_status': response.status_code}
        else:
            record['status'] = 'invalid_json'
            selection['code'] = 'INVALID_JSON'
            error = {'code': 'INVALID_JSON'}
            if len(response.content) <= 128 * 1024:
                envelope = json.loads(response.content, parse_constant=protocol.reject_constant)
                if not isinstance(envelope, dict):
                    raise ValueError('invalid response envelope')
                record['usage'] = _usage(envelope.get('usage'))
                actual_model = envelope.get('model')
                if isinstance(actual_model, str) and actual_model.strip():
                    record['model'] = actual_model
                choice = envelope['choices'][0]
                if choice.get('finish_reason') not in (None, 'stop'):
                    raise ValueError('incomplete response')
                completion = choice['message']['content']
                if not isinstance(completion, str):
                    raise ValueError('completion must be JSON text')
                selection = validate_selection(case, completion)
                record['status'] = 'ok' if selection['valid'] else 'invalid_json' if selection['code'] == 'INVALID_JSON' else 'invalid_selection'
                error = None if selection['valid'] else {'code': selection['code']}
    except httpx.RequestError:
        record['status'] = 'request_error'
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        record['status'] = 'invalid_json'
        selection = {'valid': False, 'code': 'INVALID_JSON', 'garment_ids': [], 'combination_index': None}
        error = {'code': 'INVALID_JSON'}
    record.update(selection=selection, error=error, chosen_ids=selection['garment_ids'] if selection['valid'] else [],
                  usable_ids=selection['garment_ids'] if selection['valid'] else [garment_id(gid) for gid in case['baseline_ids']],
                  fallback=not selection['valid'], elapsed_ms=round((time.perf_counter() - called) * 1000, 3))
    returned()
    try:
        _write_cache(path, record)
    except OSError:
        record['cache_error'] = {'code': 'CACHE_WRITE_FAILED'}
    return returned()
