from sqlalchemy import select
from app.v2.core.errors import fail
from app.v2.families.models import Family, Membership


def family_access(db, family_id, user, roles=None, lock=False):
    query = select(Family).where(Family.id == family_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    family = db.execute(query).scalar_one_or_none()
    membership_query = select(Membership).where(
        Membership.family_id == family_id, Membership.user_id == user.id, Membership.status == 'active')
    if lock:
        membership_query = membership_query.with_for_update().execution_options(populate_existing=True)
    membership = db.execute(membership_query).scalar_one_or_none()
    if family is None or membership is None:
        fail(404, 'NOT_FOUND', '家庭不存在或你已不是该家庭成员')
    if roles is not None and membership.role not in roles:
        fail(403, 'FORBIDDEN', '当前成员无此操作权限')
    return family, membership


def check_version(actual, expected):
    if actual != expected:
        fail(409, 'VERSION_CONFLICT', '内容已被其他成员修改，请重新加载后保存')
