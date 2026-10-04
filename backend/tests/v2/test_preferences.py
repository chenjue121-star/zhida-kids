import pytest


def test_preferences_versions_and_departure(client, family_factory, auth):
    family, users = family_factory(('admin', 'editor', 'viewer'))
    root = '/v2/families/' + family['id']
    child = client.post(root + '/children', headers=auth(users[0]), json={'nickname': 'Child', 'birthday': '2024-01-01'}).json()
    path = root + '/children/' + child['id']
    members = client.get(root + '/members', headers=auth(users[0])).json()
    editor = next(m for m in members if m['user_id'] == users[1]['user']['id'])
    settings = path + '/preference-settings'
    assert client.patch(settings, headers=auth(users[2]), json={'expected_version': 1, 'mode': 'current_member'}).status_code == 403
    assert client.patch(settings, headers=auth(users[0]), json={'expected_version': 1, 'mode': 'designated_member'}).status_code == 422
    assert client.patch(settings, headers=auth(users[0]), json={'expected_version': 1, 'mode': 'designated_member', 'designated_member_id': editor['id']}).status_code == 200
    assert client.post(root + '/leave', headers=auth(users[1])).status_code == 204
    current = client.get(settings, headers=auth(users[0])).json()
    assert current['mode'] == 'family' and current['designated_member_id'] is None and current['version'] == 3
    for target, version in [('family', 1), ('me', 0)]:
        profile = path + '/profiles/' + target
        assert client.put(profile, headers=auth(users[0]), json={'styles': ['fake'], 'expected_version': version}).status_code == 422
        response = client.put(profile, headers=auth(users[0]), json={'styles': ['sporty'], 'expected_version': version})
        assert response.status_code == 200, response.text
        assert response.json()['version'] == version + 1
        assert client.put(profile, headers=auth(users[0]), json={'styles': [], 'expected_version': version}).status_code == 409


def test_designated_member_family_scope_and_atomic_create(client, family_factory, auth):
    family, users = family_factory()
    foreign, strangers = family_factory()
    foreign_member = client.get('/v2/families/' + foreign['id'] + '/members', headers=auth(strangers[0])).json()[0]
    path = '/v2/families/' + family['id'] + '/children'
    response = client.post(path, headers={**auth(users[0]), 'Idempotency-Key': 'invalid-designation'}, json={
        'nickname': 'Child', 'birthday': '2024-01-01',
        'preferences': {'mode': 'designated_member', 'designated_member_id': foreign_member['id']},
    })
    assert response.status_code == 422
    assert client.get(path, headers=auth(users[0])).json() == []
    from sqlalchemy import select, func
    from app.v2.families.models import MutationReceipt
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(MutationReceipt).where(MutationReceipt.idempotency_key == 'invalid-designation')) == 0


@pytest.mark.parametrize('style', ['clean_daily', 'sporty', 'soft_natural', 'playful_print'])
def test_style_keys_round_trip(client, family_factory, auth, style):
    family, users = family_factory()
    path = '/v2/families/' + family['id'] + '/children'
    child = client.post(path, headers=auth(users[0]), json={'nickname': 'Child', 'birthday': '2024-01-01', 'preferences': {'styles': [style]}}).json()
    assert client.get(path + '/' + child['id'] + '/profiles/family', headers=auth(users[0])).json() == {
        'styles': [style], 'version': 1, 'inferred_tags': [], 'learning_version': 0, 'effective_weights': {style: 1}}
