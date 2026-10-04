from typing import Optional
from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session
from app.v2.core.database import get_db
from app.v2.core.errors import fail
from app.v2.identity.tokens import current_user
from app.v2.families.access import family_access
from app.v2.families.schemas import FamilyCreate, FamilyPatch, InvitationCreate, InvitationToken, MemberPatch
from app.v2.families import service

router = APIRouter()


@router.post('/families', status_code=201)
def create(body: FamilyCreate, user=Depends(current_user), db: Session = Depends(get_db),
           idempotency_key: Optional[str] = Header(None)):
    return service.create_family(db, user, body, idempotency_key)


@router.get('/families')
def list_all(user=Depends(current_user), db: Session = Depends(get_db)):
    return service.list_families(db, user)


@router.get('/families/{fid}')
def detail(fid: int, user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user)
    return service.family_json(family)


@router.patch('/families/{fid}')
@router.put('/families/{fid}')
def update(fid: int, body: FamilyPatch, user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user, ('admin',), lock=True)
    return service.update_family(db, family, body)


@router.get('/families/{fid}/members')
def members(fid: int, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user)
    return service.members(db, fid)


@router.post('/families/{fid}/invitations', status_code=201)
def invite(fid: int, body: InvitationCreate, request: Request,
           user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user, ('admin',), lock=True)
    return service.create_invitation(db, family, user, body.role, request.app.state.clock())


@router.delete('/families/{fid}/invitations/{iid}', status_code=204)
def revoke(fid: int, iid: int, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user, ('admin',), lock=True)
    service.revoke_invitation(db, family, iid, request.app.state.clock())
    return Response(status_code=204)


@router.post('/invitations/preview')
def preview(body: InvitationToken, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    return service.preview_invitation(db, body.token, user, request.app.state.clock())


@router.post('/invitations/accept')
def accept(body: InvitationToken, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    return service.accept_invitation(db, body.token, user, request.app.state.clock())


@router.patch('/families/{fid}/members/{mid}')
@router.put('/families/{fid}/members/{mid}')
def role(fid: int, mid: int, body: MemberPatch, user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user, ('admin',), lock=True)
    return service.change_role(db, family, mid, body)


@router.delete('/families/{fid}/members/{mid}', status_code=204)
def remove(fid: int, mid: int, user=Depends(current_user), db: Session = Depends(get_db)):
    family, actor = family_access(db, fid, user, ('admin',), lock=True)
    if actor.id == mid:
        fail(409, 'USE_LEAVE', '请使用退出家庭操作')
    service.remove_member(db, family, mid)
    return Response(status_code=204)


@router.post('/families/{fid}/leave', status_code=204)
def leave(fid: int, user=Depends(current_user), db: Session = Depends(get_db)):
    family, member = family_access(db, fid, user, lock=True)
    service.remove_member(db, family, member.id)
    return Response(status_code=204)
