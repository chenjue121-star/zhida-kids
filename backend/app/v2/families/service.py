from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
import json
import secrets

from sqlalchemy import select
from app.v2.core.clock import utcnow
from app.v2.core.errors import fail
from app.v2.families.access import check_version, family_access
from app.v2.families.models import Family, Invitation, Membership, MutationReceipt
from app.v2.identity.models import User


def family_json(family):
    return {key: getattr(family, key) for key in ('name', 'city', 'timezone', 'version')} | {'id': str(family.id)}


def membership_json(member, nickname=''):
    return {'id': str(member.id), 'user_id': str(member.user_id), 'role': member.role,
            'nickname': nickname, 'status': member.status}


def list_families(db, user):
    return [family_json(f) for f in db.scalars(select(Family).join(Membership).where(
        Membership.user_id == user.id, Membership.status == 'active').order_by(Family.id))]


def list_memberships(db, user):
    return [{**membership_json(m, user.nickname), 'family_id': str(m.family_id)}
            for m in db.scalars(select(Membership).where(Membership.user_id == user.id,
                                                        Membership.status == 'active').order_by(Membership.id))]


def members(db, family_id):
    return [membership_json(m, nickname) for m, nickname in db.execute(
        select(Membership, User.nickname).join(User).where(
            Membership.family_id == family_id, Membership.status == 'active').order_by(Membership.id))]


def receipt(db, user, operation, key, payload, execute, replay_guard=None):
    # The caller holds the family lock (or actor lock for family creation).
    # Receipt and resource writes share this request's transaction.
    if key is None:
        return execute()
    if not key.strip() or len(key) > 128:
        fail(422, 'VALIDATION_ERROR', '请求标识须为 1 至 128 个字符')
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    previous = db.scalar(select(MutationReceipt).where(
        MutationReceipt.actor_id == user.id, MutationReceipt.operation == operation,
        MutationReceipt.idempotency_key == key).with_for_update())
    if previous is not None:
        if replay_guard:
            replay_guard(previous.response_body)
        if previous.request_hash != digest:
            fail(409, 'IDEMPOTENCY_CONFLICT', '请求标识已用于不同内容，请重新提交')
        return previous.response_body
    result = execute()
    db.add(MutationReceipt(actor_id=user.id, operation=operation, idempotency_key=key,
                           request_hash=digest, response_body=result, status_code=201))
    db.flush()
    return result


def create_family(db, user, body, key):
    db.execute(select(User.id).where(User.id == user.id).with_for_update()).scalar_one()

    def create():
        family = Family(**body.model_dump(), created_by=user.id)
        db.add(family)
        db.flush()
        db.add(Membership(family_id=family.id, user_id=user.id, role='admin'))
        db.flush()
        return family_json(family)

    return receipt(db, user, 'create_family', key, body.model_dump(mode='json'), create,
                   lambda result: family_access(db, int(result['id']), user, lock=True))


def update_family(db, family, body):
    check_version(family.version, body.expected_version)
    for key, value in body.model_dump(exclude_unset=True, exclude={'expected_version'}).items():
        setattr(family, key, value)
    family.version += 1
    db.flush()
    return family_json(family)


def create_invitation(db, family, user, role, now=None):
    token = secrets.token_urlsafe(32)
    invitation = Invitation(family_id=family.id, created_by=user.id, role=role,
                            token_hash=sha256(token.encode()).hexdigest(),
                            expires_at=(now or utcnow()) + timedelta(days=7))
    db.add(invitation)
    db.flush()
    return {'invitation_id': str(invitation.id), 'token': token,
            'expires_at': invitation.expires_at.isoformat() + 'Z'}


def find_invitation(db, token, lock=False):
    query = select(Invitation).where(Invitation.token_hash == sha256(token.encode()).hexdigest())
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    invitation = db.scalar(query)
    if invitation is None:
        fail(404, 'NOT_FOUND', '邀请不存在，请确认邀请链接')
    return invitation


def valid_invitation(invitation, now):
    if invitation.revoked_at is not None or invitation.expires_at <= now:
        fail(410, 'INVITATION_UNAVAILABLE', '邀请已过期或已撤销，请联系管理员重新邀请')


def preview_invitation(db, token, user, now=None):
    invitation = find_invitation(db, token)
    valid_invitation(invitation, now or utcnow())
    if invitation.accepted_by is not None and invitation.accepted_by != user.id:
        fail(410, 'INVITATION_UNAVAILABLE', '邀请已被使用，请联系管理员重新邀请')
    family = db.get(Family, invitation.family_id)
    inviter = db.get(User, invitation.created_by)
    return {'family_name': family.name, 'inviter_name': inviter.nickname,
            'role': invitation.role, 'expires_at': invitation.expires_at.isoformat() + 'Z'}


def accept_invitation(db, token, user, now=None):
    now = now or utcnow()
    found = find_invitation(db, token)
    family = db.scalar(select(Family).where(Family.id == found.family_id).with_for_update()
                       .execution_options(populate_existing=True))
    invitation = find_invitation(db, token, lock=True)
    membership = db.scalar(select(Membership).where(
        Membership.family_id == family.id, Membership.user_id == user.id).with_for_update()
        .execution_options(populate_existing=True))
    if invitation.accepted_by is not None:
        if invitation.accepted_by == user.id and membership is not None and membership.status == 'active':
            return {'family_id': str(family.id), 'membership': membership_json(membership, user.nickname)}
        fail(410, 'INVITATION_UNAVAILABLE', '邀请已被使用，请联系管理员重新邀请')
    valid_invitation(invitation, now)
    if membership is not None and membership.status == 'active':
        return {'family_id': str(family.id), 'membership': membership_json(membership, user.nickname)}
    if membership is None:
        membership = Membership(family_id=family.id, user_id=user.id, role=invitation.role)
        db.add(membership)
    else:
        membership.status = 'active'
        membership.role = invitation.role
        membership.joined_at = now
    invitation.accepted_by = user.id
    invitation.accepted_at = now
    family.version += 1
    db.flush()
    return {'family_id': str(family.id), 'membership': membership_json(membership, user.nickname)}


def revoke_invitation(db, family, invitation_id, now=None):
    invitation = db.scalar(select(Invitation).where(Invitation.id == invitation_id,
                                                   Invitation.family_id == family.id).with_for_update())
    if invitation is None:
        fail(404, 'NOT_FOUND', '邀请不存在，请确认邀请链接')
    if invitation.accepted_by is not None:
        fail(409, 'INVITATION_USED', '已接受的邀请不能撤销')
    invitation.revoked_at = now or utcnow()
    db.flush()


def get_member(db, family, member_id):
    member = db.scalar(select(Membership).where(Membership.id == member_id,
                                               Membership.family_id == family.id,
                                               Membership.status == 'active').with_for_update()
                       .execution_options(populate_existing=True))
    if member is None:
        fail(404, 'NOT_FOUND', '成员不存在或已退出家庭')
    return member


def protect_last_admin(db, family, member):
    if member.role == 'admin':
        admins = db.scalars(select(Membership.id).where(Membership.family_id == family.id,
                                                       Membership.status == 'active',
                                                       Membership.role == 'admin').with_for_update()).all()
        if len(admins) <= 1:
            fail(409, 'LAST_ADMIN', '家庭须保留至少一名管理员，请先指定其他管理员')


def change_role(db, family, member_id, body):
    check_version(family.version, body.expected_family_version)
    member = get_member(db, family, member_id)
    if body.role != 'admin':
        protect_last_admin(db, family, member)
    member.role = body.role
    family.version += 1
    db.flush()
    return membership_json(member, db.get(User, member.user_id).nickname)


def remove_member(db, family, member_id):
    member = get_member(db, family, member_id)
    protect_last_admin(db, family, member)
    from app.v2.preferences.models import PreferenceSettings
    settings = db.scalars(select(PreferenceSettings).where(
        PreferenceSettings.designated_member_id == member.id).with_for_update()).all()
    for setting in settings:
        setting.mode = 'family'
        setting.designated_member_id = None
        setting.version += 1
    member.status = 'removed'
    family.version += 1
    db.flush()
