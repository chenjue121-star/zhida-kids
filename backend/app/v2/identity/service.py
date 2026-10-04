from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.v2.identity.models import User


def user_json(user):
    return {'id': str(user.id), 'nickname': user.nickname}


def get_or_create_user(db, identity):
    openid = identity['openid']
    user = db.execute(select(User).where(User.openid == openid)).scalar_one_or_none()
    if user is not None:
        return user
    try:
        with db.begin_nested():
            user = User(openid=openid, nickname=identity.get('nickname', '')[:80])
            db.add(user)
            db.flush()
    except IntegrityError:
        # A locking read sees the winner even under MySQL REPEATABLE READ.
        user = db.execute(select(User).where(User.openid == openid).with_for_update()).scalar_one_or_none()
        if user is None:
            raise
    return user
