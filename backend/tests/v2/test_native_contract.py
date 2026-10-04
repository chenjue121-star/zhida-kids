def test_put_supports_all_native_updates(client, family_factory, auth):
    family, users = family_factory(('admin', 'editor'))
    headers = auth(users[0])
    root = '/v2/families/' + family['id']
    result = client.put(root, headers=headers, json={'name': 'Updated', 'expected_version': family['version']})
    assert result.status_code == 200
    members = client.get(root + '/members', headers=headers).json()
    editor = next(m for m in members if m['role'] == 'editor')
    assert client.put(root + '/members/' + editor['id'], headers=headers, json={
        'role': 'viewer', 'expected_family_version': result.json()['version'],
    }).status_code == 200
    child = client.post(root + '/children', headers=headers, json={'nickname': 'Child', 'birthday': '2024-01-01'}).json()
    path = root + '/children/' + child['id']
    assert client.put(path, headers=headers, json={'nickname': 'New', 'expected_version': 1}).status_code == 200
    assert client.put(path + '/preference-settings', headers=headers, json={
        'mode': 'current_member', 'expected_version': 1,
    }).status_code == 200
    assert client.put(path, headers=auth(users[1]), json={'nickname': 'Forbidden', 'expected_version': 2}).status_code == 403


def test_member_profile_read_is_scoped_and_read_only(client, family_factory, auth):
    family, users = family_factory(('admin', 'editor', 'viewer'))
    foreign, strangers = family_factory()
    root = '/v2/families/' + family['id']
    child = client.post(root + '/children', headers=auth(users[0]), json={'nickname': 'Child', 'birthday': '2024-01-01'}).json()
    path = root + '/children/' + child['id']
    members = client.get(root + '/members', headers=auth(users[0])).json()
    editor = next(m for m in members if m['role'] == 'editor')
    result = client.put(path + '/profiles/me', headers=auth(users[1]), json={'styles': ['sporty'], 'expected_version': 0})
    assert result.status_code == 200
    endpoint = path + '/profiles/members/' + editor['id']
    result = client.get(endpoint, headers=auth(users[2]))
    assert result.status_code == 200
    assert result.json() == {'styles': ['sporty'], 'version': 1, 'inferred_tags': [],
                             'learning_version': 0, 'effective_weights': {'sporty': 1}}
    assert client.put(endpoint, headers=auth(users[0]), json={'styles': [], 'expected_version': 1}).status_code == 405
    assert client.get(endpoint, headers=auth(strangers[0])).status_code == 404
    foreign_member = client.get('/v2/families/' + foreign['id'] + '/members', headers=auth(strangers[0])).json()[0]
    assert client.get(path + '/profiles/members/' + foreign_member['id'], headers=auth(users[0])).status_code == 404
    client.post(root + '/leave', headers=auth(users[1]))
    assert client.get(endpoint, headers=auth(users[0])).status_code == 404
