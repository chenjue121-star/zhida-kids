"""Real MySQL transactions, with one independent session/connection per racer."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4
import os

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.v2.core.errors import DomainError
from app.v2.families import service as families
from app.v2.families.access import family_access
from app.v2.families.models import Membership, Invitation, Family, MutationReceipt
from app.v2.families.schemas import FamilyCreate
from app.v2.identity.models import User
from app.v2.identity.service import get_or_create_user
from app.v2.children import service as children
from app.v2.children.models import Child, ChildMeasurement
from app.v2.children.schemas import ChildCreate, MeasurementCreate
from app.v2.preferences import service as preferences
from app.v2.preferences.models import PreferenceProfile, PreferenceSettings
from app.v2.preferences.schemas import SettingsPatch, ProfilePut


@pytest.fixture(scope='module')
def mysql_sessions():
    root = Path(__file__).resolve().parents[2]
    url = os.environ.get('V2_TEST_DATABASE_URL') or dotenv_values(root / '.env.v2').get('V2_TEST_DATABASE_URL')
    assert url, 'V2_TEST_DATABASE_URL is required for MySQL race verification'
    parsed = make_url(url)
    assert parsed.get_backend_name() == 'mysql' and parsed.database == 'zhida_kids_v2_test', 'Refusing non-isolated database'
    config = Config(str(root / 'alembic-v2.ini'))
    config.attributes['database_url'] = url
    command.upgrade(config, 'head')
    engine = create_engine(url, pool_pre_ping=True, pool_size=6)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def race(sessions, actions):
    barrier = Barrier(len(actions))
    def run(action):
        with sessions() as db:
            connection_id = db.scalar(text('SELECT CONNECTION_ID()'))
            barrier.wait(timeout=10)
            try:
                result = action(db)
                db.commit()
                return connection_id, 200, result
            except DomainError as exc:
                db.rollback()
                return connection_id, exc.status, exc.code
    with ThreadPoolExecutor(max_workers=len(actions)) as executor:
        futures = [executor.submit(run, action) for action in actions]
        results = [future.result(timeout=25) for future in futures]
    assert len({result[0] for result in results}) == len(actions)
    return [(status, result) for _, status, result in results]


def setup_family(sessions, roles=('admin', 'admin')):
    with sessions.begin() as db:
        users = [get_or_create_user(db, {'openid': uuid4().hex}) for role in roles]
        family = families.create_family(db, users[0], FamilyCreate(name='Race', city='Shanghai'), None)
        for user, role in zip(users[1:], roles[1:]):
            db.add(Membership(family_id=int(family['id']), user_id=user.id, role=role))
        db.flush()
        return int(family['id']), [user.id for user in users]


def test_mysql_first_login_unique(mysql_sessions):
    identity = uuid4().hex
    def login(db):
        return get_or_create_user(db, {'openid': identity}).id
    results = race(mysql_sessions, [login, login])
    assert results[0] == results[1]
    with mysql_sessions() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.openid == identity)) == 1


def test_mysql_last_admin_concurrent_leave(mysql_sessions):
    fid, users = setup_family(mysql_sessions)
    def leave(uid):
        def action(db):
            family, member = family_access(db, fid, db.get(User, uid), lock=True)
            families.remove_member(db, family, member.id)
        return action
    results = race(mysql_sessions, [leave(uid) for uid in users])
    assert sorted(status for status, _ in results) == [200, 409]
    with mysql_sessions() as db:
        assert db.scalar(select(func.count()).select_from(Membership).where(
            Membership.family_id == fid, Membership.role == 'admin', Membership.status == 'active')) == 1


def test_mysql_invitation_single_consumer(mysql_sessions):
    fid, users = setup_family(mysql_sessions, ('admin',))
    with mysql_sessions.begin() as db:
        invitation = families.create_invitation(db, db.get(Family, fid), db.get(User, users[0]), 'editor')
        guests = [get_or_create_user(db, {'openid': uuid4().hex}).id for _ in range(2)]
    def accept(uid):
        return lambda db: families.accept_invitation(db, invitation['token'], db.get(User, uid))
    results = race(mysql_sessions, [accept(uid) for uid in guests])
    assert sorted(status for status, _ in results) == [200, 410]
    with mysql_sessions() as db:
        assert db.scalar(select(func.count()).select_from(Membership).where(Membership.family_id == fid)) == 2


def test_mysql_designation_and_departure(mysql_sessions):
    fid, users = setup_family(mysql_sessions, ('admin', 'editor'))
    with mysql_sessions.begin() as db:
        family, member = family_access(db, fid, db.get(User, users[0]), lock=True)
        child = children.create_child(db, family, db.get(User, users[0]), ChildCreate(nickname='Child', birthday='2024-01-01'), None)
        mid = db.scalar(select(Membership.id).where(Membership.family_id == fid, Membership.user_id == users[1]))
    def designate(db):
        family_access(db, fid, db.get(User, users[0]), lock=True)
        target = children.get_child(db, fid, int(child['id']), lock=True)
        return preferences.update_settings(db, target, SettingsPatch(expected_version=1, mode='designated_member', designated_member_id=mid))
    def leave(db):
        family, member = family_access(db, fid, db.get(User, users[1]), lock=True)
        families.remove_member(db, family, member.id)
    results = race(mysql_sessions, [designate, leave])
    assert results[0][0] in (200, 422) and results[1][0] == 200
    with mysql_sessions() as db:
        settings = db.get(PreferenceSettings, int(child['id']))
        assert settings.mode == 'family' and settings.designated_member_id is None


def test_mysql_profile_first_create_conflicts(mysql_sessions):
    fid, users = setup_family(mysql_sessions, ('admin',))
    with mysql_sessions.begin() as db:
        family, member = family_access(db, fid, db.get(User, users[0]), lock=True)
        child = children.create_child(db, family, db.get(User, users[0]), ChildCreate(nickname='Child', birthday='2024-01-01'), None)
    def save(db):
        _, member = family_access(db, fid, db.get(User, users[0]), lock=True)
        target = children.get_child(db, fid, int(child['id']), lock=True)
        return preferences.put_profile(db, target, member, 'me', ProfilePut(styles=['sporty'], expected_version=0))
    results = race(mysql_sessions, [save, save])
    assert sorted(status for status, _ in results) == [200, 409]


def test_mysql_receipt_same_key_atomic(mysql_sessions):
    fid, users = setup_family(mysql_sessions, ('admin',))
    key = uuid4().hex
    def create(db):
        user = db.get(User, users[0])
        family, _ = family_access(db, fid, user, lock=True)
        return children.create_child(db, family, user, ChildCreate(nickname='Child', birthday='2024-01-01'), key)
    results = race(mysql_sessions, [create, create])
    assert results[0] == results[1]
    with mysql_sessions() as db:
        assert db.scalar(select(func.count()).select_from(Child).where(Child.family_id == fid)) == 1
        assert db.scalar(select(func.count()).select_from(MutationReceipt).where(MutationReceipt.idempotency_key == key)) == 1
