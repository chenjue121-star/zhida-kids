"""D concurrency uses isolated MySQL connections, never SQLite as lock evidence."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

from sqlalchemy import select, func
from test_member_races import mysql_sessions, race
from test_c_mysql_races import setup, save_action
from app.v2.children.service import get_child
from app.v2.core.errors import DomainError
from app.v2.families.access import family_access
from app.v2.identity.models import User
from app.v2.outfits import service as outfits
from app.v2.outfits.models import OutfitPlan, PlanRevision, Reservation
from app.v2.outfits.schemas import Cancel, Reuse, Draft, Save
from app.v2.preferences import service as preferences
from app.v2.preferences.models import FeedbackEvent, PreferenceProfile
from app.v2.preferences.schemas import Feedback, TagAction


def selected(sessions):
    fid, users, request, body, payload = setup(sessions)
    with sessions() as db:
        plan = outfits.save(db, request, fid, db.get(User, users[0]), payload)['plan']
        db.commit()
    return fid, users, request, body, plan


def feedback_action(fid, uid, request, cid, body):
    def action(db):
        user = db.get(User, uid)
        family, member = family_access(db, fid, user, ('admin', 'editor'), lock=True)
        child = get_child(db, fid, cid, lock=True)
        return preferences.submit_feedback(db, family, child, member, user, body, request.app.state.clock())
    return action


def test_mysql_feedback_same_event_records_once(mysql_sessions):
    fid, users, request, body, plan = selected(mysql_sessions)
    event = Feedback(event_id=uuid4().hex, plan_id=plan['id'], plan_version=1,
        signal='like', reason='aesthetic', styles=['playful_print'])
    action = feedback_action(fid, users[0], request, body.child_id, event)
    results = race(mysql_sessions, [action, action])
    assert results[0] == results[1] and results[0][0] == 200
    with mysql_sessions() as db:
        assert db.scalar(select(func.count()).select_from(FeedbackEvent).where(
            FeedbackEvent.family_id == fid, FeedbackEvent.event_id == event.event_id)) == 1


def test_mysql_cancel_and_edit_only_one_revision_wins(mysql_sessions):
    fid, users, request, body, plan = selected(mysql_sessions)
    edit = Draft(**{**body.model_dump(), 'target_plan_id': plan['id'], 'expected_version': 1})
    with mysql_sessions() as db:
        version = outfits.review(db, request, fid, db.get(User, users[0]), edit)['input_version']; db.commit()
    payload = Save(**edit.model_dump(), input_version=version, operation_id=uuid4().hex)
    cancel = Cancel(expected_version=1, operation_id=uuid4().hex)
    actions = [save_action(fid, users[0], request, payload),
        lambda db: outfits.cancel(db, request, fid, db.get(User, users[1]), int(plan['id']), cancel)]
    results = race(mysql_sessions, actions)
    assert sorted(status for status, _ in results) == [200, 409]
    assert next(r for status, r in results if status == 409) in ('VERSION_CONFLICT', 'PLAN_CANCELLED')
    with mysql_sessions() as db:
        current = db.get(OutfitPlan, int(plan['id']))
        assert current.version == 2
        assert db.scalar(select(func.count()).select_from(PlanRevision).where(PlanRevision.plan_id == current.id)) == 2
        count = db.scalar(select(func.count()).select_from(Reservation).where(Reservation.plan_id == current.id))
        assert count == (0 if current.status == 'cancelled' else 2)


def test_mysql_cancel_resolve_and_original_share_one_durable_fence(mysql_sessions):
    fid, users, request, _, plan = selected(mysql_sessions)
    body = Cancel(expected_version=1, operation_id=uuid4().hex)
    actions = [lambda db: outfits.cancel(db, request, fid, db.get(User, users[0]), int(plan['id']), body),
        lambda db: outfits.cancel(db, request, fid, db.get(User, users[0]), int(plan['id']), body, resolve=True)]
    results = race(mysql_sessions, actions)
    assert results[0] == results[1] and results[0][0] == 200
    response = results[0][1]
    with mysql_sessions() as db:
        plan = db.get(OutfitPlan, int(plan['id']))
        assert plan.status == ('selected' if response.get('error') else 'cancelled')


def test_mysql_dismiss_racing_threshold_never_reuses_suppressed_evidence(mysql_sessions):
    fid, users, request, draft, first = selected(mysql_sessions)
    plans = [first]
    for _ in range(2):
        with mysql_sessions() as db:
            version = outfits.review(db, request, fid, db.get(User, users[0]), draft)['input_version']
            plan = outfits.save(db, request, fid, db.get(User, users[0]), Save(**draft.model_dump(),
                input_version=version, operation_id=uuid4().hex))['plan']; db.commit(); plans.append(plan)
    for plan in plans[:2]:
        with mysql_sessions() as db:
            feedback_action(fid, users[0], request, draft.child_id, Feedback(event_id=uuid4().hex,
                plan_id=plan['id'], plan_version=1, signal='like', reason='aesthetic', styles=['playful_print']))(db); db.commit()
    with mysql_sessions() as db:
        expected = preferences.get_profile(db, draft.child_id, 'family').version
    event = Feedback(event_id=uuid4().hex, plan_id=plans[2]['id'], plan_version=1,
        signal='like', reason='aesthetic', styles=['playful_print'])
    def dismiss(db):
        user = db.get(User, users[0]); _, member = family_access(db, fid, user, lock=True)
        child = get_child(db, fid, draft.child_id, lock=True)
        return preferences.tag_action(db, child, member, 'family', 'playful_print',
            TagAction(expected_version=expected, action='dismiss'))
    results = race(mysql_sessions, [dismiss, feedback_action(fid, users[0], request, draft.child_id, event)])
    assert results[1][0] == 200 and results[0][0] in (200, 409)
    with mysql_sessions() as db:
        profile = preferences.get_profile(db, draft.child_id, 'family')
        if results[0][0] == 200:
            assert 'playful_print' in profile.suppression_cutoffs
            assert not any(t['style'] == 'playful_print' for t in profile.inferred_tags)
        else:
            assert results[0][1] == 'VERSION_CONFLICT'


def test_mysql_reuse_weather_io_rechecks_source_before_returning_draft(mysql_sessions):
    fid, users, request, draft, plan = selected(mysql_sessions)
    entered, release = Event(), Event()
    def forecast(payload):
        assert mysql_sessions.kw['bind'].pool.checkedout() == 0
        entered.set(); assert release.wait(10)
        return {'status': 'unknown', 'target_date': payload['target_date']}
    request.app.state.forecast_provider = forecast
    body = Reuse(expected_source_version=1, child_id=draft.child_id,
        target_date='2026-10-08', draft_id=uuid4().hex)
    def original():
        with mysql_sessions() as db:
            try:
                outfits.reuse(db, request, fid, db.get(User, users[0]), int(plan['id']), body)
                raise AssertionError('Stale source accepted')
            except DomainError as exc:
                db.rollback(); return exc.status, exc.code
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(original); assert entered.wait(10)
        with mysql_sessions() as db:
            outfits.cancel(db, request, fid, db.get(User, users[1]), int(plan['id']),
                Cancel(expected_version=1, operation_id=uuid4().hex)); db.commit()
        release.set(); assert pending.result(timeout=15) == (409, 'VERSION_CONFLICT')


def test_mysql_learning_projection_reads_events_committed_after_old_snapshot(mysql_sessions):
    fid, users, request, draft, first = selected(mysql_sessions)
    plans = [first]
    for _ in range(3):
        with mysql_sessions() as db:
            version = outfits.review(db, request, fid, db.get(User, users[0]), draft)['input_version']
            plan = outfits.save(db, request, fid, db.get(User, users[0]), Save(**draft.model_dump(),
                input_version=version, operation_id=uuid4().hex))['plan']; db.commit(); plans.append(plan)
    def feedback(plan):
        return Feedback(event_id=uuid4().hex, plan_id=plan['id'], plan_version=1,
            signal='like', reason='aesthetic', styles=['playful_print'])
    for plan in plans[:2]:
        with mysql_sessions() as db:
            feedback_action(fid, users[0], request, draft.child_id, feedback(plan))(db); db.commit()
    with mysql_sessions() as stale:
        stale.scalar(select(func.count()).select_from(FeedbackEvent).where(FeedbackEvent.family_id == fid))
        with mysql_sessions() as fresh:
            feedback_action(fid, users[0], request, draft.child_id, feedback(plans[2]))(fresh); fresh.commit()
        response = feedback_action(fid, users[0], request, draft.child_id, feedback(plans[3]))(stale)
        assert next(t for t in response['profile']['inferred_tags'] if t['style'] == 'playful_print')['evidence_count'] == 4
        stale.commit()


def test_mysql_suppression_cutoff_includes_events_committed_after_old_snapshot(mysql_sessions):
    fid, users, request, draft, plan = selected(mysql_sessions)
    with mysql_sessions() as stale:
        stale.scalars(select(FeedbackEvent.id).where(FeedbackEvent.family_id == fid)).all()
        with mysql_sessions() as fresh:
            event = Feedback(event_id=uuid4().hex, plan_id=plan['id'], plan_version=1,
                signal='like', reason='aesthetic', styles=['playful_print'])
            feedback_action(fid, users[0], request, draft.child_id, event)(fresh)
            latest = fresh.scalar(select(func.max(FeedbackEvent.id)).where(FeedbackEvent.family_id == fid)); fresh.commit()
        user = stale.get(User, users[0]); _, member = family_access(stale, fid, user, lock=True)
        child = get_child(stale, fid, draft.child_id, lock=True)
        profile = preferences.get_profile(stale, draft.child_id, 'family', lock=True)
        preferences.tag_action(stale, child, member, 'family', 'playful_print', TagAction(expected_version=profile.version, action='dismiss'))
        assert profile.suppression_cutoffs['playful_print'] >= latest
        stale.commit()


def revoke_member(sessions, fid, actor_id, revoked_id):
    from app.v2.families import service as families
    from app.v2.families.models import Membership
    with sessions() as db:
        family, _ = family_access(db, fid, db.get(User, actor_id), lock=True)
        membership = db.scalar(select(Membership).where(Membership.family_id == fid,
            Membership.user_id == revoked_id, Membership.status == 'active').with_for_update())
        families.remove_member(db, family, membership.id)
        db.commit()


def test_mysql_calendar_rechecks_revocation_after_old_identity_snapshot(mysql_sessions):
    from datetime import date
    fid, users, request, _, plan = selected(mysql_sessions)
    with mysql_sessions() as stale:
        original_actor = stale.get(User, users[0])
        # Establish the same consistent-read snapshot current_user creates.
        family_access(stale, fid, original_actor)
        revoke_member(mysql_sessions, fid, users[1], users[0])
        try:
            outfits.calendar(stale, request, fid, original_actor,
                date.fromisoformat(plan['target_date']), date.fromisoformat(plan['target_date']))
            raise AssertionError('Revoked member read calendar from a stale snapshot')
        except DomainError as exc:
            assert exc.status == 404
        stale.rollback()


def test_mysql_plan_detail_rechecks_revocation_after_old_identity_snapshot(mysql_sessions):
    fid, users, _, _, plan = selected(mysql_sessions)
    with mysql_sessions() as stale:
        original_actor = stale.get(User, users[0])
        family_access(stale, fid, original_actor)
        revoke_member(mysql_sessions, fid, users[1], users[0])
        try:
            outfits.plan_detail(stale, fid, original_actor, int(plan['id']))
            raise AssertionError('Revoked member read plan detail from a stale snapshot')
        except DomainError as exc:
            assert exc.status == 404
        stale.rollback()


def test_mysql_profile_rechecks_revocation_after_old_identity_snapshot(mysql_sessions):
    from app.v2.preferences.router import profile
    fid, users, _, draft, _ = selected(mysql_sessions)
    with mysql_sessions() as stale:
        original_actor = stale.get(User, users[0])
        family_access(stale, fid, original_actor)
        revoke_member(mysql_sessions, fid, users[1], users[0])
        try:
            profile(fid, draft.child_id, 'family', user=original_actor, db=stale)
            raise AssertionError('Revoked member read learned preferences from a stale snapshot')
        except DomainError as exc:
            assert exc.status == 404
        stale.rollback()
