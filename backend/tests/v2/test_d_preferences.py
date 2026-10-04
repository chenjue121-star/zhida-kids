from copy import deepcopy
from uuid import uuid4
import pytest
from sqlalchemy import event, func, select
from test_c_outfits import wardrobe, plan_body, save, recommendation


def path(root, kid, target='family'):
    return root + '/children/' + kid['id'] + '/profiles/' + target


def plans(client, wardrobe, n=3, **extra):
    root, _, headers, kid, gs = wardrobe
    result = []
    for _ in range(n):
        response, _ = save(client, root, headers, plan_body(kid, gs[:2], **extra))
        assert response.status_code == 200, response.text
        result.append(response.json()['plan'])
    return result


def feedback(client, root, headers, kid, plan, **extra):
    body = {'event_id': uuid4().hex, 'plan_id': plan['id'], 'plan_version': plan['version'],
            'signal': 'like', 'reason': 'aesthetic', 'styles': ['playful_print'], **extra}
    return client.post(root + '/children/' + kid['id'] + '/feedback', headers=headers, json=body), body


def test_feedback_distinct_plans_idempotence_immutable_events_and_explicit_priority(client, wardrobe):
    root, _, headers, kid, _ = wardrobe
    for i, plan in enumerate(plans(client, wardrobe)):
        response, body = feedback(client, root, headers, kid, plan)
        assert response.status_code == 200, response.text
        if i < 2: assert not any(t['style'] == 'playful_print' for t in response.json()['profile']['inferred_tags'])
    data = response.json(); tag = next(t for t in data['profile']['inferred_tags'] if t['style'] == 'playful_print')
    assert tag['direction'] == 'like' and tag['evidence_count'] == 3 and 0 < tag['weight'] <= .5
    assert len({e['plan_id'] for e in tag['evidence']}) == 3 and tag['rule_version']
    assert data['event']['actor_id'] and data['event']['source_subject']['owner_key'] == 'family'
    url = root + '/children/' + kid['id'] + '/feedback'
    assert client.post(url, headers=headers, json=body).json()['event'] == data['event']
    assert client.post(url, headers=headers, json={**body, 'signal': 'dislike'}).status_code == 409
    from app.v2.preferences.models import FeedbackEvent
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(FeedbackEvent).where(FeedbackEvent.signal == 'like')) == 3
        raw = db.scalar(select(FeedbackEvent)); raw.reason = 'washing'
        with pytest.raises(ValueError, match='immutable'): db.flush()
    explicit = client.put(path(root, kid), headers=headers, json={'styles': ['playful_print'], 'expected_version': data['profile']['version']})
    assert explicit.status_code == 200 and explicit.json()['effective_weights']['playful_print'] == 1


@pytest.mark.parametrize('reason', ['comfort', 'washing', 'missing', 'too_small', 'skip'])
def test_temporary_and_comfort_reasons_do_not_learn_aesthetics(client, wardrobe, reason):
    root, _, headers, kid, _ = wardrobe
    for plan in plans(client, wardrobe):
        response, _ = feedback(client, root, headers, kid, plan, signal='dislike', reason=reason)
        assert response.status_code == 200 and response.json()['event']['reason'] == reason
    assert not any(t['style'] == 'playful_print' for t in response.json()['profile']['inferred_tags'])


def test_same_plan_does_not_accumulate_and_dismiss_cutoff_requires_new_evidence(client, wardrobe):
    root, _, headers, kid, _ = wardrobe
    source = plans(client, wardrobe)
    for _ in range(4):
        response, _ = feedback(client, root, headers, kid, source[0]); assert response.status_code == 200
    assert not any(t['style'] == 'playful_print' for t in response.json()['profile']['inferred_tags'])
    for p in source[1:]: response, _ = feedback(client, root, headers, kid, p)
    previous = response.json()['profile']; url = path(root, kid) + '/tags/playful_print'
    dismissed = client.post(url, headers=headers, json={'expected_version': previous['version'], 'action': 'dismiss'})
    assert dismissed.status_code == 200 and not any(t['style'] == 'playful_print' for t in dismissed.json()['inferred_tags'])
    assert client.post(url, headers=headers, json={'expected_version': previous['version'], 'action': 'accept'}).status_code == 409
    for i, p in enumerate(source):
        response, _ = feedback(client, root, headers, kid, p)
        assert any(t['style'] == 'playful_print' for t in response.json()['profile']['inferred_tags']) == (i == 2)
    accepted = client.post(url, headers=headers, json={'expected_version': response.json()['profile']['version'], 'action': 'accept'})
    assert accepted.status_code == 200 and 'playful_print' in accepted.json()['styles']
    removed = client.put(path(root, kid), headers=headers, json={'expected_version': accepted.json()['version'], 'styles': []})
    assert removed.status_code == 200 and 'playful_print' not in removed.json()['effective_weights']


def test_designated_basis_attributes_actor_not_designated_and_viewer_cannot_write(client, wardrobe, auth):
    root, users, headers, kid, _ = wardrobe
    members = client.get(root + '/members', headers=headers).json(); designated = next(m for m in members if m['role'] == 'editor')
    for p in plans(client, wardrobe, preference_mode='designated_member', designated_member_id=designated['id']):
        assert feedback(client, root, auth(users[2]), kid, p)[0].status_code == 403
        response, _ = feedback(client, root, headers, kid, p); assert response.status_code == 200
    data = response.json(); actor = next(m for m in members if m['role'] == 'admin')
    assert data['target'] == 'me' and data['event']['owner_key'] == 'member:' + actor['id']
    assert data['event']['source_subject']['membership_id'] == designated['id'] and data['event']['attribution'] == 'actor_personal'
    assert client.get(path(root, kid, 'me'), headers=auth(users[1])).json()['inferred_tags'] == []
    assert client.get(path(root, kid), headers=headers).json()['inferred_tags'] == []


def test_learning_signature_changes_without_saved_snapshot_mutation_and_revision_checked(client, wardrobe):
    root, _, headers, kid, _ = wardrobe
    source = plans(client, wardrobe); frozen = deepcopy(source[0]); before, _ = recommendation(client, root, headers, kid)
    assert feedback(client, root, headers, kid, source[0], plan_version=999)[0].status_code == 404
    for p in source: assert feedback(client, root, headers, kid, p)[0].status_code == 200
    after, _ = recommendation(client, root, headers, kid); assert before['input_version'] != after['input_version']
    context = client.get(root + '/outfits/context', headers=headers, params={'child_id': kid['id'], 'target_date': frozen['target_date']}).json()
    assert any(w['code'] == 'CURRENT_PREFERENCES_CHANGED' for w in context['plans'][0]['current_warnings'])
    assert {k: v for k, v in context['plans'][0].items() if k != 'current_warnings'} == frozen


def test_selection_event_weak_atomic_and_save_replay_deduplicated(client, wardrobe, engine):
    root, _, headers, kid, gs = wardrobe
    result, payload = save(client, root, headers, plan_body(kid, gs[:2])); assert result.status_code == 200
    assert client.post(root + '/outfits/plans', headers=headers, json=payload).status_code == 200
    from app.v2.preferences.models import FeedbackEvent
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(FeedbackEvent)) == 1 and db.scalar(select(FeedbackEvent)).signal == 'selection'
    def reject(c, cursor, statement, p, ctx, many):
        if statement.startswith('INSERT INTO wardrobe_operations'): raise RuntimeError('D atomic rollback')
    event.listen(engine, 'before_cursor_execute', reject)
    try:
        with pytest.raises(RuntimeError, match='D atomic rollback'): save(client, root, headers, plan_body(kid, gs[:2]))
    finally: event.remove(engine, 'before_cursor_execute', reject)
    with client.app.state.session_factory() as db: assert db.scalar(select(func.count()).select_from(FeedbackEvent)) == 1


def test_cancelled_weak_selections_stop_learning_but_explicit_feedback_remains(client, wardrobe):
    root, _, headers, kid, garments = wardrobe
    for index in (0, 1):
        g = garments[index]
        updated = client.put(root + '/garments/' + g['id'], headers=headers,
            json={'expected_version': g['version'], 'pattern': 'solid'})
        assert updated.status_code == 200
        garments[index] = updated.json()
    source = plans(client, wardrobe)
    current = client.get(path(root, kid), headers=headers).json()
    assert any(t['style'] == 'clean_daily' for t in current['inferred_tags'])
    for p in source:
        assert feedback(client, root, headers, kid, p)[0].status_code == 200
    assert client.post(root + '/outfits/plans/' + source[0]['id'] + '/cancel', headers=headers,
        json={'expected_version': 1, 'operation_id': uuid4().hex}).status_code == 200
    current = client.get(path(root, kid), headers=headers).json()
    assert not any(t['style'] == 'clean_daily' for t in current['inferred_tags'])
    assert any(t['style'] == 'playful_print' for t in current['inferred_tags'])


def test_negative_inference_is_bounded_explicit_style_overrides_it(client, wardrobe):
    root, _, headers, kid, _ = wardrobe
    for p in plans(client, wardrobe):
        response, _ = feedback(client, root, headers, kid, p, signal='dislike')
        assert response.status_code == 200
    profile = response.json()['profile']
    tag = next(t for t in profile['inferred_tags'] if t['style'] == 'playful_print')
    assert tag['direction'] == 'dislike' and -.5 <= tag['weight'] < 0
    explicit = client.put(path(root, kid), headers=headers, json={'styles': ['playful_print'], 'expected_version': profile['version']})
    assert explicit.status_code == 200 and explicit.json()['effective_weights']['playful_print'] == 1


def test_negative_inferred_tag_cannot_be_accepted_as_explicit_like(client, wardrobe):
    root, _, headers, kid, _ = wardrobe
    for p in plans(client, wardrobe):
        response, _ = feedback(client, root, headers, kid, p, signal='dislike')
        assert response.status_code == 200
    profile = response.json()['profile']
    accepted = client.post(path(root, kid) + '/tags/playful_print', headers=headers,
        json={'expected_version': profile['version'], 'action': 'accept'})
    assert accepted.status_code == 422
    current = client.get(path(root, kid), headers=headers).json()
    assert current['styles'] == [] and current['version'] == profile['version']


@pytest.mark.parametrize('edit_mode', ['family', 'current_member'])
def test_edit_replaces_weak_selection_features_but_preserves_explicit_opinions(client, wardrobe, edit_mode):
    root, _, headers, kid, garments = wardrobe
    for index in (0, 1):
        g = garments[index]
        response = client.put(root + '/garments/' + g['id'], headers=headers,
            json={'expected_version': g['version'], 'pattern': 'solid'})
        assert response.status_code == 200
        garments[index] = response.json()
    source = plans(client, wardrobe)
    assert any(t['style'] == 'clean_daily' for t in client.get(path(root, kid), headers=headers).json()['inferred_tags'])
    for plan in source:
        assert feedback(client, root, headers, kid, plan, styles=['soft_natural'])[0].status_code == 200
    g = garments[0]
    response = client.put(root + '/garments/' + g['id'], headers=headers,
        json={'expected_version': g['version'], 'pattern': 'print'})
    assert response.status_code == 200
    garments[0] = response.json()
    for plan in source:
        updated, _ = save(client, root, headers, plan_body(kid, garments[:2], target_plan_id=plan['id'], expected_version=1, preference_mode=edit_mode))
        assert updated.status_code == 200
    profile = client.get(path(root, kid), headers=headers).json()
    assert not any(t['style'] == 'clean_daily' for t in profile['inferred_tags'])
    selected_profile = profile if edit_mode == 'family' else client.get(path(root, kid, 'me'), headers=headers).json()
    playful = next(t for t in selected_profile['inferred_tags'] if t['style'] == 'playful_print')
    assert playful['evidence_count'] == 3 and all(e['plan_version'] == 2 for e in playful['evidence'])
    stated = next(t for t in profile['inferred_tags'] if t['style'] == 'soft_natural')
    assert stated['evidence_count'] == 3 and all(e['signal'] == 'like' and e['plan_version'] == 1 for e in stated['evidence'])
