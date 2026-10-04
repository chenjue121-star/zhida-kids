from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture
def engine():
    from app.v2.core.database import load_metadata
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    load_metadata().create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine):
    from app.v2.core.config import V2Settings
    from app.v2.main import create_app
    settings = V2Settings(_env_file=None, database_url='sqlite://', jwt_secret='test-secret-at-least-thirty-two-bytes', env='test')
    with TestClient(create_app(settings, engine, lambda code: {'openid': code, 'nickname': code})) as client:
        yield client


@pytest.fixture
def login(client):
    def login(identity):
        response = client.post('/v2/auth/wechat-login', json={'code': identity})
        assert response.status_code == 200, response.text
        return response.json()
    return login


@pytest.fixture
def auth():
    return lambda user: {'Authorization': 'Bearer ' + user['token']}


@pytest.fixture
def family_factory(client, login, auth):
    def create(roles=('admin',), name='Home'):
        from uuid import uuid4
        users = [login(uuid4().hex) for _ in roles]
        response = client.post('/v2/families', headers=auth(users[0]), json={'name': name, 'city': 'Shanghai'})
        assert response.status_code == 201, response.text
        family = response.json()
        for user, role in zip(users[1:], roles[1:]):
            invitation = client.post(f"/v2/families/{family['id']}/invitations", headers=auth(users[0]), json={'role': role if role != 'admin' else 'editor'}).json()
            joined = client.post('/v2/invitations/accept', headers=auth(user), json={'token': invitation['token']})
            assert joined.status_code == 200, joined.text
            if role == 'admin':
                current = client.get(f"/v2/families/{family['id']}", headers=auth(users[0])).json()
                promoted = client.patch(f"/v2/families/{family['id']}/members/{joined.json()['membership']['id']}", headers=auth(users[0]), json={'role': role, 'expected_family_version': current['version']})
                assert promoted.status_code == 200, promoted.text
        family = client.get(f"/v2/families/{family['id']}", headers=auth(users[0])).json()
        return family, users
    return create
