"""C uses actual isolated MySQL connections; SQLite does not prove these locks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event, Barrier
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import func, select

from test_member_races import mysql_sessions, setup_family, race
from app.v2.children import service as children
from app.v2.children.schemas import ChildCreate
from app.v2.core.config import V2Settings
from app.v2.core.errors import DomainError
from app.v2.families.access import family_access
from app.v2.identity.models import User
from app.v2.outfits import service
from app.v2.outfits.models import OutfitPlan, PlanRevision, Reservation, RecommendationRequest
from app.v2.outfits.schemas import Draft, Save, Recommend
from app.v2.wardrobe.models import Clothing, ChildClothing


def setup(sessions, provider=None, forecast_provider=None):
    fid, users = setup_family(sessions, ('admin', 'admin'))
    settings = V2Settings(_env_file=None, database_url='sqlite://',
        jwt_secret='mysql-C-test-secret-at-least-thirty-two-bytes', env='test')
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings,
        clock=lambda: datetime(2026, 10, 3, 8), outfit_provider=provider, forecast_provider=forecast_provider)))
    with sessions.begin() as db:
        user = db.get(User, users[0])
        family, _ = family_access(db, fid, user, lock=True)
        kid = children.create_child(db, family, user, ChildCreate(nickname='C Race', age_months=24), None)
        ids = []
        for category in ('top', 'bottom'):
            garment = Clothing(family_id=fid, created_by=user.id, name=category, category=category,
                colors=['blue'], pattern='solid', thickness='medium', state='ready')
            db.add(garment)
            db.flush()
            db.add(ChildClothing(clothing_id=garment.id, child_id=int(kid['id']), fit='fit'))
            ids.append(garment.id)
        db.flush()
    body = Draft(child_id=kid['id'], target_date='2026-10-03', draft_id=uuid4().hex,
        main_items=[{'garment_id': gid, 'expected_version': 1} for gid in ids], weather_acknowledged=True)
    with sessions() as db:
        review = service.review(db, request, fid, db.get(User, users[0]), body)
        payload = Save(**body.model_dump(), input_version=review['input_version'], operation_id=uuid4().hex)
        db.commit()
    return fid, users, request, body, payload


def save_action(fid, uid, request, payload, resolve=False):
    return lambda db: service.save(db, request, fid, db.get(User, uid), payload, resolve=resolve)


def test_mysql_identical_save_single_plan_revision_and_reservation_set(mysql_sessions):
    fid, users, request, _, payload = setup(mysql_sessions)
    results = race(mysql_sessions, [save_action(fid, users[0], request, payload)] * 2)
    assert results[0] == results[1] and results[0][0] == 200
    with mysql_sessions() as db:
        assert db.scalar(select(func.count()).select_from(OutfitPlan).where(OutfitPlan.family_id == fid)) == 1
        assert db.scalar(select(func.count()).select_from(Reservation).where(Reservation.family_id == fid)) == 2


def test_mysql_two_members_same_version_exactly_one_update_wins(mysql_sessions):
    fid, users, request, body, initial = setup(mysql_sessions)
    with mysql_sessions() as db:
        first = service.save(db, request, fid, db.get(User, users[0]), initial)['plan']
        db.commit()
    edit = Draft(**{**body.model_dump(), 'target_plan_id': first['id'], 'expected_version': 1})
    with mysql_sessions() as db:
        version = service.review(db, request, fid, db.get(User, users[0]), edit)['input_version']
        db.commit()
    payloads = [Save(**edit.model_dump(), input_version=version, operation_id=uuid4().hex) for _ in users]
    results = race(mysql_sessions, [save_action(fid, uid, request, payload) for uid, payload in zip(users, payloads)])
    assert sorted(status for status, _ in results) == [200, 409]
    assert next(result for status, result in results if status == 409) == 'VERSION_CONFLICT'
    with mysql_sessions() as db:
        plan = db.scalar(select(OutfitPlan).where(OutfitPlan.family_id == fid))
        assert plan.version == 2
        assert db.scalar(select(func.count()).select_from(PlanRevision).where(PlanRevision.plan_id == plan.id)) == 2


def test_mysql_resolve_while_weather_io_fences_late_original_save(mysql_sessions):
    entered, released = Event(), Event()
    fid, users, request, _, payload = setup(mysql_sessions)
    def forecast(value):
        entered.set()
        assert released.wait(10)
        return {'status': 'unknown', 'target_date': value['target_date'], 'city': value['city']}
    request.app.state.forecast_provider = forecast
    with ThreadPoolExecutor(max_workers=2) as pool:
        def original():
            with mysql_sessions() as db:
                result = service.save(db, request, fid, db.get(User, users[0]), payload)
                db.commit()
                return result
        first = pool.submit(original)
        assert entered.wait(10)
        with mysql_sessions() as db:
            result = service.save(db, request, fid, db.get(User, users[0]), payload, resolve=True)
            db.commit()
        released.set()
        assert first.result(timeout=15) == result
    assert result['error']['code'] == 'NOT_EXECUTED'
    with mysql_sessions() as db:
        assert db.scalar(select(func.count()).select_from(OutfitPlan).where(OutfitPlan.family_id == fid)) == 0


def test_mysql_same_recommend_request_claims_once_and_model_has_no_checkout(mysql_sessions):
    entered, released = Event(), Event()
    class Provider:
        calls = 0
        def recommend(self, payload):
            assert mysql_sessions.kw['bind'].pool.checkedout() == 0
            self.calls += 1
            entered.set()
            assert released.wait(10)
            return {'garment_ids': [i['garment_id'] for i in payload['combinations'][0]]}
    provider = Provider()
    fid, users, request, body, _ = setup(mysql_sessions, provider=provider)
    recommend = Recommend(**body.model_dump(), request_id=uuid4().hex)
    def original():
        with mysql_sessions() as db:
            result = service.recommend(db, request, fid, db.get(User, users[0]), recommend)
            db.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(original)
        assert entered.wait(10)
        with mysql_sessions() as db:
            try:
                service.recommend(db, request, fid, db.get(User, users[0]), recommend)
                raise AssertionError('Pending request duplicated provider work')
            except DomainError as error:
                assert error.code == 'RECOMMENDATION_PENDING'
                db.rollback()
        released.set()
        assert first.result(timeout=15)['source'] == 'model'
    assert provider.calls == 1
    with mysql_sessions() as db:
        assert db.scalar(select(func.count()).select_from(RecommendationRequest).where(RecommendationRequest.family_id == fid)) == 1


def test_mysql_distinct_operations_same_review_input_cannot_duplicate_initial_choice(mysql_sessions):
    fid, users, request, _, payload = setup(mysql_sessions)
    second = payload.model_copy(update={'operation_id': uuid4().hex})
    results = race(mysql_sessions, [save_action(fid, users[0], request, payload),
                                    save_action(fid, users[0], request, second)])
    assert sorted(status for status, _ in results) == [200, 409]
    assert next(result for status, result in results if status == 409) == 'INPUT_CHANGED'
    with mysql_sessions() as db:
        assert db.scalar(select(func.count()).select_from(OutfitPlan).where(OutfitPlan.family_id == fid)) == 1


def test_mysql_operation_query_rechecks_removed_membership_after_rr_snapshot(mysql_sessions):
    from app.v2.families.models import Membership
    from app.v2.families.service import remove_member
    fid, users, request, _, payload = setup(mysql_sessions)
    with mysql_sessions() as db:
        service.save(db, request, fid, db.get(User, users[0]), payload)
        db.commit()
    with mysql_sessions() as reader:
        original_user = reader.get(User, users[0])
        with mysql_sessions.begin() as writer:
            family, _ = family_access(writer, fid, writer.get(User, users[1]), lock=True)
            membership = writer.scalar(select(Membership).where(Membership.family_id == fid,
                Membership.user_id == users[0]))
            remove_member(writer, family, membership.id)
        try:
            service.operation(reader, fid, original_user, payload.operation_id)
            raise AssertionError('Removed reader saw stale authorized history')
        except DomainError as error:
            assert error.status == 404
