from uuid import uuid4
from test_b_wardrobe_intake import child, draft, garment, confirm


def test_confirm_unknown_resolve_fences_late_submission(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b, _, candidate = draft(client, root, headers, kid['id'])
    operation = uuid4().hex
    body = {'operation_id': operation, 'entries': [{'candidate_id': candidate['id'],
              'expected_version': candidate['version'], 'action': 'new'}]}
    path = root + '/intake/batches/' + b['id']
    assert client.get(path + '/operations/' + operation, headers=headers).json()['status'] == 'unknown'
    resolved = client.post(path + '/operations/' + operation + '/resolve', headers=headers, json=body)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()['results'][0]['error']['code'] == 'NOT_EXECUTED'
    assert client.post(path + '/confirm', headers=headers, json=body).json() == resolved.json()
    assert client.get(root + '/garments', headers=headers).json()['total'] == 0


def test_bulk_resolve_returns_existing_success_or_fences_unknown(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    g = garment(client, root, headers, kid['id'])
    op = uuid4().hex
    body = {'operation_id': op, 'action': 'state', 'state': 'washing', 'items': [
        {'id': g['id'], 'expected_version': g['version']}]}
    resolved = client.post(root + '/wardrobe-operations/' + op + '/resolve', headers=headers, json=body)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()['results'][0]['error']['code'] == 'NOT_EXECUTED'
    assert client.post(root + '/garments/bulk', headers=headers, json=body).json() == resolved.json()
    assert client.get(root + '/garments/' + g['id'], headers=headers).json()['state'] == 'ready'


def test_single_archive_has_query_and_resolve_closure(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    g = garment(client, root, headers, kid['id'])
    op = uuid4().hex
    body = {'operation_id': op, 'expected_version': g['version']}
    path = root + '/garments/' + g['id'] + '/archive'
    resolved = client.post(path + '/resolve', headers=headers, json=body)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()['results'][0]['error']['code'] == 'NOT_EXECUTED'
    assert client.post(path, headers={**headers, 'Idempotency-Key': op}, json=body).status_code == 409
    assert client.get(root + '/wardrobe-operations/' + op, headers=headers).json() == resolved.json()


def test_candidate_client_identity_replays_and_item_discard_is_explicit(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b, item, c = draft(client, root, headers, kid['id'])
    path = root + '/intake/batches/' + b['id']
    body = {'client_id': uuid4().hex, 'item_id': item['id'], 'name': '手填第二件'}
    first = client.post(path + '/candidates', headers=headers, json=body)
    assert first.status_code == 201, first.text
    assert client.post(path + '/candidates', headers=headers, json=body).json() == first.json()
    assert client.post(path + '/candidates', headers=headers, json={**body, 'name': '不同'}).status_code == 409
    item = client.get(path, headers=headers).json()['items'][0]
    discarded = client.put(path + '/items/' + item['id'], headers=headers,
                           json={'expected_version': item['version'], 'discarded': True})
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()['discarded'] is True
    assert confirm(client, root, headers, b, [c]).json()['results'][0]['error']['code'] == 'CANDIDATE_DISCARDED'


def test_candidate_ownership_exception_can_distinguish_bulk_from_individual(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b, _, c = draft(client, root, headers, kid['id'])
    path = root + '/intake/batches/' + b['id'] + '/candidates/' + c['id']
    changed = client.put(path, headers=headers, json={'expected_version': c['version'],
        'owners': [{'child_id': kid['id'], 'fit': 'small'}], 'ownership_exception': True})
    assert changed.status_code == 200, changed.text
    assert changed.json()['ownership_exception'] is True
    bulk = client.put(path, headers=headers, json={'expected_version': changed.json()['version'],
        'owners': [{'child_id': kid['id'], 'fit': 'unknown'}], 'ownership_exception': False})
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()['ownership_exception'] is False


def test_discard_photo_preserves_already_confirmed_objects_and_stops_pending(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b, item, c = draft(client, root, headers, kid['id'])
    path = root + '/intake/batches/' + b['id']
    extra = client.post(path + '/candidates', headers=headers,
        json={'client_id': uuid4().hex, 'item_id': item['id'], 'category': 'bottom', 'selected': True}).json()
    confirmed = confirm(client, root, headers, b, [c]).json()['results'][0]['garment']
    item = client.get(path, headers=headers).json()['items'][0]
    response = client.put(path + '/items/' + item['id'], headers=headers,
        json={'expected_version': item['version'], 'discarded': True})
    assert response.status_code == 200, response.text
    candidates = response.json()['candidates']
    assert next(row for row in candidates if row['id'] == c['id'])['discarded'] is False
    assert next(row for row in candidates if row['id'] == extra['id'])['discarded'] is True
    assert client.get(root + '/garments/' + confirmed['id'], headers=headers).json() == confirmed
