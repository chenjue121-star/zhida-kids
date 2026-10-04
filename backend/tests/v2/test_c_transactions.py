from copy import deepcopy
from uuid import uuid4
import pytest
from sqlalchemy import event, select, func
from test_c_outfits import wardrobe, plan_body, save, inputs
from test_b_wardrobe_intake import child


def share_item(client, root, headers, garment, kids):
    response = client.put(root + '/garments/' + garment['id'] + '/owners', headers=headers,
        json={'expected_version': garment['version'], 'owners': [{'child_id': k['id'], 'fit': 'fit'} for k in kids]})
    assert response.status_code == 200, response.text
    return response.json()


def sharing_setup(client, wardrobe):
    root, users, headers, first, garments = wardrobe
    second = child(client, root, headers, '另一个孩子')
    shared = [share_item(client, root, headers, g, [first, second]) for g in garments[:2]]
    original, _ = save(client, root, headers, plan_body(first, shared))
    assert original.status_code == 200
    target = plan_body(second, shared)
    return root, headers, first, second, shared, original.json()['plan'], target


def grants(client, root, headers, first, second, shared, body):
    for garment in shared:
        response = client.post(root + '/outfits/sharing', headers=headers, json={**body,
            'garment_id': garment['id'], 'reason': '上午与下午分开准备',
            'periods': [{'child_id': first['id'], 'start': '08:00', 'end': '12:00'},
                        {'child_id': second['id'], 'start': '14:00', 'end': '18:00'}]})
        assert response.status_code == 200, response.text
        body = {**body, 'sharing_grants': body['sharing_grants'] + [response.json()['grant']]}
    return body


def test_cross_child_sources_grants_bind_draft_usage_and_every_plan_version(client, wardrobe):
    root, headers, first, second, shared, _, body = sharing_setup(client, wardrobe)
    review = client.post(root + '/outfits/review', headers=headers, json=body).json()
    assert not review['valid'] and len(review['conflicts']) == 2
    body = grants(client, root, headers, first, second, shared, body)
    assert client.post(root + '/outfits/review', headers=headers, json=body).json()['valid']
    changed = {**body, 'draft_id': uuid4().hex}
    assert not client.post(root + '/outfits/review', headers=headers, json=changed).json()['valid']
    changed = deepcopy(body)
    changed['sharing_grants'][0]['reason'] = '未重新确认'
    assert not client.post(root + '/outfits/review', headers=headers, json=changed).json()['valid']
    new_source, _ = save(client, root, headers, plan_body(first, shared))
    assert new_source.status_code == 200
    outdated = client.post(root + '/outfits/review', headers=headers, json=body).json()
    assert not outdated['valid'] and len(outdated['conflicts'][0]['sources']) == 2
    body = {**body, 'sharing_grants': []}
    body = grants(client, root, headers, first, second, shared, body)
    result, _ = save(client, root, headers, body)
    assert result.status_code == 200, result.text


def test_sharing_blank_overlap_and_partial_periods_are_rejected(client, wardrobe):
    root, headers, first, second, shared, _, body = sharing_setup(client, wardrobe)
    payload = {**body, 'garment_id': shared[0]['id'], 'reason': '   ',
        'periods': [{'child_id': first['id'], 'start': '08:00', 'end': '18:00'},
                    {'child_id': second['id'], 'start': '14:00', 'end': '18:00'}]}
    assert client.post(root + '/outfits/sharing', headers=headers, json=payload).status_code == 422
    response = client.post(root + '/outfits/sharing', headers=headers, json={**payload, 'reason': '明确原因'})
    assert response.status_code == 422 and response.json()['error']['code'] == 'SHARING_PERIODS_OVERLAP'


def test_receipt_failure_rolls_back_plan_revision_and_all_reservations(client, wardrobe, engine):
    root, _, headers, kid, garments = wardrobe
    body = plan_body(kid, garments[:2])
    def reject_receipt(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO wardrobe_operations'):
            raise RuntimeError('forced C receipt rollback')
    event.listen(engine, 'before_cursor_execute', reject_receipt)
    try:
        with pytest.raises(RuntimeError, match='forced C receipt rollback'):
            save(client, root, headers, body)
    finally:
        event.remove(engine, 'before_cursor_execute', reject_receipt)
    from app.v2.outfits.models import OutfitPlan, PlanRevision, Reservation
    with client.app.state.session_factory() as db:
        for model in (OutfitPlan, PlanRevision, Reservation):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_backup_replacement_is_scoped_compatible_and_pending_review_cannot_save(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    body = plan_body(kid, garments[:2])
    body['backup'] = {'mode': 'partial', 'items': [{'garment_id': garments[3]['id'],
        'expected_version': garments[3]['version'], 'replaces_garment_id': garments[0]['id']}]}
    result = client.post(root + '/outfits/candidates', headers=headers,
                         json={**body, 'usage': 'backup', 'replace_id': garments[3]['id']})
    assert result.status_code == 200, result.text
    assert all(i['category'] == 'top' for i in result.json()['items'])
    body['backup_needs_review'] = True
    response, _ = save(client, root, headers, body)
    assert response.status_code == 409 and response.json()['error']['code'] == 'BACKUP_REVIEW_REQUIRED'


def test_latest_snapshot_has_separate_current_warnings_history_receipt_stays_frozen(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    result, payload = save(client, root, headers, plan_body(kid, garments[:2]))
    g = garments[0]
    client.put(root + '/garments/' + g['id'], headers=headers,
               json={'state': 'washing', 'expected_version': g['version']})
    context = client.get(root + '/outfits/context', headers=headers,
                         params={'child_id': kid['id'], 'target_date': '2026-10-03'}).json()
    assert context['plans'][0]['main_items'][0]['state'] == 'ready'
    assert any(w['code'] == 'CURRENT_GARMENT_UNAVAILABLE' for w in context['plans'][0]['current_warnings'])
    assert client.get(root + '/outfits/operations/' + payload['operation_id'], headers=headers).json() == result.json()


def test_original_selected_plan_reports_new_cross_child_usage_without_changing_snapshot(client, wardrobe):
    root, headers, first, second, shared, original, body = sharing_setup(client, wardrobe)
    selected, _ = save(client, root, headers, grants(client, root, headers, first, second, shared, body))
    assert selected.status_code == 200
    context = client.get(root + '/outfits/context', headers=headers,
        params={'child_id': first['id'], 'target_date': '2026-10-03'}).json()
    plan = context['plans'][0]
    assert any(w['code'] == 'CURRENT_OCCUPANCY_CHANGED' for w in plan['current_warnings'])
    assert {k: v for k, v in plan.items() if k != 'current_warnings'} == original


def test_recommendation_cache_includes_backup_and_replay_checks_current_inputs(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    from test_c_outfits import recommendation
    first, initial = recommendation(client, root, headers, kid)
    with_backup = plan_body(kid, garments[:2])
    with_backup['backup'] = {'mode': 'partial', 'items': [{'garment_id': garments[3]['id'],
        'expected_version': garments[3]['version'], 'replaces_garment_id': garments[0]['id']}]}
    second, _ = recommendation(client, root, headers, kid, **{k: v for k, v in with_backup.items()
        if k not in ('child_id', 'target_date', 'scene', 'preference_mode', 'draft_id')})
    assert second['input_version'] != first['input_version']
    client.put(root + '/garments/' + garments[0]['id'], headers=headers,
               json={'state': 'washing', 'expected_version': garments[0]['version']})
    response = client.post(root + '/outfits/recommend', headers=headers, json=initial)
    assert response.status_code == 409 and response.json()['error']['code'] == 'INPUT_CHANGED'


def test_rules_block_thin_cold_layers_and_uncoordinated_provider_choices():
    from test_c_rules import item
    from app.v2.outfits import rules
    result = rules.generate([item(1, 'top', thickness='thin'), item(2, 'bottom', thickness='thin'),
                            item(3, 'outerwear', thickness='thin')], scene='daily', age_months=24,
                            weather={'status': 'known', 'temp_min': 4, 'temp_max': 8}, comfort={}, styles=[])
    assert not result['items']
    assert rules.validate([item(1, 'top', pattern='print', colors=['red', 'purple']),
                           item(2, 'bottom', pattern='plaid', colors=['orange', 'green'])],
                           'daily', 24, {'status': 'unknown'}, {})


@pytest.mark.parametrize('mode', ['partial', 'full'])
def test_excluded_backup_cannot_be_saved_or_occupied(client, wardrobe, mode):
    root, _, headers, kid, garments = wardrobe
    body = plan_body(kid, garments[:2])
    spare = [{'garment_id': garments[3]['id'], 'expected_version': garments[3]['version'],
              'replaces_garment_id': garments[0]['id']}]
    if mode == 'full':
        spare.append({'garment_id': garments[4]['id'], 'expected_version': garments[4]['version']})
    body.update(backup={'mode': mode, 'items': spare}, excluded_ids=[garments[3]['id']])
    result, _ = save(client, root, headers, body)
    assert result.status_code == 409 and result.json()['error']['code'] == 'EXCLUDED_ITEM'


def test_third_child_cannot_silently_rewrite_both_sides_of_existing_schedule(client, wardrobe):
    root, _, headers, first, garments = wardrobe
    second = child(client, root, headers, 'second')
    third = child(client, root, headers, 'third')
    shared = [share_item(client, root, headers, g, [first, second, third]) for g in garments[:2]]
    initial, _ = save(client, root, headers, plan_body(first, shared))
    assert initial.status_code == 200
    second_body = grants(client, root, headers, first, second, shared, plan_body(second, shared))
    selected, _ = save(client, root, headers, second_body)
    assert selected.status_code == 200
    third_body = plan_body(third, shared)
    response = client.post(root + '/outfits/sharing', headers=headers, json={**third_body,
        'garment_id': shared[0]['id'], 'reason': '三人分开准备', 'periods': [
            {'child_id': first['id'], 'start': '10:00', 'end': '12:00'},
            {'child_id': second['id'], 'start': '14:00', 'end': '18:00'},
            {'child_id': third['id'], 'start': '08:00', 'end': '10:00'}]})
    assert response.status_code == 409 and response.json()['error']['code'] == 'SHARING_REVIEW_REQUIRED'


def test_update_receipt_failure_retains_original_revision_and_all_old_usage(client, wardrobe, engine):
    root, _, headers, kid, garments = wardrobe
    original, payload = save(client, root, headers, plan_body(kid, garments[:2]))
    plan = original.json()['plan']
    edit = plan_body(kid, garments[3:], target_plan_id=plan['id'], expected_version=plan['version'])
    def reject_receipt(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO wardrobe_operations'):
            raise RuntimeError('update C receipt rollback')
    event.listen(engine, 'before_cursor_execute', reject_receipt)
    try:
        with pytest.raises(RuntimeError, match='update C receipt rollback'):
            save(client, root, headers, edit)
    finally:
        event.remove(engine, 'before_cursor_execute', reject_receipt)
    context = client.get(root + '/outfits/context', headers=headers,
                         params={'child_id': kid['id'], 'target_date': '2026-10-03'}).json()
    assert context['plans'][0]['version'] == 1
    assert {r['garment_id'] for r in context['occupancy']} == {g['id'] for g in garments[:2]}
    assert client.get(root + '/outfits/operations/' + payload['operation_id'], headers=headers).json() == original.json()
