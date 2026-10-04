from datetime import datetime


def test_first_child_creates_private_family_once(client, login, auth):
    user = login('first-use-parent')
    client.app.state.clock = lambda: datetime(2026, 9, 22, 4, 0)
    body = {'nickname': '宝贝', 'age_months': 27, 'styles': ['clean_daily']}
    headers = {**auth(user), 'Idempotency-Key': 'first-child-one'}
    created = client.post('/v2/onboarding/child', headers=headers, json=body)
    assert created.status_code == 201, created.text
    result = created.json()
    assert result['child']['birthday'] is None
    assert result['child']['age_months'] == 27
    assert result['child']['age_recorded_on'] == '2026-09-22'
    assert result['child']['preference_summary']['styles'] == ['clean_daily']
    assert result['family']['city'] is None
    assert client.post('/v2/onboarding/child', headers=headers, json=body).json() == result
    assert len(client.get('/v2/families', headers=auth(user)).json()) == 1
    assert len(client.get('/v2/families/' + result['family']['id'] + '/children', headers=auth(user)).json()) == 1


def test_first_child_requires_age_and_rejects_duplicate_initial_child(client, login, auth):
    user = login('first-use-invalid')
    headers = auth(user)
    assert client.post('/v2/onboarding/child', headers=headers, json={'age_months': 84}).status_code == 422
    assert client.post('/v2/onboarding/child', headers=headers, json={'nickname': '宝贝'}).status_code == 422
    assert client.get('/v2/families', headers=headers).json() == []
    first = client.post('/v2/onboarding/child', headers=headers, json={'age_months': 0})
    assert first.status_code == 201
    second = client.post('/v2/onboarding/child', headers=headers, json={'age_months': 5})
    assert second.status_code == 409


def test_age_only_child_and_later_birthday(client, family_factory, auth):
    family, users = family_factory()
    path = '/v2/families/' + family['id'] + '/children'
    created = client.post(path, headers=auth(users[0]), json={'nickname': '小花', 'age_months': 49})
    assert created.status_code == 201, created.text
    child = created.json()
    assert child['birthday'] is None
    assert child['age_months'] == 49
    edited = client.put(path + '/' + child['id'], headers=auth(users[0]), json={
        'birthday': '2022-08-01', 'expected_version': child['version']})
    assert edited.status_code == 200, edited.text
    assert edited.json()['birthday'] == '2022-08-01'
    assert edited.json()['age_months'] is None
