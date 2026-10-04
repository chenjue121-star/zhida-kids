import pytest


def test_family_access_and_idempotency(client, family_factory, login, auth):
    family, users = family_factory(('admin', 'editor', 'viewer'))
    path = '/v2/families/' + family['id']
    for user in users:
        assert client.get(path, headers=auth(user)).status_code == 200
        members = client.get(path + '/members', headers=auth(user)).json()
        assert len(members) == 3
        assert set(members[0]) == {'id', 'user_id', 'role', 'nickname', 'status'}
    assert client.get(path, headers=auth(login('outsider'))).status_code == 404
    assert client.get(path).status_code == 401
    for user in users[1:]:
        assert client.patch(path, headers=auth(user), json={'name': 'Other', 'expected_version': family['version']}).status_code == 403
    assert client.patch(path, headers=auth(users[0]), json={'name': 'New', 'expected_version': family['version']}).status_code == 200
    assert client.patch(path, headers=auth(users[0]), json={'name': 'Old', 'expected_version': family['version']}).status_code == 409
    headers = {**auth(users[0]), 'Idempotency-Key': 'family-once'}
    body = {'name': 'Replay', 'city': 'Shanghai'}
    first = client.post('/v2/families', headers=headers, json=body)
    second = client.post('/v2/families', headers=headers, json=body)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert client.post('/v2/families', headers=headers, json={**body, 'name': 'different'}).status_code == 409


@pytest.mark.parametrize('body', [{'name': ' ', 'city': 'City'}, {'name': 'Name', 'city': ''},
                                 {'name': 'Name', 'city': 'City', 'timezone': 'Not/AZone'},
                                 {'name': 'Name', 'city': 'City', 'created_by': '1'}])
def test_invalid_family_fields(client, login, auth, body):
    assert client.post('/v2/families', headers=auth(login('user')), json=body).status_code == 422


def test_family_receipt_replay_checks_current_membership(client, family_factory, auth):
    family, users = family_factory(('admin', 'admin'))
    headers = {**auth(users[0]), 'Idempotency-Key': 'lost-membership'}
    body = {'name': 'Replay', 'city': 'City'}
    created = client.post('/v2/families', headers=headers, json=body).json()
    from app.v2.families.models import Membership
    from sqlalchemy import select
    with client.app.state.session_factory.begin() as db:
        member = db.scalar(select(Membership).where(Membership.family_id == int(created['id'])))
        member.status = 'removed'
    assert client.post('/v2/families', headers=headers, json=body).status_code == 404


def test_ids_above_javascript_integer_limit_are_strings(client, auth):
    from app.v2.identity.models import User
    from app.v2.families.models import Family, Membership
    from app.v2.identity.tokens import issue_token
    large = 9007199254740993
    with client.app.state.session_factory.begin() as db:
        user = User(id=large, openid='large-id', nickname='Large')
        db.add(user)
        db.flush()
        family = Family(id=large + 1, name='Large', city='City', created_by=user.id)
        db.add(family)
        db.flush()
        db.add(Membership(id=large + 2, family_id=family.id, user_id=user.id, role='admin'))
        token, _ = issue_token(user, client.app.state.settings)
    headers = {'Authorization': 'Bearer ' + token}
    me = client.get('/v2/me', headers=headers).json()
    assert me['user']['id'] == str(large)
    assert me['families'][0]['id'] == str(large + 1)
    assert me['memberships'][0]['id'] == str(large + 2)
    assert me['memberships'][0]['family_id'] == str(large + 1)
    assert me['memberships'][0]['user_id'] == str(large)


def test_failed_receipt_rolls_back_family_and_admin(client, login, auth):
    from sqlalchemy import event, select, func
    from fastapi.testclient import TestClient
    from app.v2.families.models import Family, Membership, MutationReceipt
    user = login('rollback')
    def reject_receipt(mapper, connection, target):
        raise RuntimeError('simulated storage failure')
    event.listen(MutationReceipt, 'before_insert', reject_receipt)
    try:
        with TestClient(client.app, raise_server_exceptions=False) as requester:
            response = requester.post('/v2/families', headers={**auth(user), 'Idempotency-Key': 'rollback'}, json={'name': 'Lost', 'city': 'City'})
            assert response.status_code == 500
            assert response.json()['error']['code'] == 'INTERNAL_ERROR'
        with client.app.state.session_factory() as db:
            for model in (Family, Membership, MutationReceipt):
                assert db.scalar(select(func.count()).select_from(model)) == 0
    finally:
        event.remove(MutationReceipt, 'before_insert', reject_receipt)
