from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import jwt
from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session
from app.v2.core.database import get_db
from app.v2.core.errors import fail
from app.v2.identity.models import User


def issue_token(user, settings):
    now = int(datetime.now(timezone.utc).timestamp())
    expiration = now + settings.jwt_ttl_seconds
    token = jwt.encode({'sub': str(user.id), 'iat': now, 'exp': expiration,
                        'iss': settings.jwt_issuer, 'aud': settings.jwt_audience},
                       settings.jwt_secret.get_secret_value(), algorithm='HS256')
    return token, datetime.fromtimestamp(expiration, timezone.utc).isoformat()


def current_user(request: Request, authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    settings = request.app.state.settings
    if not authorization or not authorization.startswith('Bearer '):
        fail(401, 'UNAUTHORIZED', '登录已失效，请重新登录')
    try:
        payload = jwt.decode(authorization[7:], settings.jwt_secret.get_secret_value(),
                             algorithms=['HS256'], issuer=settings.jwt_issuer,
                             audience=settings.jwt_audience,
                             options={'require': ['iss', 'aud', 'sub', 'iat', 'exp']})
        subject = payload['sub']
        if not isinstance(subject, str) or not subject.isdecimal() or not 0 < int(subject) <= 9223372036854775807:
            raise ValueError('Invalid subject')
        user = db.get(User, int(subject))
    except (jwt.InvalidTokenError, ValueError, TypeError):
        fail(401, 'UNAUTHORIZED', '登录已失效，请重新登录')
    if user is None:
        fail(401, 'UNAUTHORIZED', '登录已失效，请重新登录')
    return user
