from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.v2.core.database import get_db
from app.v2.identity.schemas import LoginRequest
from app.v2.identity.tokens import current_user, issue_token
from app.v2.identity.service import get_or_create_user, user_json
from app.v2.integrations.wechat import exchange_code

router = APIRouter()


@router.post('/auth/wechat-login')
async def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    identity = await exchange_code(body.code, request.app.state.settings, request.app.state.wechat_exchange)
    user = get_or_create_user(db, identity)
    token, expires_at = issue_token(user, request.app.state.settings)
    return {'token': token, 'expires_at': expires_at, 'user': user_json(user)}


@router.get('/me')
def me(user=Depends(current_user), db: Session = Depends(get_db)):
    from app.v2.families.service import list_families, list_memberships
    return {'user': user_json(user), 'families': list_families(db, user), 'memberships': list_memberships(db, user)}
