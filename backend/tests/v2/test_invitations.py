def test_invitation_repeat_and_removed_access(client, family_factory, login, auth):
    family, users = family_factory(('admin', 'viewer'))
    path = '/v2/families/' + family['id']
    invitation = client.post(path + '/invitations', headers=auth(users[0]), json={'role': 'editor'}).json()
    token = {'token': invitation['token']}
    existing = client.post('/v2/invitations/accept', headers=auth(users[1]), json=token)
    assert existing.status_code == 200
    assert existing.json()['membership']['role'] == 'viewer'
    newcomer = login('newcomer')
    accepted = client.post('/v2/invitations/accept', headers=auth(newcomer), json=token)
    assert accepted.status_code == 200
    assert client.post('/v2/invitations/accept', headers=auth(newcomer), json=token).json() == accepted.json()
    assert client.post('/v2/invitations/accept', headers=auth(login('late')), json=token).status_code == 410
    assert client.delete(path + '/members/' + accepted.json()['membership']['id'], headers=auth(users[0])).status_code == 204
    assert client.get(path, headers=auth(newcomer)).status_code == 404
    assert client.post('/v2/invitations/accept', headers=auth(newcomer), json=token).status_code == 410
    assert client.post('/v2/invitations/preview', headers=auth(users[0]), json={'token': 'bad'}).status_code == 404


def test_last_admin_and_revoke(client, family_factory, auth):
    family, users = family_factory()
    path = '/v2/families/' + family['id']
    assert client.post(path + '/leave', headers=auth(users[0])).status_code == 409
    invitation = client.post(path + '/invitations', headers=auth(users[0]), json={'role': 'viewer'}).json()
    assert client.delete(path + '/invitations/' + invitation['invitation_id'], headers=auth(users[0])).status_code == 204
    assert client.post('/v2/invitations/accept', headers=auth(users[0]), json={'token': invitation['token']}).status_code == 410


def test_expiration_and_minimal_preview(client, family_factory, login, auth):
    from datetime import timedelta
    from app.v2.families.models import Invitation
    family, users = family_factory()
    path = '/v2/families/' + family['id']
    invitation = client.post(path + '/invitations', headers=auth(users[0]), json={'role': 'viewer'}).json()
    token = {'token': invitation['token']}
    guest = login('preview-guest')
    preview = client.post('/v2/invitations/preview', headers=auth(guest), json=token).json()
    assert set(preview) == {'family_name', 'inviter_name', 'role', 'expires_at'}
    with client.app.state.session_factory() as db:
        stored = db.get(Invitation, int(invitation['invitation_id']))
        assert stored.token_hash != invitation['token'] and len(stored.token_hash) == 64
    initial = client.app.state.clock()
    client.app.state.clock = lambda: initial + timedelta(days=8)
    assert client.post('/v2/invitations/preview', headers=auth(guest), json=token).status_code == 410
    assert client.post('/v2/invitations/accept', headers=auth(guest), json=token).status_code == 410


def test_invitation_and_member_scope(client, family_factory, auth):
    one, users = family_factory(('admin', 'editor', 'viewer'))
    other, strangers = family_factory()
    first = '/v2/families/' + one['id']
    second = '/v2/families/' + other['id']
    invitation = client.post(second + '/invitations', headers=auth(strangers[0]), json={}).json()
    assert client.delete(first + '/invitations/' + invitation['invitation_id'], headers=auth(users[0])).status_code == 404
    foreign_member = client.get(second + '/members', headers=auth(strangers[0])).json()[0]
    assert client.delete(first + '/members/' + foreign_member['id'], headers=auth(users[0])).status_code == 404
    for user in users[1:]:
        assert client.post(first + '/invitations', headers=auth(user), json={}).status_code == 403
    assert client.post(first + '/invitations', headers=auth(users[0]), json={'role': 'admin'}).status_code == 422
