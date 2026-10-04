"""B races run against the same protected, real MySQL test database as A."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event
from uuid import uuid4
from sqlalchemy import select, func, text
from test_member_races import mysql_sessions, setup_family, race
from app.v2.core.errors import DomainError
from app.v2.identity.models import User
from app.v2.families.access import family_access
from app.v2.children import service as children
from app.v2.children.schemas import ChildCreate
from app.v2.recognition import service as intake
from app.v2.recognition.schemas import BatchCreate, ItemCreate, CandidateCreate, Confirmation
from app.v2.recognition.models import IntakeBatch, RecognitionAttempt, Candidate, Operation
from app.v2.wardrobe.models import Clothing
from app.v2.wardrobe import service as wardrobe
from app.v2.wardrobe.schemas import OwnersPatch, Transfer


def setup_candidate(sessions):
    fid, users = setup_family(sessions, ('admin',))
    with sessions.begin() as db:
        user = db.get(User, users[0])
        family, _ = family_access(db, fid, user, ('admin', 'editor'), lock=True)
        child = children.create_child(db, family, user, ChildCreate(nickname='B', age_months=24), None)
        b = intake.create_batch(db, family, user, BatchCreate(default_child_id=child['id']), uuid4().hex)
        batch = intake.get_batch(db, fid, int(b['id']), user, lock=True)
        item = intake.create_item(db, batch, ItemCreate(client_id=uuid4().hex, source='manual'))
        candidate = intake.create_candidate(db, batch, CandidateCreate(item_id=item['id'], client_id=uuid4().hex,
            category='top', selected=True))
    return fid, users[0], int(b['id']), int(child['id']), candidate


def action(fid, uid, bid, candidate, op, *, resolve=False, rollback=False):
    def execute(db):
        user = db.get(User, uid)
        family, _ = family_access(db, fid, user, ('admin', 'editor'), lock=True)
        batch = intake.get_batch(db, fid, bid, user, lock=True)
        body = Confirmation(operation_id=op, entries=[{'candidate_id': candidate['id'],
            'expected_version': candidate['version'], 'action': 'new'}])
        result = (intake.resolve_confirmation if resolve else intake.confirm)(db, family, user, batch, body)
        if rollback:
            raise DomainError(409, 'FORCED_ROLLBACK', 'test rollback')
        return result
    return execute


def test_mysql_same_candidate_distinct_operation_creates_one_object(mysql_sessions):
    fid, uid, bid, _, candidate = setup_candidate(mysql_sessions)
    results = race(mysql_sessions, [action(fid, uid, bid, candidate, uuid4().hex),
                                    action(fid, uid, bid, candidate, uuid4().hex)])
    assert all(status == 200 for status, _ in results)
    assert results[0][1]['results'][0]['garment']['id'] == results[1][1]['results'][0]['garment']['id']
    with mysql_sessions() as db:
        assert db.scalar(select(func.count()).select_from(Clothing).where(Clothing.family_id == fid)) == 1
        assert db.scalar(select(func.count()).select_from(Operation).where(Operation.family_id == fid)) == 2


def ordered(sessions, fid, uid, first_action, second_action):
    first_locked, second_started = Event(), Event()
    def run_first():
        with sessions() as db:
            connection = db.scalar(text('SELECT CONNECTION_ID()'))
            family_access(db, fid, db.get(User, uid), ('admin', 'editor'), lock=True)
            first_locked.set()
            assert second_started.wait(10)
            try:
                result = first_action(db)
                db.commit()
                return connection, 200, result
            except DomainError as error:
                db.rollback()
                return connection, error.status, error.code
    def run_second():
        assert first_locked.wait(10)
        with sessions() as db:
            connection = db.scalar(text('SELECT CONNECTION_ID()'))
            second_started.set()
            result = second_action(db)
            db.commit()
            return connection, 200, result
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_first)
        second = pool.submit(run_second)
        results = [first.result(timeout=25), second.result(timeout=25)]
    assert results[0][0] != results[1][0]
    return [(status, result) for _, status, result in results]


def test_mysql_confirm_wins_resolve_replays_success(mysql_sessions):
    fid, uid, bid, _, candidate = setup_candidate(mysql_sessions)
    op = uuid4().hex
    results = ordered(mysql_sessions, fid, uid, action(fid, uid, bid, candidate, op),
                      action(fid, uid, bid, candidate, op, resolve=True))
    assert results[0] == results[1]
    assert results[0][1]['counts']['new'] == 1


def test_mysql_resolve_wins_late_confirmation_never_executes(mysql_sessions):
    fid, uid, bid, _, candidate = setup_candidate(mysql_sessions)
    op = uuid4().hex
    results = ordered(mysql_sessions, fid, uid, action(fid, uid, bid, candidate, op, resolve=True),
                      action(fid, uid, bid, candidate, op))
    assert results[0] == results[1]
    assert results[0][1]['results'][0]['error']['code'] == 'NOT_EXECUTED'
    with mysql_sessions() as db:
        assert db.scalar(select(func.count()).select_from(Clothing).where(Clothing.family_id == fid)) == 0


def test_mysql_rolled_back_confirmation_resolves_as_not_executed(mysql_sessions):
    fid, uid, bid, _, candidate = setup_candidate(mysql_sessions)
    op = uuid4().hex
    results = ordered(mysql_sessions, fid, uid, action(fid, uid, bid, candidate, op, rollback=True),
                      action(fid, uid, bid, candidate, op, resolve=True))
    assert results[0] == (409, 'FORCED_ROLLBACK')
    assert results[1][1]['results'][0]['error']['code'] == 'NOT_EXECUTED'
    with mysql_sessions() as db:
        assert db.scalar(select(func.count()).select_from(Clothing).where(Clothing.family_id == fid)) == 0
        assert db.get(Candidate, int(candidate['id'])).confirmed_garment_id is None


def test_mysql_transfer_rechecks_shared_relations_after_waiting(mysql_sessions):
    fid, uid, bid, child_id, candidate = setup_candidate(mysql_sessions)
    with mysql_sessions.begin() as db:
        result = action(fid, uid, bid, candidate, uuid4().hex)(db)
        garment = result['results'][0]['garment']
        user = db.get(User, uid)
        family, _ = family_access(db, fid, user, lock=True)
        child2 = children.create_child(db, family, user, ChildCreate(nickname='second', age_months=30), None)
    def share(db):
        family_access(db, fid, db.get(User, uid), lock=True)
        g = wardrobe.get_garment(db, fid, int(garment['id']), lock=True)
        return wardrobe.update_owners(db, g, OwnersPatch(expected_version=g.version,
            owners=[{'child_id': child_id, 'fit': 'fit'}, {'child_id': child2['id'], 'fit': 'large'}]))
    def transfer(db):
        family_access(db, fid, db.get(User, uid), lock=True)
        g = wardrobe.get_garment(db, fid, int(garment['id']), lock=True)
        try:
            return wardrobe.transfer(db, g, Transfer(expected_version=g.version, child_id=child2['id'], fit='fit'))
        except DomainError as error:
            return error.code
    results = ordered(mysql_sessions, fid, uid, share, transfer)
    assert results[1][1] == 'SHARED_TRANSFER_CONFLICT'


def test_mysql_two_workers_claim_once_and_provider_runs_without_db_checkout(mysql_sessions, tmp_path):
    from app.v2.media.models import MediaAsset
    from app.v2.media.storage import FileStorage
    from app.v2.media.service import normalize_image
    from app.v2.jobs.worker import RecognitionWorker
    from test_b_worker_assets import photo, ClothesProvider
    fid, uid, bid, _, candidate = setup_candidate(mysql_sessions)
    now = datetime(2026, 10, 2)
    storage = FileStorage(tmp_path)
    data, sha256, width, height = normalize_image(photo(), 'image/png')
    key = storage.put(fid, sha256, data)
    with mysql_sessions.begin() as db:
        user = db.get(User, uid)
        family_access(db, fid, user, lock=True)
        batch = intake.get_batch(db, fid, bid, user, lock=True)
        item = intake.get_item(db, bid, int(candidate['item_id']), lock=True)
        asset = MediaAsset(family_id=fid, sha256=sha256, object_key=key, width=width, height=height)
        db.add(asset)
        db.flush()
        item.asset_id = asset.id
        intake.enqueue(db, batch, item, now=now)
        attempt_id = db.scalar(select(RecognitionAttempt.id).where(RecognitionAttempt.item_id == item.id))
    class CheckedProvider(ClothesProvider):
        def recognize(self, image, content_type='image/jpeg'):
            assert mysql_sessions.kw['bind'].pool.checkedout() == 0, 'provider call holds a SQL connection'
            return super().recognize(image, content_type)
    workers = [RecognitionWorker(mysql_sessions, storage, CheckedProvider(), clock=lambda: now) for _ in range(2)]
    results = race(mysql_sessions, [lambda db: workers[0].claim(), lambda db: workers[1].claim()])
    claims = [result for _, result in results if result is not None]
    assert len(claims) == 1 and claims[0].attempt_id == attempt_id
    workers[0].process(claims[0])
    assert workers[1].publish(claims[0], ClothesProvider().recognize(b'')) is False
    with mysql_sessions() as db:
        attempt = db.get(RecognitionAttempt, attempt_id)
        assert attempt.status == 'succeeded' and attempt.tries == 1
