from datetime import datetime
import json
from uuid import uuid4
import httpx
from sqlalchemy import select
from test_b_worker_assets import worker, uploaded, ClothesProvider
from test_b_wardrobe_intake import child, draft


def test_negative_photo_succeeds_without_candidates_or_auto_retry(client, family_factory, auth, tmp_path):
    class EmptyProvider:
        def recognize(self, image, content_type='image/jpeg'):
            return {'candidates': []}
    now = datetime(2026, 10, 2)
    client.app.state.clock = lambda: now
    w = worker(client, tmp_path, EmptyProvider())
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    _, _, path = uploaded(client, root, headers, kid)
    assert w.run_once()
    current = client.get(path, headers=headers).json()
    assert current['items'][0]['status'] == 'succeeded' and current['items'][0]['error'] is None
    assert current['candidates'] == [] and w.claim() is None
    assert current['has_pending'] is False and current['unresolved_items_count'] == 0


def test_adapter_trace_retains_model_usage_and_bounded_raw_without_credentials():
    from app.v2.integrations.qwen import QwenProvider
    seen = []
    raw = {'candidates': [{'name': '上衣', 'category': 'not-an-enum', 'colors': ['新颜色'], 'bbox': None}]}
    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'model': 'served-snapshot', 'usage': {
            'prompt_tokens': 123, 'completion_tokens': 45, 'total_tokens': 168},
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(raw, ensure_ascii=False)}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = QwenProvider('NEVER_PERSIST_KEY', 'frozen-model', 'https://example.invalid/v1', client).recognize(b'image')
    assert seen[0]['max_tokens'] == 4096 and seen[0]['temperature'] == 0
    trace = result['_trace']
    assert trace['provider'] == 'qwen' and trace['model'] == 'served-snapshot'
    assert trace['usage']['prompt_tokens'] == 123
    assert len(trace['prompt_hash']) == 64
    assert json.loads(trace['raw_json']) == raw
    assert 'NEVER_PERSIST_KEY' not in json.dumps(trace)
    assert 'image' not in trace


def test_attempt_trace_is_immutable_when_human_edits_candidate(client, family_factory, auth, tmp_path):
    class Traced(ClothesProvider):
        def recognize(self, image, content_type='image/jpeg'):
            result = super().recognize(image, content_type)
            result['_trace'] = {'provider': 'fake', 'model': 'fixed', 'usage': {'total_tokens': 1},
                'prompt_hash': 'a' * 64, 'parameters': {'max_tokens': 4096}, 'raw_json': json.dumps(result)}
            return result
    now = datetime(2026, 10, 2)
    client.app.state.clock = lambda: now
    w = worker(client, tmp_path, Traced())
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    _, item, path = uploaded(client, root, headers, kid)
    assert w.run_once()
    from app.v2.recognition.models import RecognitionAttempt
    with client.app.state.session_factory() as db:
        before = db.scalar(select(RecognitionAttempt.result).where(RecognitionAttempt.item_id == int(item['id'])))
    assert before['trace']['model'] == 'fixed'
    candidate = client.get(path, headers=headers).json()['candidates'][0]
    changed = client.put(path + '/candidates/' + candidate['id'], headers=headers,
                         json={'expected_version': candidate['version'], 'name': '人工名字'})
    assert changed.status_code == 200
    with client.app.state.session_factory() as db:
        after = db.scalar(select(RecognitionAttempt.result).where(RecognitionAttempt.item_id == int(item['id'])))
    assert after == before


def test_manual_fit_exception_is_derived_at_creation(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b, item, default = draft(client, root, headers, kid['id'])
    assert default['ownership_exception'] is False
    special = client.post(root + '/intake/batches/' + b['id'] + '/candidates', headers=headers, json={
        'client_id': uuid4().hex, 'item_id': item['id'], 'owners': [{'child_id': kid['id'], 'fit': 'small'}]}).json()
    assert special['ownership_exception'] is True


def test_finished_batch_is_not_reported_as_pending_draft(client, family_factory, auth):
    from test_b_wardrobe_intake import confirm
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b, _, candidate = draft(client, root, headers, kid['id'])
    detail = client.get(root + '/intake/batches/' + b['id'], headers=headers).json()
    assert detail['pending_candidates_count'] == 1 and detail['has_pending'] is True
    assert confirm(client, root, headers, b, [candidate]).status_code == 200
    detail = client.get(root + '/intake/batches/' + b['id'], headers=headers).json()
    assert detail['pending_candidates_count'] == 0 and detail['has_pending'] is False
    assert all(row['id'] != b['id'] for row in client.get(root + '/intake/batches', headers=headers).json())


def test_no_candidate_photo_remains_resumable_until_explicitly_discarded(client, family_factory, auth, tmp_path):
    from app.v2.media.storage import FileStorage
    client.app.state.storage = FileStorage(tmp_path)
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b, item, path = uploaded(client, root, headers, kid)
    detail = client.get(path, headers=headers).json()
    assert detail['unresolved_items_count'] == 1 and detail['has_pending'] is True
    assert client.put(path + '/items/' + item['id'], headers=headers,
        json={'expected_version': item['version'], 'discarded': True}).status_code == 200
    assert client.get(path, headers=headers).json()['has_pending'] is False


def test_provider_evidence_is_bounded():
    from app.v2.integrations.qwen import QwenProvider
    raw = {'candidates': [{'name': 'x' * 40000, 'category': 'top'}]}
    response = {'choices': [{'message': {'content': json.dumps(raw)}, 'finish_reason': 'stop'}]}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))) as client:
        result = QwenProvider('fake-key', 'fixed', 'https://example.invalid', client).recognize(b'image')
    assert result['_trace']['raw_truncated'] is True
    assert len(result['_trace']['raw_json'].encode('utf-8')) <= 32768


def test_worker_cli_uses_configured_retry_budget(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace
    from app.v2.core import config, database
    from app.v2.jobs import worker as worker_module
    settings = config.V2Settings(_env_file=None, database_url='sqlite://', jwt_secret='test',
        private_storage_dir=str(tmp_path), recognition_max_attempts=1)
    monkeypatch.setattr(config, 'V2Settings', lambda: settings)
    monkeypatch.setattr(database, 'build_engine', lambda url: SimpleNamespace(dispose=lambda: None))
    monkeypatch.setattr(database, 'session_factory', lambda engine: 'sessions')
    monkeypatch.setattr(worker_module, 'provider_from_settings', lambda settings: None)
    captured = {}
    class FakeWorker:
        def __init__(self, sessions, storage, provider, **kwargs):
            captured.update(kwargs)
        def run_once(self):
            return False
    monkeypatch.setattr(worker_module, 'RecognitionWorker', FakeWorker)
    monkeypatch.setattr(sys, 'argv', ['worker', '--once'])
    worker_module.main()
    assert captured['max_tries'] == 1
