from uuid import uuid4


def child(client, root, headers, name='小宝'):
    response = client.post(root + '/children', headers=headers,
                           json={'nickname': name, 'age_months': 24})
    assert response.status_code == 201, response.text
    return response.json()


def batch(client, root, headers, child_id):
    response = client.post(root + '/intake/batches', headers={**headers, 'Idempotency-Key': uuid4().hex},
                           json={'default_child_id': child_id})
    assert response.status_code == 201, response.text
    return response.json()


def draft(client, root, headers, child_id, *, category='top', source='manual'):
    b = batch(client, root, headers, child_id)
    path = root + '/intake/batches/' + b['id']
    response = client.post(path + '/items', headers=headers, json={'client_id': uuid4().hex, 'source': source})
    assert response.status_code == 201, response.text
    item = response.json()
    response = client.post(path + '/candidates', headers=headers, json={
        'item_id': item['id'], 'client_id': uuid4().hex, 'name': '蓝上衣', 'category': category, 'colors': ['blue'],
        'pattern': 'unknown', 'thickness': 'unknown', 'owners': [{'child_id': child_id, 'fit': 'fit'}],
        'state': 'ready', 'selected': True,
    })
    assert response.status_code == 201, response.text
    return b, item, response.json()


def confirm(client, root, headers, b, candidates, operation=None, entries=None):
    return client.post(root + '/intake/batches/' + b['id'] + '/confirm', headers=headers, json={
        'operation_id': operation or uuid4().hex,
        'entries': entries or [{'candidate_id': c['id'], 'expected_version': c['version'], 'action': 'new'} for c in candidates],
    })


def garment(client, root, headers, child_id):
    b, _, c = draft(client, root, headers, child_id)
    result = confirm(client, root, headers, b, [c])
    assert result.status_code == 200, result.text
    assert result.json()['counts'] == {'new': 1, 'existing': 0, 'failed': 0}
    return result.json()['results'][0]['garment']


def test_manual_confirm_replay_and_new_operation_do_not_duplicate(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b, _, c = draft(client, root, headers, kid['id'])
    operation = uuid4().hex
    first = confirm(client, root, headers, b, [c], operation)
    assert first.status_code == 200, first.text
    assert confirm(client, root, headers, b, [c], operation).json() == first.json()
    second = confirm(client, root, headers, b, [c])
    assert second.json()['results'][0]['garment']['id'] == first.json()['results'][0]['garment']['id']
    assert second.json()['counts'] == {'new': 0, 'existing': 1, 'failed': 0}
    assert client.get(root + '/garments', headers=headers).json()['total'] == 1
    changed = confirm(client, root, headers, b, [], operation, entries=[{
        'candidate_id': c['id'], 'expected_version': c['version'] + 1, 'action': 'new'}])
    assert changed.status_code == 409
    assert changed.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_partial_confirm_preserves_unselected_and_failed_candidate(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b, item, good = draft(client, root, headers, kid['id'])
    path = root + '/intake/batches/' + b['id']
    bad = client.post(path + '/candidates', headers=headers, json={'item_id': item['id'], 'client_id': uuid4().hex, 'owners': [
        {'child_id': kid['id'], 'fit': 'unknown'}], 'selected': True}).json()
    unselected = client.post(path + '/candidates', headers=headers, json={'item_id': item['id'], 'client_id': uuid4().hex, 'selected': False}).json()
    operation = uuid4().hex
    response = confirm(client, root, headers, b, [good, bad], operation)
    assert response.status_code == 200, response.text
    assert response.json()['counts'] == {'new': 1, 'existing': 0, 'failed': 1}
    assert response.json()['results'][1]['error']['code'] == 'CATEGORY_REQUIRED'
    assert client.get(path + '/operations/' + operation, headers=headers).json() == response.json()
    assert client.get(path + '/operations/not-recorded', headers=headers).json()['status'] == 'unknown'
    current = client.get(path, headers=headers).json()['candidates']
    assert next(c for c in current if c['id'] == unselected['id'])['discarded'] is False
    assert next(c for c in current if c['id'] == bad['id'])['confirmed_garment_id'] is None


def test_owner_fit_is_independent_state_shared_and_transfer_checks_version(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    a, b = child(client, root, headers), child(client, root, headers, '二宝')
    g = garment(client, root, headers, a['id'])
    shared = client.put(root + '/garments/' + g['id'] + '/owners', headers=headers, json={
        'expected_version': g['version'], 'owners': [{'child_id': a['id'], 'fit': 'small'}, {'child_id': b['id'], 'fit': 'large'}]})
    assert shared.status_code == 200, shared.text
    g2 = shared.json()
    assert {o['child_id']: o['fit'] for o in g2['owners']} == {a['id']: 'small', b['id']: 'large'}
    assert client.post(root + '/garments/' + g['id'] + '/transfer', headers=headers, json={
        'expected_version': g['version'], 'child_id': b['id'], 'fit': 'fit'}).status_code == 409
    assert client.post(root + '/garments/' + g['id'] + '/transfer', headers=headers, json={
        'expected_version': g2['version'], 'child_id': b['id'], 'fit': 'fit'}).json()['error']['code'] == 'SHARED_TRANSFER_CONFLICT'
    changed = client.put(root + '/garments/' + g['id'], headers=headers, json={
        'expected_version': g2['version'], 'state': 'washing'}).json()
    for kid in (a, b):
        listed = client.get(root + '/garments', headers=headers, params={'child_id': kid['id']}).json()
        assert listed['items'][0]['id'] == g['id']
        assert listed['items'][0]['state'] == 'washing'
    assert changed['owners'] == g2['owners']


def test_archive_restore_preserves_identity_state_history_and_archived_children(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    a, b = child(client, root, headers), child(client, root, headers, '二宝')
    g = garment(client, root, headers, a['id'])
    g = client.put(root + '/garments/' + g['id'], headers=headers, json={'expected_version': g['version'], 'state': 'missing'}).json()
    path = root + '/garments/' + g['id']
    op = uuid4().hex
    removed = client.post(path + '/archive', headers={**headers, 'Idempotency-Key': op}, json={'expected_version': g['version'], 'operation_id': op})
    assert removed.status_code == 200, removed.text
    r = removed.json()
    op = uuid4().hex
    assert client.post(path + '/archive', headers={**headers, 'Idempotency-Key': op}, json={'expected_version': g['version'], 'operation_id': op}).json() == r
    assert client.delete(root + '/children/' + a['id'], headers=headers, params={'expected_version': a['version']}).status_code == 204
    op = uuid4().hex
    denied = client.post(path + '/restore', headers={**headers, 'Idempotency-Key': op}, json={
        'expected_version': r['version'], 'operation_id': op, 'owners': [{'child_id': a['id'], 'fit': 'fit'}]})
    assert denied.status_code == 404
    op = uuid4().hex
    restored = client.post(path + '/restore', headers={**headers, 'Idempotency-Key': op}, json={
        'expected_version': r['version'], 'operation_id': op, 'owners': [{'child_id': b['id'], 'fit': 'unknown'}]})
    assert restored.status_code == 200, restored.text
    result = restored.json()
    assert result['id'] == g['id'] and result['state'] == 'missing'
    assert result['owners'] == [{'child_id': b['id'], 'nickname': '二宝', 'fit': 'unknown', 'archived': False}]
    assert any(o['child_id'] == a['id'] for o in result['history_owners'])
    op = uuid4().hex
    again = client.post(path + '/restore', headers={**headers, 'Idempotency-Key': op}, json={
        'expected_version': r['version'], 'operation_id': op, 'owners': [{'child_id': b['id'], 'fit': 'large'}]}).json()
    assert again == result


def test_drafts_creator_only_viewer_forbidden_and_foreign_scoped(client, family_factory, auth):
    f, users = family_factory(('admin', 'editor', 'viewer'))
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    b, _, c = draft(client, root, headers, kid['id'])
    path = root + '/intake/batches/' + b['id']
    assert client.get(path, headers=auth(users[1])).status_code == 404
    assert client.get(path, headers=auth(users[2])).status_code == 403
    assert client.get(root + '/intake/batches', headers=auth(users[2])).status_code == 403
    g = confirm(client, root, headers, b, [c]).json()['results'][0]['garment']
    assert client.get(root + '/garments/' + g['id'], headers=auth(users[2])).status_code == 200
    assert client.put(root + '/garments/' + g['id'], headers=auth(users[2]), json={'expected_version': 1, 'name': '改'}).status_code == 403
    foreign, outsiders = family_factory()
    assert client.get('/v2/families/' + foreign['id'] + '/garments/' + g['id'], headers=auth(outsiders[0])).status_code == 404


def test_existing_reuse_requires_owner_review_and_preserves_garment(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    a, b = child(client, root, headers), child(client, root, headers, '二宝')
    existing = garment(client, root, headers, a['id'])
    batch_, _, c = draft(client, root, headers, b['id'])
    entry = {'candidate_id': c['id'], 'expected_version': c['version'], 'action': 'existing',
             'existing_garment_id': existing['id'], 'expected_garment_version': existing['version']}
    failed = confirm(client, root, headers, batch_, [], entries=[entry])
    assert failed.json()['results'][0]['error']['code'] == 'OWNER_REVIEW_REQUIRED'
    shared = client.put(root + '/garments/' + existing['id'] + '/owners', headers=headers, json={
        'expected_version': existing['version'], 'owners': [{'child_id': a['id'], 'fit': 'fit'}, {'child_id': b['id'], 'fit': 'small'}]}).json()
    entry['expected_garment_version'] = shared['version']
    result = confirm(client, root, headers, batch_, [], entries=[entry]).json()
    assert result['counts'] == {'new': 0, 'existing': 1, 'failed': 0}
    assert result['results'][0]['garment'] == shared


def test_bulk_partial_result_and_unknown_query(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    kid = child(client, root, headers)
    a, b = garment(client, root, headers, kid['id']), garment(client, root, headers, kid['id'])
    operation = uuid4().hex
    body = {'operation_id': operation, 'action': 'state', 'state': 'washing', 'items': [
        {'id': a['id'], 'expected_version': a['version']}, {'id': b['id'], 'expected_version': 99}]}
    first = client.post(root + '/garments/bulk', headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert first.json()['counts']['failed'] == 1
    assert client.post(root + '/garments/bulk', headers=headers, json=body).json() == first.json()
    assert client.get(root + '/wardrobe-operations/' + operation, headers=headers).json() == first.json()
    assert client.get(root + '/wardrobe-operations/unknown', headers=headers).json()['status'] == 'unknown'
    assert client.get(root + '/garments/' + b['id'], headers=headers).json()['state'] == 'ready'


def test_removed_filter_and_restore_defaults_use_last_snapshot_only(client, family_factory, auth):
    f, users = family_factory()
    root, headers = '/v2/families/' + f['id'], auth(users[0])
    a, b = child(client, root, headers), child(client, root, headers, '二宝')
    g = garment(client, root, headers, a['id'])
    path = root + '/garments/' + g['id']
    g = client.post(path + '/transfer', headers=headers,
        json={'expected_version': g['version'], 'child_id': b['id'], 'fit': 'large'}).json()
    op = uuid4().hex
    removed = client.post(path + '/archive', headers={**headers, 'Idempotency-Key': op},
        json={'expected_version': g['version'], 'operation_id': op}).json()
    assert {o['child_id'] for o in removed['last_owners']} == {b['id']}
    assert {o['child_id'] for o in removed['history_owners']} == {a['id'], b['id']}
    assert client.get(root + '/garments', headers=headers,
        params={'archived': True, 'history_child_id': a['id']}).json()['total'] == 0
    op = uuid4().hex
    restored = client.post(path + '/restore', headers={**headers, 'Idempotency-Key': op}, json={
        'expected_version': removed['version'], 'operation_id': op, 'owners': [{'child_id': a['id'], 'fit': 'unknown'}]}).json()
    op = uuid4().hex
    again = client.post(path + '/archive', headers={**headers, 'Idempotency-Key': op},
        json={'expected_version': restored['version'], 'operation_id': op}).json()
    assert {o['child_id'] for o in again['last_owners']} == {a['id']}
    assert client.get(root + '/garments', headers=headers,
        params={'archived': True, 'history_child_id': b['id']}).json()['total'] == 0
