from uuid import uuid4
import pytest
from sqlalchemy import event, func, select
from test_c_outfits import wardrobe, plan_body, save
from test_b_wardrobe_intake import child


def make_plan(client, wardrobe):
    root, _, headers, kid, gs = wardrobe
    result, payload = save(client, root, headers, plan_body(kid, gs[:2])); assert result.status_code == 200
    return result.json()['plan'], payload


def test_calendar_multi_ranges_viewer_and_scopes(client, wardrobe, auth, family_factory):
    root, users, headers, kid, _ = wardrobe
    first, _ = make_plan(client, wardrobe); second, _ = make_plan(client, wardrobe)
    response = client.get(root + '/outfits/calendar', headers=auth(users[2]), params={'start_date': '2026-10-01', 'end_date': '2026-10-31', 'child_id': kid['id']})
    assert response.status_code == 200, response.text
    assert [p['id'] for p in response.json()['plans']] == [first['id'], second['id']]
    assert response.json()['role'] == 'viewer' and response.json()['timezone'] == 'Asia/Shanghai'
    assert all(p['status'] == 'selected' for p in response.json()['plans'])
    assert client.get(root + '/outfits/plans/' + first['id'], headers=headers).json() == first
    for dates in [('2026-12-01', '2026-10-01'), ('2026-01-01', '2026-12-31')]:
        assert client.get(root + '/outfits/calendar', headers=headers, params={'start_date': dates[0], 'end_date': dates[1]}).status_code == 422
    foreign, strangers = family_factory(); foreign_root = '/v2/families/' + foreign['id']
    assert client.get(foreign_root + '/outfits/plans/' + first['id'], headers=auth(strangers[0])).status_code == 404
    assert client.get(foreign_root + '/outfits/calendar', headers=auth(strangers[0]), params={'start_date': '2026-10-01', 'end_date': '2026-10-31', 'child_id': kid['id']}).status_code == 404


def test_cancel_idempotent_releases_usage_preserves_history_refuses_edit(client, wardrobe):
    root, _, headers, kid, gs = wardrobe; plan, payload = make_plan(client, wardrobe)
    url = root + '/outfits/plans/' + plan['id']; body = {'expected_version': 1, 'operation_id': uuid4().hex}
    response = client.post(url + '/cancel', headers=headers, json=body); assert response.status_code == 200, response.text
    result = response.json(); assert result['plan']['status'] == 'cancelled' and result['plan']['version'] == 2 and result['plan']['cancelled_at']
    assert client.post(url + '/cancel', headers=headers, json=body).json() == result
    assert client.get(root + '/outfits/operations/' + body['operation_id'], headers=headers).json() == result
    assert client.post(url + '/cancel', headers=headers, json={**body, 'expected_version': 2}).status_code == 409
    ctx = client.get(root + '/outfits/context', headers=headers, params={'child_id': kid['id'], 'target_date': plan['target_date']}).json()
    assert ctx['plans'] == [] and ctx['occupancy'] == []
    query = {'start_date': plan['target_date'], 'end_date': plan['target_date']}
    assert client.get(root + '/outfits/calendar', headers=headers, params=query).json()['plans'] == []
    assert client.get(root + '/outfits/calendar', headers=headers, params={**query, 'include_cancelled': True}).json()['plans'][0] == result['plan']
    assert client.get(root + '/outfits/operations/' + payload['operation_id'], headers=headers).json()['plan'] == plan
    from app.v2.outfits.models import PlanRevision, Reservation
    with client.app.state.session_factory() as db:
        assert db.scalar(select(PlanRevision).where(PlanRevision.plan_id == int(plan['id']), PlanRevision.version == 1)).snapshot == plan
        assert db.scalar(select(func.count()).select_from(Reservation)) == 0
    rejected, _ = save(client, root, headers, plan_body(kid, gs[:2], target_plan_id=plan['id'], expected_version=2))
    assert rejected.status_code == 409 and rejected.json()['error']['code'] == 'PLAN_CANCELLED'


def test_cancel_resolve_fences_late_cancel(client, wardrobe):
    root, _, headers, _, _ = wardrobe; plan, _ = make_plan(client, wardrobe)
    url = root + '/outfits/plans/' + plan['id'] + '/cancel'; body = {'expected_version': 1, 'operation_id': uuid4().hex}
    result = client.post(url + '/resolve', headers=headers, json=body)
    assert result.status_code == 200 and result.json()['error']['code'] == 'NOT_EXECUTED'
    assert client.post(url, headers=headers, json=body).json() == result.json()
    assert client.get(root + '/outfits/plans/' + plan['id'], headers=headers).json()['status'] == 'selected'


def test_cancel_viewer_refused_and_receipt_failure_rolls_back(client, wardrobe, auth, engine):
    root, users, headers, _, _ = wardrobe; plan, _ = make_plan(client, wardrobe)
    url = root + '/outfits/plans/' + plan['id'] + '/cancel'; body = {'expected_version': 1, 'operation_id': uuid4().hex}
    assert client.post(url, headers=auth(users[2]), json=body).status_code == 403
    def reject(c, cursor, statement, p, ctx, many):
        if statement.startswith('INSERT INTO wardrobe_operations'): raise RuntimeError('D cancel rollback')
    event.listen(engine, 'before_cursor_execute', reject)
    try:
        with pytest.raises(RuntimeError, match='D cancel rollback'): client.post(url, headers=headers, json=body)
    finally: event.remove(engine, 'before_cursor_execute', reject)
    assert client.get(root + '/outfits/plans/' + plan['id'], headers=headers).json() == plan
    from app.v2.outfits.models import Reservation
    with client.app.state.session_factory() as db: assert db.scalar(select(func.count()).select_from(Reservation)) == 2


def test_reuse_target_weather_current_versions_unavailable_and_no_write(client, wardrobe, auth):
    root, users, headers, kid, gs = wardrobe; plan, _ = make_plan(client, wardrobe)
    assert client.put(root + '/garments/' + gs[0]['id'], headers=headers, json={'expected_version': 1, 'state': 'washing'}).status_code == 200
    client.app.state.forecast_provider = lambda p: {'status': 'known', 'target_date': p['target_date'], 'temp_min': 19, 'temp_max': 24}
    url = root + '/outfits/plans/' + plan['id'] + '/reuse'; body = {'expected_source_version': 1, 'child_id': kid['id'], 'target_date': '2026-10-08', 'draft_id': uuid4().hex}
    assert client.post(url, headers=auth(users[2]), json=body).status_code == 403
    response = client.post(url, headers=headers, json=body); assert response.status_code == 200, response.text
    data = response.json(); d = data['draft']
    assert data['source_plan_id'] == plan['id'] and data['source_version'] == 1
    assert d['target_date'] == '2026-10-08' and d['target_plan_id'] is None and d['recommendation_id'] is None
    assert d['sharing_grants'] == [] and d['locked_ids'] == [] and d['excluded_ids'] == [] and d['action_id']
    assert d['main_items'][0]['expected_version'] == 2 and data['context']['weather']['target_date'] == '2026-10-08'
    assert not data['review']['valid'] and data['review']['missing']
    from app.v2.outfits.models import OutfitPlan, Reservation
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(OutfitPlan)) == 1 and db.scalar(select(func.count()).select_from(Reservation)) == 2
    assert client.post(url, headers=headers, json={**body, 'expected_source_version': 999}).status_code == 409


def test_cancelled_source_cross_child_and_archive_history(client, wardrobe):
    root, _, headers, kid, gs = wardrobe; plan, _ = make_plan(client, wardrobe); url = root + '/outfits/plans/' + plan['id']
    assert client.post(url + '/cancel', headers=headers, json={'expected_version': 1, 'operation_id': uuid4().hex}).status_code == 200
    body = {'expected_source_version': 2, 'child_id': kid['id'], 'target_date': '2026-10-08', 'draft_id': uuid4().hex}
    assert client.post(url + '/reuse', headers=headers, json=body).status_code == 200
    other = child(client, root, headers, 'Another'); data = client.post(url + '/reuse', headers=headers, json={**body, 'child_id': other['id']}).json()
    assert [str(i['garment_id']) for i in data['draft']['main_items']] == [g['id'] for g in gs[:2]] and not data['review']['valid']
    assert client.request('DELETE', root + '/children/' + kid['id'], headers=headers, params={'expected_version': kid['version']}).status_code == 204
    assert client.get(url, headers=headers).status_code == 200
    assert client.get(root + '/outfits/calendar', headers=headers, params={'start_date': '2026-10-01', 'end_date': '2026-10-31', 'child_id': kid['id'], 'include_cancelled': True}).status_code == 200
    assert client.post(url + '/reuse', headers=headers, json=body).status_code == 404


def test_reuse_cross_child_uses_current_physical_version_even_without_owner_relation(client, wardrobe):
    root, _, headers, _, garments = wardrobe
    plan, _ = make_plan(client, wardrobe)
    g = garments[0]
    assert client.put(root + '/garments/' + g['id'], headers=headers,
        json={'expected_version': g['version'], 'name': 'Updated physical item'}).status_code == 200
    target = child(client, root, headers, 'Target child')
    response = client.post(root + '/outfits/plans/' + plan['id'] + '/reuse', headers=headers,
        json={'expected_source_version': 1, 'child_id': target['id'], 'target_date': '2026-10-08', 'draft_id': uuid4().hex})
    assert response.status_code == 200
    assert response.json()['draft']['main_items'][0]['expected_version'] == 2
    assert not response.json()['review']['valid']
