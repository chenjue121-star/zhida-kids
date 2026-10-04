from typing import Optional
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session
from app.v2.core.database import get_db
from app.v2.identity.tokens import current_user
from app.v2.families.access import family_access
from app.v2.children.schemas import ChildCreate, ChildPatch, MeasurementCreate
from app.v2.children import service

router = APIRouter()
EDITORS = ('admin', 'editor')


@router.get('/families/{fid}/children')
def children(fid: int, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user)
    return service.list_children(db, fid)


@router.post('/families/{fid}/children', status_code=201)
def create(fid: int, body: ChildCreate, request: Request, user=Depends(current_user),
           db: Session = Depends(get_db), idempotency_key: Optional[str] = Header(None)):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    return service.create_child(db, family, user, body, idempotency_key, request.app.state.clock())


@router.get('/families/{fid}/children/{cid}')
def detail(fid: int, cid: int, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user)
    return service.child_json(db, service.get_child(db, fid, cid))


@router.patch('/families/{fid}/children/{cid}')
@router.put('/families/{fid}/children/{cid}')
def update(fid: int, cid: int, body: ChildPatch, request: Request,
           user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    child = service.get_child(db, fid, cid, lock=True)
    return service.update_child(db, family, child, body, request.app.state.clock())


@router.delete('/families/{fid}/children/{cid}', status_code=204)
def archive(fid: int, cid: int, request: Request, expected_version: int = Query(..., ge=1),
            user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS, lock=True)
    child = service.get_child(db, fid, cid, lock=True)
    service.archive_child(db, child, expected_version, request.app.state.clock())
    return Response(status_code=204)


@router.post('/families/{fid}/children/{cid}/measurements', status_code=201)
def measure(fid: int, cid: int, body: MeasurementCreate, request: Request,
            user=Depends(current_user), db: Session = Depends(get_db), idempotency_key: Optional[str] = Header(None)):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    child = service.get_child(db, fid, cid, lock=True)
    return service.add_measurement(db, family, child, user, body, idempotency_key, request.app.state.clock())
