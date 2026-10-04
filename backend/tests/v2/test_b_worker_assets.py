from datetime import datetime, timedelta
from importlib.util import find_spec
from io import BytesIO
from uuid import uuid4
from PIL import Image
from sqlalchemy import select
from test_b_wardrobe_intake import child, batch, confirm


def photo(color='blue'):
    data = BytesIO()
    Image.new('RGB', (32, 24), color).save(data, format='PNG')
    return data.getvalue()


def uploaded(client, root, headers, kid):
    b = batch(client, root, headers, kid['id'])
    path = root + '/intake/batches/' + b['id']
    item = client.post(path + '/items', headers=headers,
                       json={'client_id': uuid4().hex, 'source': 'camera'}).json()
    response = client.put(path + '/items/' + item['id'] + '/upload', headers={**headers, 'Content-Type': 'image/png'}, content=photo())
    assert response.status_code == 200, response.text
    return b, response.json(), path


def worker(client, tmp_path, provider=None, clock=None):
    assert find_spec('app.v2.jobs.worker') is not None, 'durable worker is missing'
    from app.v2.jobs.worker import RecognitionWorker
    from app.v2.media.storage import FileStorage
    from app.v2.integrations.recognition import UnconfiguredProvider
    client.app.state.storage = FileStorage(tmp_path)
    return RecognitionWorker(client.app.state.session_factory, client.app.state.storage,
        provider or UnconfiguredProvider(), clock=clock or (lambda: datetime(2026, 10, 2, 0, 0)))


class ClothesProvider:
    def recognize(self, image, content_type='image/jpeg'):
        return {'candidates': [{'category': 'top', 'name': '识别上衣', 'colors': ['blue'],
            'pattern': 'solid', 'thickness': 'unknown', 'bbox': [0, 0, 1, 1]}]}


def test_upload_private_hash_reuse_without_physical_dedup_and_replay_no_job(client, family_factory, auth, tmp_path):
    from app.v2.media.storage import FileStorage
    client.app.state.storage = FileStorage(tmp_path)
    f, users = family_factory(('admin', 'editor', 'viewer'))
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b, item, path = uploaded(client, root, headers, kid)
    replay = client.put(path + '/items/' + item['id'] + '/upload', headers={**headers, 'Content-Type': 'image/png'}, content=photo())
    assert replay.status_code == 200 and replay.json()['asset_id'] == item['asset_id']
    assert client.put(path + '/items/' + item['id'] + '/upload', headers={**headers, 'Content-Type': 'image/png'}, content=photo('red')).status_code == 409
    assert client.get(root + '/assets/' + item['asset_id'] + '/content', headers=auth(users[0])).status_code == 200
    for user in users[1:]:
        assert client.get(root + '/assets/' + item['asset_id'] + '/content', headers=auth(user)).status_code == 404
    manual = {'client_id': uuid4().hex, 'item_id': item['id'], 'category': 'top', 'selected': True}
    c = client.post(path + '/candidates', headers=headers, json=manual).json()
    assert confirm(client, root, headers, b, [c]).status_code == 200
    assert client.get(root + '/assets/' + item['asset_id'] + '/content', headers=auth(users[2])).status_code == 200
    _, same, _ = uploaded(client, root, headers, kid)
    assert same['asset_id'] == item['asset_id']
    from app.v2.recognition.models import RecognitionAttempt
    with client.app.state.session_factory() as db:
        assert len(db.scalars(select(RecognitionAttempt)).all()) == 2


def test_invalid_image_is_not_saved_or_queued(client, family_factory, auth, tmp_path):
    from app.v2.media.storage import FileStorage
    client.app.state.storage = FileStorage(tmp_path)
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b = batch(client, root, headers, kid['id'])
    path = root + '/intake/batches/' + b['id']
    item = client.post(path + '/items', headers=headers, json={'client_id': uuid4().hex, 'source': 'album'}).json()
    result = client.put(path + '/items/' + item['id'] + '/upload', headers={**headers, 'Content-Type': 'image/png'}, content=b'not image')
    assert result.status_code == 422, result.text
    assert client.get(path, headers=headers).json()['items'][0]['asset_id'] is None


def test_worker_unconfigured_is_honest_failed_manual_remains_usable(client, family_factory, auth, tmp_path):
    now = datetime(2026, 10, 2, 0, 0)
    client.app.state.clock = lambda: now
    w = worker(client, tmp_path)
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    _, _, path = uploaded(client, root, headers, kid)
    assert w.run_once() is True
    current = client.get(path, headers=headers).json()
    assert current['items'][0]['status'] == 'failed'
    assert current['items'][0]['error']
    assert current['candidates'] == []


def test_late_result_appends_unselected_and_never_overwrites_manual(client, family_factory, auth, tmp_path):
    now = datetime(2026, 10, 2)
    client.app.state.clock = lambda: now
    w = worker(client, tmp_path, ClothesProvider())
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    _, item, path = uploaded(client, root, headers, kid)
    claim = w.claim()
    assert claim is not None and w.claim() is None
    manual = client.post(path + '/candidates', headers=headers, json={'item_id': item['id'], 'client_id': uuid4().hex,
        'category': 'dress', 'name': '人工确认裙子', 'selected': True}).json()
    w.process(claim)
    current = client.get(path, headers=headers).json()['candidates']
    assert next(c for c in current if c['id'] == manual['id'])['name'] == '人工确认裙子'
    added = [c for c in current if c['id'] != manual['id']]
    assert len(added) == 1 and added[0]['selected'] is False
    assert w.publish(claim, ClothesProvider().recognize(b'')) is False
    assert len(client.get(path, headers=headers).json()['candidates']) == 2


def test_first_reliable_single_camera_only_preselects(client, family_factory, auth, tmp_path):
    now = datetime(2026, 10, 2)
    client.app.state.clock = lambda: now
    w = worker(client, tmp_path, ClothesProvider())
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    _, _, path = uploaded(client, root, headers, kid)
    assert w.run_once()
    c = client.get(path, headers=headers).json()['candidates'][0]
    assert c['selected'] is True and c['category'] == 'top'
    assert client.get(root + '/garments', headers=headers).json()['total'] == 0


def test_expired_worker_lease_is_uncertain_fences_late_publish_and_retry(client, family_factory, auth, tmp_path):
    now = [datetime(2026, 10, 2)]
    client.app.state.clock = lambda: now[0]
    w = worker(client, tmp_path, ClothesProvider(), lambda: now[0])
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    _, item, path = uploaded(client, root, headers, kid)
    claim = w.claim()
    now[0] += timedelta(minutes=10)
    assert w.claim() is None
    assert w.publish(claim, ClothesProvider().recognize(b'')) is False
    assert client.get(path, headers=headers).json()['items'][0]['status'] == 'uncertain'
    assert client.post(path + '/items/' + item['id'] + '/recognition', headers=headers).json()['error']['code'] == 'RECOGNITION_UNCERTAIN'


def test_worker_rechecks_discard_and_membership_before_publish(client, family_factory, auth, tmp_path):
    now = datetime(2026, 10, 2)
    client.app.state.clock = lambda: now
    w = worker(client, tmp_path, ClothesProvider())
    f, users = family_factory(('admin', 'editor'))
    root, headers = '/v2/families/' + f['id'], auth(users[1])
    kid = child(client, root, auth(users[0]))
    _, item, path = uploaded(client, root, headers, kid)
    claim = w.claim()
    item = client.get(path, headers=headers).json()['items'][0]
    assert client.put(path + '/items/' + item['id'], headers=headers,
        json={'expected_version': item['version'], 'discarded': True}).status_code == 200
    assert w.publish(claim, ClothesProvider().recognize(b'')) is False
    assert client.get(path, headers=headers).json()['candidates'] == []
    _, _, other_path = uploaded(client, root, headers, kid)
    claim = w.claim()
    members = client.get(root + '/members', headers=auth(users[0])).json()
    member = next(m for m in members if m['role'] == 'editor')
    assert client.delete(root + '/members/' + member['id'], headers=auth(users[0])).status_code == 204
    assert w.publish(claim, ClothesProvider().recognize(b'')) is False
    assert client.get(other_path, headers=headers).status_code == 404


def test_no_reliable_bbox_does_not_preselect_a_single_candidate(client, family_factory, auth, tmp_path):
    class Ungrounded(ClothesProvider):
        def recognize(self, image, content_type='image/jpeg'):
            result = super().recognize(image, content_type)
            result['candidates'][0]['bbox'] = None
            return result
    now = datetime(2026, 10, 2)
    client.app.state.clock = lambda: now
    w = worker(client, tmp_path, Ungrounded())
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    _, _, path = uploaded(client, root, headers, kid)
    assert w.run_once()
    assert client.get(path, headers=headers).json()['candidates'][0]['selected'] is False


def test_automatic_retry_is_bounded_and_success_is_not_preselected(client, family_factory, auth, tmp_path):
    from app.v2.integrations.recognition import RecognitionFailure
    class Flaky(ClothesProvider):
        calls = 0
        def recognize(self, image, content_type='image/jpeg'):
            self.calls += 1
            if self.calls == 1:
                raise RecognitionFailure('RATE_LIMITED', '稍后重试', retryable=True)
            return super().recognize(image, content_type)
    now = [datetime(2026, 10, 2)]
    client.app.state.clock = lambda: now[0]
    provider = Flaky()
    w = worker(client, tmp_path, provider, lambda: now[0])
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    _, _, path = uploaded(client, root, headers, kid)
    assert w.run_once()
    assert client.get(path, headers=headers).json()['items'][0]['status'] == 'queued'
    assert w.run_once() is False
    now[0] += timedelta(seconds=10)
    assert w.run_once()
    assert client.get(path, headers=headers).json()['candidates'][0]['selected'] is False
    assert provider.calls == 2


def test_missing_private_file_fails_before_any_provider_call(client, family_factory, auth, tmp_path):
    class Counting(ClothesProvider):
        calls = 0
        def recognize(self, image, content_type='image/jpeg'):
            self.calls += 1
            return super().recognize(image, content_type)
    now = datetime(2026, 10, 2)
    client.app.state.clock = lambda: now
    provider = Counting()
    w = worker(client, tmp_path, provider)
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    _, _, path = uploaded(client, root, headers, kid)
    claim = w.claim()
    (tmp_path / claim.object_key).unlink()
    w.process(claim)
    assert provider.calls == 0
    assert client.get(path, headers=headers).json()['items'][0]['status'] == 'failed'
