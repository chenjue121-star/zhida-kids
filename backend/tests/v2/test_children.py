import pytest


def test_children_measurements_archive_and_scope(client, family_factory, auth):
    family, users = family_factory(('admin', 'viewer'))
    path = '/v2/families/' + family['id'] + '/children'
    body = {'nickname': 'Child', 'birthday': '2024-01-01'}
    assert client.post(path, headers=auth(users[1]), json=body).status_code == 403
    assert client.post(path, headers=auth(users[0]), json={**body, 'birthday': '2099-01-01'}).status_code == 422
    headers = {**auth(users[0]), 'Idempotency-Key': 'child-once'}
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 201, response.text
    child = response.json()
    assert child['latest_measurement'] is None
    assert client.post(path, headers=headers, json=body).json() == child
    detail = path + '/' + child['id']
    other, other_users = family_factory()
    assert client.get('/v2/families/' + other['id'] + '/children/' + child['id'], headers=auth(other_users[0])).status_code == 404
    for invalid in [{'height_cm': 0}, {'weight_kg': -1}, {}]:
        assert client.post(detail + '/measurements', headers=auth(users[0]), json={**invalid, 'measured_on': '2025-01-01'}).status_code == 422
    for height in [90, 91]:
        assert client.post(detail + '/measurements', headers=auth(users[0]), json={'height_cm': height, 'measured_on': '2025-01-01'}).status_code == 201
    assert client.get(detail, headers=auth(users[0])).json()['latest_measurement']['height_cm'] == 91
    assert client.patch(detail, headers=auth(users[0]), json={'nickname': 'Updated', 'expected_version': 1}).status_code == 200
    assert client.delete(detail + '?expected_version=1', headers=auth(users[0])).status_code == 409
    assert client.delete(detail + '?expected_version=2', headers=auth(users[0])).status_code == 204
    assert client.get(detail, headers=auth(users[0])).status_code == 404
    assert client.get(path, headers=auth(users[0])).json() == []


@pytest.mark.parametrize('role,expected', [('admin', 201), ('editor', 201), ('viewer', 403)])
def test_child_write_matrix(client, family_factory, auth, role, expected):
    family, users = family_factory(('admin', role))
    response = client.post('/v2/families/' + family['id'] + '/children', headers=auth(users[1]), json={'nickname': 'Child', 'birthday': '2024-01-01'})
    assert response.status_code == expected


def test_partial_patch_null_and_field_injection(client, family_factory, auth):
    family, users = family_factory()
    path = '/v2/families/' + family['id'] + '/children'
    child = client.post(path, headers=auth(users[0]), json={'nickname': 'Child', 'birthday': '2024-01-01', 'skin_tone': 'medium'}).json()
    detail = path + '/' + child['id']
    response = client.patch(detail, headers=auth(users[0]), json={'skin_tone': None, 'expected_version': 1})
    assert response.json()['skin_tone'] is None and response.json()['nickname'] == 'Child'
    for body in [{'height_cm': 10}, {'family_id': '999'}, {'nickname': None}, {'birthday': None}]:
        assert client.patch(detail, headers=auth(users[0]), json={**body, 'expected_version': 2}).status_code == 422
    assert client.delete(detail, headers=auth(users[0])).status_code == 422


def test_family_local_dates(client, family_factory, auth):
    from datetime import datetime
    family, users = family_factory()
    root = '/v2/families/' + family['id']
    client.app.state.clock = lambda: datetime(2025, 1, 1, 23, 30)
    assert client.patch(root, headers=auth(users[0]), json={'timezone': 'Pacific/Honolulu', 'expected_version': family['version']}).status_code == 200
    body = {'nickname': 'Child', 'birthday': '2025-01-02'}
    assert client.post(root + '/children', headers=auth(users[0]), json=body).status_code == 422
    assert client.patch(root, headers=auth(users[0]), json={'timezone': 'Asia/Shanghai', 'expected_version': family['version'] + 1}).status_code == 200
    assert client.post(root + '/children', headers=auth(users[0]), json=body).status_code == 201


def test_measurement_receipt_and_permission_replay(client, family_factory, auth):
    family, users = family_factory(('admin', 'editor'))
    root = '/v2/families/' + family['id']
    child = client.post(root + '/children', headers=auth(users[1]), json={'nickname': 'Child', 'birthday': '2024-01-01'}).json()
    path = root + '/children/' + child['id'] + '/measurements'
    headers = {**auth(users[1]), 'Idempotency-Key': 'measurement-once'}
    body = {'weight_kg': 12, 'measured_on': '2025-01-01'}
    one = client.post(path, headers=headers, json=body)
    assert one.status_code == 201
    assert client.post(path, headers=headers, json=body).json() == one.json()
    assert client.post(path, headers=headers, json={**body, 'weight_kg': 13}).status_code == 409
    assert client.post(root + '/leave', headers=auth(users[1])).status_code == 204
    assert client.post(path, headers=headers, json=body).status_code == 404


@pytest.mark.parametrize('value', ['Infinity', '-Infinity', 'NaN', 0, -1, 0.001])
def test_measurements_must_be_finite_positive(value):
    from app.v2.children.schemas import MeasurementCreate
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MeasurementCreate(height_cm=value, measured_on='2025-01-01')
