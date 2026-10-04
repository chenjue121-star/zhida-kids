from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session
from app.v2.core.database import get_db
from app.v2.core.errors import fail
from app.v2.identity.tokens import current_user
from app.v2.families.access import family_access
from app.v2.wardrobe import service
from app.v2.wardrobe.schemas import GarmentPatch, OwnersPatch, Transfer, Archive, Restore, Bulk, Category, State, Fit
from app.v2.recognition.operations import lookup, unknown

router = APIRouter()
EDITORS = ('admin', 'editor')


@router.get('/families/{fid}/garments')
def garments(fid: int, user=Depends(current_user), db: Session = Depends(get_db),
             child_id: int | None = Query(None, gt=0), category: Category | None = None,
             state: State | None = None, fit: Fit | None = None, shared: bool | None = None,
             archived: bool = False, history_child_id: int | None = Query(None, gt=0),
             cursor: int | None = Query(None, ge=0), limit: int = Query(30, ge=1, le=100)):
    family_access(db, fid, user)
    return service.list_garments(db, fid, child_id=child_id, category=category, state=state, fit=fit,
        shared=shared, archived=archived, history_child_id=history_child_id, cursor=cursor, limit=limit)


# Register static bulk path before the garment-id path.
@router.post('/families/{fid}/garments/bulk')
def bulk(fid: int, body: Bulk, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    return service.bulk(db, family, user, body, request.app.state.clock())


@router.get('/families/{fid}/wardrobe-operations/{operation_id}')
def operation(fid: int, operation_id: str, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS)
    result = lookup(db, fid, user.id, 'wardrobe', operation_id)
    return result.response if result else unknown(operation_id)


@router.post('/families/{fid}/wardrobe-operations/{operation_id}/resolve')
def resolve(fid: int, operation_id: str, body: Bulk, user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    if operation_id != body.operation_id:
        fail(422, 'VALIDATION_ERROR', '操作标识不一致')
    return service.resolve_bulk(db, family, user, body)


@router.get('/families/{fid}/garments/{gid}')
def detail(fid: int, gid: int, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user)
    return service.garment_json(db, service.get_garment(db, fid, gid))


@router.put('/families/{fid}/garments/{gid}')
def update(fid: int, gid: int, body: GarmentPatch, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS, lock=True)
    return service.update(db, service.get_garment(db, fid, gid, lock=True), body)


@router.put('/families/{fid}/garments/{gid}/owners')
def owners(fid: int, gid: int, body: OwnersPatch, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS, lock=True)
    return service.update_owners(db, service.get_garment(db, fid, gid, lock=True), body)


@router.post('/families/{fid}/garments/{gid}/transfer')
def transfer(fid: int, gid: int, body: Transfer, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS, lock=True)
    return service.transfer(db, service.get_garment(db, fid, gid, lock=True), body)


@router.post('/families/{fid}/garments/{gid}/archive')
def archive(fid: int, gid: int, body: Archive, request: Request, user=Depends(current_user),
            db: Session = Depends(get_db), idempotency_key: str = Header(...)):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    return service.single_operation(db, family, user, service.get_garment(db, fid, gid, lock=True),
        'archive', body, key=idempotency_key, now=request.app.state.clock())


@router.post('/families/{fid}/garments/{gid}/restore')
def restore(fid: int, gid: int, body: Restore, user=Depends(current_user), db: Session = Depends(get_db),
            idempotency_key: str = Header(...)):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    return service.single_operation(db, family, user, service.get_garment(db, fid, gid, lock=True),
                                    'restore', body, key=idempotency_key)


@router.post('/families/{fid}/garments/{gid}/archive/resolve')
def resolve_archive(fid: int, gid: int, body: Archive, user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    return service.single_operation(db, family, user, service.get_garment(db, fid, gid, lock=True),
                                    'archive', body, resolve=True)


@router.post('/families/{fid}/garments/{gid}/restore/resolve')
def resolve_restore(fid: int, gid: int, body: Restore, user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    return service.single_operation(db, family, user, service.get_garment(db, fid, gid, lock=True),
                                    'restore', body, resolve=True)
