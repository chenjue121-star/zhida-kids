from uuid import uuid4
import pytest
from sqlalchemy import event
from test_b_wardrobe_intake import child, draft
from test_b_worker_assets import worker, uploaded, ClothesProvider


def test_outer_receipt_failure_rolls_back_successful_candidate_savepoint(client, family_factory, auth, engine):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b, _, c = draft(client, root, headers, kid['id'])
    def fail_receipt(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO wardrobe_operations'):
            raise RuntimeError('forced receipt failure')
    event.listen(engine, 'before_cursor_execute', fail_receipt)
    try:
        with pytest.raises(RuntimeError, match='forced receipt failure'):
            client.post(root + '/intake/batches/' + b['id'] + '/confirm', headers=headers, json={
                'operation_id': uuid4().hex, 'entries': [{'candidate_id': c['id'],
                    'expected_version': c['version'], 'action': 'new'}]})
    finally:
        event.remove(engine, 'before_cursor_execute', fail_receipt)
    assert client.get(root + '/garments', headers=headers).json()['total'] == 0
    current = client.get(root + '/intake/batches/' + b['id'], headers=headers).json()['candidates'][0]
    assert current['confirmed_garment_id'] is None and current['version'] == c['version']


def test_restored_editor_permission_can_resume_own_failed_draft(client, family_factory, auth, tmp_path):
    from datetime import datetime
    now = datetime(2026, 10, 2)
    client.app.state.clock = lambda: now
    w = worker(client, tmp_path, ClothesProvider())
    f, users = family_factory(('admin', 'editor'))
    root, admin, editor = '/v2/families/' + f['id'], auth(users[0]), auth(users[1])
    kid = child(client, root, admin)
    _, item, path = uploaded(client, root, editor, kid)
    members = client.get(root + '/members', headers=admin).json()
    mid = next(m['id'] for m in members if m['role'] == 'editor')
    version = client.get(root, headers=admin).json()['version']
    assert client.put(root + '/members/' + mid, headers=admin,
        json={'role': 'viewer', 'expected_family_version': version}).status_code == 200
    assert w.claim() is None
    assert client.get(path, headers=editor).status_code == 403
    version = client.get(root, headers=admin).json()['version']
    assert client.put(root + '/members/' + mid, headers=admin,
        json={'role': 'editor', 'expected_family_version': version}).status_code == 200
    assert client.get(path, headers=editor).status_code == 200
    retry = client.post(path + '/items/' + item['id'] + '/recognition', headers=editor)
    assert retry.status_code == 202, retry.text
