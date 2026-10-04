"""Bounded immutable evidence for later recognition evaluation; never API data."""
import json
from hashlib import sha256
from app.v2.integrations.recognition import PROMPT


def recognition_trace(result, provider):
    incoming = result.get('_trace', {}) if isinstance(result, dict) else {}
    if not isinstance(incoming, dict):
        incoming = {}
    fields = {'name', 'category', 'colors', 'pattern', 'thickness', 'bbox'}
    raw = incoming.get('raw_json')
    if not isinstance(raw, str):
        candidates = result.get('candidates', []) if isinstance(result, dict) else []
        raw = json.dumps({'candidates': [{key: value for key, value in candidate.items() if key in fields}
            for candidate in candidates if isinstance(candidate, dict)]}, ensure_ascii=False, allow_nan=False)
    encoded = raw.encode('utf-8')
    usage = incoming.get('usage', {})
    usage = {key: value for key, value in usage.items() if key in (
        'prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens', 'output_tokens', 'cached_tokens', 'image_tokens')
        and type(value) is int and value >= 0} if isinstance(usage, dict) else {}
    params = incoming.get('parameters', {})
    # Never retain request messages, Authorization, image bytes or arbitrary adapter diagnostics.
    params = {key: value for key, value in params.items() if key in (
        'max_tokens', 'temperature', 'response_format', 'enable_thinking', 'thinking')} if isinstance(params, dict) else {}
    return {'provider': str(incoming.get('provider', getattr(provider, 'provider_name', type(provider).__name__)))[:40],
            'model': str(incoming.get('model', getattr(provider, 'model', '')))[:128],
            'usage': usage, 'prompt_hash': str(incoming.get('prompt_hash', sha256(PROMPT.encode()).hexdigest()))[:64],
            'parameters': params, 'raw_json': encoded[:32768].decode('utf-8', errors='ignore'),
            'raw_truncated': bool(incoming.get('raw_truncated')) or len(encoded) > 32768}
