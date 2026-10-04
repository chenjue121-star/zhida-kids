from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.v2.children.models import Child
from app.v2.children.schemas import ChildCreate
from app.v2.children.service import create_child
from app.v2.core.database import get_db
from app.v2.core.errors import fail
from app.v2.families.models import Family, Membership
from app.v2.families.schemas import Input
from app.v2.families.service import family_json, receipt
from app.v2.identity.models import User
from app.v2.identity.tokens import current_user
from app.v2.preferences.schemas import Style

router = APIRouter()


class FirstChild(Input):
    age_months: int = Field(ge=0, le=83)
    nickname: str = Field(default='宝贝', min_length=1, max_length=80)
    styles: list[Style] = Field(default_factory=list, max_length=4)


@router.post('/onboarding/child', status_code=201)
def first_child(body: FirstChild, request: Request, user=Depends(current_user),
                db: Session = Depends(get_db), idempotency_key: Optional[str] = Header(None)):
    db.execute(select(User.id).where(User.id == user.id).with_for_update()).scalar_one()

    def create():
        family = db.scalar(select(Family).where(Family.personal_owner_id == user.id).with_for_update())
        if family is None:
            family = Family(name='我的家庭', city=None, created_by=user.id, personal_owner_id=user.id)
            db.add(family)
            db.flush()
            db.add(Membership(family_id=family.id, user_id=user.id, role='admin'))
            db.flush()
        member = db.scalar(select(Membership).where(Membership.family_id == family.id,
                                                    Membership.user_id == user.id, Membership.status == 'active'))
        if member is None:
            fail(409, 'FAMILY_ACCESS_REVOKED', '个人空间已不可访问，请联系家庭管理员')
        if db.scalar(select(Child.id).where(Child.family_id == family.id, Child.archived_at.is_(None)).limit(1)):
            fail(409, 'CHILD_EXISTS', '已创建第一个孩子，请到孩子列表添加其他宝贝')
        child_body = ChildCreate(nickname=body.nickname, age_months=body.age_months,
                                 preferences={'styles': body.styles})
        child = create_child(db, family, user, child_body, None, request.app.state.clock())
        return {'family': family_json(family), 'child': child}

    return receipt(db, user, 'first_child', idempotency_key, body.model_dump(mode='json'), create)
