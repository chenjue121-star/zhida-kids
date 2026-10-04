from datetime import datetime
from uuid import uuid4

import pytest
from test_b_wardrobe_intake import child, draft, confirm


@pytest.fixture
def wardrobe(client, family_factory, auth):
    family, users = family_factory(('admin', 'editor', 'viewer'))
    root, headers = '/v2/families/' + family['id'], auth(users[0])
    kid = child(client, root, headers)
    garments = []
    for category in ('top', 'bottom', 'shoes', 'top', 'bottom'):
        b, _, candidate = draft(client, root, headers, kid['id'], category=category)
        garments.append(confirm(client, root, headers, b, [candidate]).json()['results'][0]['garment'])
    client.app.state.clock = lambda: datetime(2026, 10, 3, 8)
    return root, users, headers, kid, garments


def inputs(kid, **extra):
    return {'child_id': kid['id'], 'target_date': '2026-10-03', 'scene': 'daily',
            'preference_mode': 'family', **extra}


def recommendation(client, root, headers, kid, **extra):
    body = inputs(kid, draft_id=uuid4().hex, request_id=uuid4().hex, **extra)
    response = client.post(root + '/outfits/recommend', headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


def plan_body(kid, garments, **extra):
    return inputs(kid, draft_id=uuid4().hex,
        main_items=[{'garment_id': g['id'], 'expected_version': g['version']} for g in garments],
        backup={'mode': 'none', 'items': []}, locked_ids=[], excluded_ids=[],
        sharing_grants=[], weather_acknowledged=True, **extra)


def save(client, root, headers, body, operation=None):
    review = client.post(root + '/outfits/review', headers=headers, json=body)
    assert review.status_code == 200, review.text
    payload = {**body, 'input_version': review.json()['input_version'], 'operation_id': operation or uuid4().hex}
    response = client.post(root + '/outfits/plans', headers=headers, json=payload)
    return response, payload


def test_context_family_timezone_actual_date_and_scoped_weather(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    client.app.state.clock = lambda: datetime(2026, 10, 3, 16, 30)
    response = client.get(root + '/outfits/context', headers=headers,
                          params={'child_id': kid['id'], 'date_mode': 'tomorrow'})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['today'] == '2026-10-04' and data['target_date'] == '2026-10-05'
    assert data['weather']['status'] == 'unknown'
    assert data['weather']['target_date'] == '2026-10-05'
    assert len(data['garments']) == len(garments) and data['role'] == 'admin'


def test_recommendation_cache_isolates_constraints_preferences_and_measurements(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    first, body = recommendation(client, root, headers, kid)
    second, _ = recommendation(client, root, headers, kid)
    assert second['cached'] and second['recommendation_id'] == first['recommendation_id']
    assert all(item['fit'] == 'fit' for item in first['items'])
    locked, _ = recommendation(client, root, headers, kid, locked_ids=[garments[3]['id']])
    assert garments[3]['id'] in [i['garment_id'] for i in locked['items']]
    assert locked['input_version'] != first['input_version']
    member, _ = recommendation(client, root, headers, kid, preference_mode='current_member')
    assert member['preference_subject']['owner_key'].startswith('member:')
    assert member['input_version'] != first['input_version']
    measurement = client.post(root + '/children/' + kid['id'] + '/measurements', headers=headers,
                             json={'height_cm': 90, 'measured_on': '2026-10-03'})
    assert measurement.status_code == 201
    changed, _ = recommendation(client, root, headers, kid)
    assert changed['input_version'] != first['input_version']
    replay = client.post(root + '/outfits/recommend', headers=headers, json=body)
    assert replay.status_code == 409 and replay.json()['error']['code'] == 'INPUT_CHANGED'


def test_model_failure_falls_back_and_locked_invalid_is_not_silently_dropped(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    class Broken:
        def recommend(self, payload):
            raise TimeoutError('lost response')
    client.app.state.outfit_provider = Broken()
    result, _ = recommendation(client, root, headers, kid)
    assert result['source'] == 'rules' and result['items']
    assert any(w['code'] == 'PROVIDER_UNAVAILABLE' for w in result['warnings'])
    g = garments[0]
    client.put(root + '/garments/' + g['id'], headers=headers,
               json={'state': 'washing', 'expected_version': g['version']})
    result, _ = recommendation(client, root, headers, kid, locked_ids=[g['id']])
    assert not result['items'] and any(m['code'] == 'LOCKED_UNAVAILABLE' for m in result['missing'])


def test_provider_and_weather_release_sql_before_io_then_recheck_permissions(client, wardrobe, auth):
    root, users, headers, kid, _ = wardrobe
    from sqlalchemy import event
    def no_transaction(payload):
        assert not client.app.state.engine.pool.connection.dbapi_connection.in_transaction
        return {'status': 'unknown', 'target_date': payload['target_date'], 'city': 'Shanghai'}
    client.app.state.forecast_provider = no_transaction
    class Downgrade:
        def recommend(self, payload):
            members = client.get(root + '/members', headers=headers).json()
            mid = next(m['id'] for m in members if m['role'] == 'editor')
            version = client.get(root, headers=headers).json()['version']
            assert client.put(root + '/members/' + mid, headers=headers,
                json={'role': 'viewer', 'expected_family_version': version}).status_code == 200
            return {'garment_ids': [g['garment_id'] for g in payload['combinations'][0]]}
    client.app.state.outfit_provider = Downgrade()
    response = client.post(root + '/outfits/recommend', headers=auth(users[1]),
                           json=inputs(kid, draft_id='late', request_id='late'))
    assert response.status_code == 403, response.text


def test_plans_multiplan_snapshots_version_update_and_replay(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    body = plan_body(kid, garments[:3])
    response, payload = save(client, root, headers, body)
    assert response.status_code == 200, response.text
    plan = response.json()['plan']
    replay = client.post(root + '/outfits/plans', headers=headers, json=payload)
    assert replay.json() == response.json()
    second, _ = save(client, root, headers, plan_body(kid, garments[:2]))
    assert second.status_code == 200 and second.json()['plan']['id'] != plan['id']
    assert second.json()['plan']['sequence'] == 2
    g = garments[0]
    client.put(root + '/garments/' + g['id'], headers=headers,
               json={'name': 'later changed', 'expected_version': g['version']})
    context = client.get(root + '/outfits/context', headers=headers,
                         params={'child_id': kid['id'], 'target_date': '2026-10-03'}).json()
    assert context['plans'][0]['main_items'][0]['name'] == g['name']
    historical = client.get(root + '/outfits/operations/' + payload['operation_id'], headers=headers)
    assert historical.json() == response.json()
    changed = plan_body(kid, garments[3:], target_plan_id=plan['id'], expected_version=plan['version'])
    updated, _ = save(client, root, headers, changed)
    assert updated.status_code == 200 and updated.json()['plan']['sequence'] == 1
    assert updated.json()['plan']['version'] == 2
    stale, _ = save(client, root, headers, changed)
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'VERSION_CONFLICT'


def test_unknown_query_resolve_fences_late_save_and_actor_scope(client, wardrobe, auth):
    root, users, headers, kid, garments = wardrobe
    body = plan_body(kid, garments[:2])
    reviewed = client.post(root + '/outfits/review', headers=headers, json=body).json()
    op = uuid4().hex
    payload = {**body, 'input_version': reviewed['input_version'], 'operation_id': op}
    path = root + '/outfits/operations/' + op
    unknown = client.get(path, headers=headers)
    assert unknown.status_code == 200 and unknown.json()['status'] == 'unknown'
    resolved = client.post(path + '/resolve', headers=headers, json=payload)
    assert resolved.status_code == 200 and resolved.json()['error']['code'] == 'NOT_EXECUTED'
    assert client.post(root + '/outfits/plans', headers=headers, json=payload).json() == resolved.json()
    assert client.get(path, headers=auth(users[1])).json()['status'] == 'unknown'
    context = client.get(root + '/outfits/context', headers=headers,
                         params={'child_id': kid['id'], 'target_date': '2026-10-03'}).json()
    assert context['plans'] == []


def test_viewer_can_read_shared_plans_but_cannot_generate_or_change(client, wardrobe, auth):
    root, users, headers, kid, garments = wardrobe
    response, payload = save(client, root, headers, plan_body(kid, garments[:2]))
    assert response.status_code == 200
    viewer = auth(users[2])
    assert client.get(root + '/outfits/context', headers=viewer,
        params={'child_id': kid['id'], 'target_date': '2026-10-03'}).json()['plans']
    for route, body in [('recommend', inputs(kid, draft_id='v', request_id='v')),
                        ('review', plan_body(kid, garments[:2])), ('plans', payload)]:
        assert client.post(root + '/outfits/' + route, headers=viewer, json=body).status_code == 403


def test_candidates_and_backup_have_no_draft_reservations_and_dedup_packing(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    body = plan_body(kid, garments[:2])
    candidates = client.post(root + '/outfits/candidates', headers=headers,
                             json={**body, 'replace_id': garments[0]['id']})
    assert candidates.status_code == 200 and garments[3]['id'] in [g['garment_id'] for g in candidates.json()['items']]
    backup = client.post(root + '/outfits/backup', headers=headers, json={**body, 'mode': 'full'})
    assert backup.status_code == 200 and backup.json()['items']
    review = client.post(root + '/outfits/review', headers=headers, json={**body,
        'backup': {'mode': 'full', 'items': [{'garment_id': g['id'], 'expected_version': g['version']}
                                           for g in garments[3:] + [garments[2]]]}})
    assert review.status_code == 200 and len(review.json()['packing_items']) == 5
    context = client.get(root + '/outfits/context', headers=headers,
                         params={'child_id': kid['id'], 'target_date': '2026-10-03'}).json()
    assert context['occupancy'] == []


def test_weather_io_default_family_location_change_rejects_old_forecast(client, wardrobe):
    root, _, headers, kid, _ = wardrobe
    def changed(payload):
        family = client.get(root, headers=headers).json()
        assert client.put(root, headers=headers, json={'city': 'Beijing',
            'expected_version': family['version']}).status_code == 200
        return {'status': 'known', 'target_date': payload['target_date'], 'city': payload['city'],
                'temp_min': 20, 'temp_max': 25, 'condition': '晴'}
    client.app.state.forecast_provider = changed
    response = client.post(root + '/outfits/recommend', headers=headers,
                           json=inputs(kid, draft_id='old-location', request_id='old-location'))
    assert response.status_code == 409 and response.json()['error']['code'] == 'INPUT_CHANGED'


def test_unavailable_draft_item_can_still_request_replacement_candidates(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    body = plan_body(kid, garments[:2])
    item = garments[0]
    client.put(root + '/garments/' + item['id'], headers=headers,
               json={'state': 'washing', 'expected_version': item['version']})
    response = client.post(root + '/outfits/candidates', headers=headers,
                           json={**body, 'replace_id': item['id']})
    assert response.status_code == 200, response.text
    assert garments[3]['id'] in [g['garment_id'] for g in response.json()['items']]


def test_archived_draft_item_can_be_replaced_without_restoring_the_physical_item(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    body = plan_body(kid, garments[:2])
    operation = uuid4().hex
    response = client.post(root + '/garments/' + garments[0]['id'] + '/archive',
        headers={**headers, 'Idempotency-Key': operation},
        json={'expected_version': garments[0]['version'], 'operation_id': operation})
    assert response.status_code == 200
    candidates = client.post(root + '/outfits/candidates', headers=headers,
                             json={**body, 'replace_id': garments[0]['id']})
    assert candidates.status_code == 200, candidates.text
    assert garments[3]['id'] in [g['garment_id'] for g in candidates.json()['items']]
    assert client.get(root + '/garments/' + garments[0]['id'], headers=headers).json()['archived_at']


@pytest.mark.parametrize('other', ['washing', 'missing_slot'])
def test_candidate_adjustment_can_repair_one_slot_while_other_slots_remain_invalid(client, wardrobe, other):
    root, _, headers, kid, garments = wardrobe
    body = plan_body(kid, garments[:2] if other == 'washing' else garments[:1])
    for item in garments[:2] if other == 'washing' else garments[:1]:
        assert client.put(root + '/garments/' + item['id'], headers=headers,
            json={'state': 'washing', 'expected_version': item['version']}).status_code == 200
    candidates = client.post(root + '/outfits/candidates', headers=headers,
                             json={**body, 'replace_id': garments[0]['id']})
    assert candidates.status_code == 200 and garments[3]['id'] in [i['garment_id'] for i in candidates.json()['items']]
    replaced = {**body, 'main_items': [{'garment_id': garments[3]['id'], 'expected_version': garments[3]['version']}] + body['main_items'][1:]}
    assert not client.post(root + '/outfits/review', headers=headers, json=replaced).json()['valid']


@pytest.mark.parametrize('mode', ['partial', 'full'])
def test_backup_candidates_allow_one_slot_repair_without_approving_remaining_invalid_slots(client, wardrobe, mode):
    root, _, headers, kid, garments = wardrobe
    b, _, choice = draft(client, root, headers, kid['id'], category='top')
    new_top = confirm(client, root, headers, b, [choice]).json()['results'][0]['garment']
    body = plan_body(kid, garments[:2])
    body['backup'] = {'mode': mode, 'items': [
        {'garment_id': item['id'], 'expected_version': item['version'],
         **({'replaces_garment_id': garments[index]['id']} if mode == 'partial' else {})}
        for index, item in enumerate(garments[3:])]}
    for item in (garments[1], garments[4]):
        assert client.put(root + '/garments/' + item['id'], headers=headers,
            json={'state': 'washing', 'expected_version': item['version']}).status_code == 200
    candidates = client.post(root + '/outfits/candidates', headers=headers,
        json={**body, 'usage': 'backup', 'replace_id': garments[3]['id']})
    assert candidates.status_code == 200, candidates.text
    selected = next(i for i in candidates.json()['items'] if i['garment_id'] == new_top['id'])
    if mode == 'partial':
        assert selected['replaces_garment_id'] == garments[0]['id']
    body['backup']['items'][0].update(garment_id=new_top['id'], expected_version=new_top['version'])
    assert not client.post(root + '/outfits/review', headers=headers, json=body).json()['valid']


def test_sampling_timestamp_is_not_weather_input_but_effective_conditions_are(client, wardrobe):
    root, _, headers, kid, _ = wardrobe
    weather = {'status': 'known', 'target_date': '2026-10-03', 'city': 'Shanghai',
               'temp_min': 20, 'temp_max': 25, 'condition': '晴', 'captured_at': 'first'}
    client.app.state.forecast_provider = lambda payload: dict(weather)
    first, _ = recommendation(client, root, headers, kid)
    weather['captured_at'] = 'later'
    same, _ = recommendation(client, root, headers, kid)
    assert same['cached'] and same['input_version'] == first['input_version']
    weather['temp_min'] = 19
    changed, _ = recommendation(client, root, headers, kid)
    assert not changed['cached'] and changed['input_version'] != first['input_version']


def test_invalid_model_choice_cannot_escape_locked_excluded_rules(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    class Invalid:
        def recommend(self, payload):
            return {'garment_ids': ['999999'], 'reason': 'invented'}
    client.app.state.outfit_provider = Invalid()
    result, _ = recommendation(client, root, headers, kid,
        locked_ids=[garments[0]['id']], excluded_ids=[garments[3]['id']])
    assert result['source'] == 'rules'
    assert garments[0]['id'] in [i['garment_id'] for i in result['items']]
    assert garments[3]['id'] not in [i['garment_id'] for i in result['items']]
    assert any(w['code'] == 'PROVIDER_INVALID' for w in result['warnings'])


def test_historical_save_is_readable_by_original_actor_after_viewer_downgrade(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    saved, payload = save(client, root, headers, plan_body(kid, garments[:2]))
    members = client.get(root + '/members', headers=headers).json()
    editor = next(m for m in members if m['role'] == 'editor')
    original = next(m for m in members if m['role'] == 'admin')
    family = client.get(root, headers=headers).json()
    assert client.put(root + '/members/' + editor['id'], headers=headers,
        json={'role': 'admin', 'expected_family_version': family['version']}).status_code == 200
    family = client.get(root, headers=headers).json()
    assert client.put(root + '/members/' + original['id'], headers=headers,
        json={'role': 'viewer', 'expected_family_version': family['version']}).status_code == 200
    assert client.get(root + '/outfits/operations/' + payload['operation_id'], headers=headers).json() == saved.json()
    assert client.post(root + '/outfits/plans', headers=headers, json=payload).status_code == 403


def test_foreign_child_and_foreign_recommendation_cannot_enter_plan(client, wardrobe, family_factory, auth):
    root, _, headers, kid, garments = wardrobe
    family, users = family_factory()
    other_root, other_headers = '/v2/families/' + family['id'], auth(users[0])
    other = child(client, other_root, other_headers)
    denied = client.post(root + '/outfits/recommend', headers=headers,
        json=inputs(other, draft_id=uuid4().hex, request_id=uuid4().hex))
    assert denied.status_code == 404
    foreign, _ = recommendation(client, other_root, other_headers, other)
    saved, _ = save(client, root, headers,
        plan_body(kid, garments[:2], recommendation_id=foreign['recommendation_id']))
    assert saved.status_code == 404
