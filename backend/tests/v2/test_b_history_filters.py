from uuid import uuid4
from test_b_wardrobe_intake import child, garment


def test_history_users_include_all_pages_and_archived_children(client, family_factory, auth):
    family, users = family_factory(('admin', 'viewer'))
    root, headers = '/v2/families/' + family['id'], auth(users[0])
    first = child(client, root, headers, '第一页宝贝')
    later = child(client, root, headers, '后续页宝贝')
    for kid in (first, later):
        g = garment(client, root, headers, kid['id'])
        operation = uuid4().hex
        response = client.post(root + '/garments/' + g['id'] + '/archive',
            headers={**headers, 'Idempotency-Key': operation},
            json={'operation_id': operation, 'expected_version': g['version']})
        assert response.status_code == 200, response.text
    assert client.delete(root + '/children/' + later['id'], headers=headers,
                         params={'expected_version': later['version']}).status_code == 204
    response = client.get(root + '/garments', headers=auth(users[1]),
                          params={'archived': True, 'limit': 1})
    assert response.status_code == 200
    page = response.json()
    assert len(page['items']) == 1 and page['next_cursor']
    expected = [{'id': first['id'], 'nickname': first['nickname'], 'archived': False},
                {'id': later['id'], 'nickname': later['nickname'], 'archived': True}]
    assert page['history_children'] == expected
    filtered = client.get(root + '/garments', headers=headers,
                          params={'archived': True, 'history_child_id': later['id']}).json()
    assert filtered['total'] == 1
    assert filtered['history_children'] == expected
    other, others = family_factory()
    other_page = client.get('/v2/families/' + other['id'] + '/garments',
                            headers=auth(others[0]), params={'archived': True}).json()
    assert other_page['history_children'] == []
