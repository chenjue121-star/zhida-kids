from typing import Literal
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.v2.core.database import get_db
from app.v2.core.errors import fail
from app.v2.identity.tokens import current_user
from app.v2.families.access import family_access
from app.v2.families.models import Membership
from app.v2.children.service import get_child
from app.v2.preferences.schemas import ProfilePut, SettingsPatch, Feedback, TagAction, Style
from app.v2.preferences import service

router = APIRouter()
EDITORS = ('admin', 'editor')


@router.get('/families/{fid}/children/{cid}/preference-settings')
def settings(fid: int, cid: int, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, lock=True)
    child = get_child(db, fid, cid, lock=True)
    return service.settings_json(service.get_settings(db, child.id, lock=True))


@router.patch('/families/{fid}/children/{cid}/preference-settings')
@router.put('/families/{fid}/children/{cid}/preference-settings')
def update(fid: int, cid: int, body: SettingsPatch, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS, lock=True)
    child = get_child(db, fid, cid, lock=True)
    return service.update_settings(db, child, body)


@router.get('/families/{fid}/children/{cid}/profiles/members/{mid}')
def member_profile(fid: int, cid: int, mid: int,
                   user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, lock=True)
    child = get_child(db, fid, cid, lock=True)
    member = db.scalar(select(Membership).where(
        Membership.id == mid, Membership.family_id == fid, Membership.status == 'active',
    ).with_for_update().execution_options(populate_existing=True))
    if member is None:
        fail(404, 'NOT_FOUND', '成员不存在或已退出家庭')
    return service.profile_json(service.get_profile(db, child.id, 'member:' + str(member.id), lock=True))


@router.get('/families/{fid}/children/{cid}/profiles/{target}')
def profile(fid: int, cid: int, target: Literal['family', 'me'],
            user=Depends(current_user), db: Session = Depends(get_db)):
    _, member = family_access(db, fid, user, lock=True)
    child = get_child(db, fid, cid, lock=True)
    owner = 'family' if target == 'family' else 'member:' + str(member.id)
    return service.profile_json(service.get_profile(db, child.id, owner, lock=True))


@router.put('/families/{fid}/children/{cid}/profiles/{target}')
def put(fid: int, cid: int, target: Literal['family', 'me'], body: ProfilePut,
        user=Depends(current_user), db: Session = Depends(get_db)):
    _, member = family_access(db, fid, user, EDITORS, lock=True)
    child = get_child(db, fid, cid, lock=True)
    return service.put_profile(db, child, member, target, body)


@router.post('/families/{fid}/children/{cid}/feedback')
def feedback(fid: int, cid: int, body: Feedback, request: Request,
             user=Depends(current_user), db: Session = Depends(get_db)):
    family, member = family_access(db, fid, user, EDITORS, lock=True)
    child = get_child(db, fid, cid, lock=True)
    return service.submit_feedback(db, family, child, member, user, body, request.app.state.clock())


@router.post('/families/{fid}/children/{cid}/profiles/{target}/tags/{style}')
def tag(fid: int, cid: int, target: Literal['family', 'me'], style: Style, body: TagAction,
        user=Depends(current_user), db: Session = Depends(get_db)):
    _, member = family_access(db, fid, user, EDITORS, lock=True)
    child = get_child(db, fid, cid, lock=True)
    return service.tag_action(db, child, member, target, style, body)
