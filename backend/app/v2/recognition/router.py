from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session
from app.v2.core.database import get_db
from app.v2.core.errors import fail
from app.v2.identity.tokens import current_user
from app.v2.families.access import family_access
from app.v2.recognition import service
from app.v2.recognition.schemas import BatchCreate, ItemCreate, ItemPatch, CandidateCreate, CandidatePatch, Confirmation
from app.v2.recognition.operations import lookup, unknown

router = APIRouter()
EDITORS = ('admin', 'editor')


@router.get('/families/{fid}/intake/batches')
def batches(fid: int, user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user, EDITORS)
    return service.list_batches(db, family, user)


@router.post('/families/{fid}/intake/batches', status_code=201)
def create_batch(fid: int, body: BatchCreate, user=Depends(current_user), db: Session = Depends(get_db),
                 idempotency_key: str = Header(...)):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    return service.create_batch(db, family, user, body, idempotency_key)


@router.get('/families/{fid}/intake/batches/{bid}')
def batch_detail(fid: int, bid: int, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS)
    return service.batch_json(db, service.get_batch(db, fid, bid, user))


@router.post('/families/{fid}/intake/batches/{bid}/items', status_code=201)
def create_item(fid: int, bid: int, body: ItemCreate, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS, lock=True)
    return service.create_item(db, service.get_batch(db, fid, bid, user, lock=True), body)


@router.put('/families/{fid}/intake/batches/{bid}/items/{iid}')
def discard(fid: int, bid: int, iid: int, body: ItemPatch, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS, lock=True)
    batch = service.get_batch(db, fid, bid, user, lock=True)
    return service.discard_item(db, batch, service.get_item(db, bid, iid, lock=True), body)


@router.post('/families/{fid}/intake/batches/{bid}/items/{iid}/recognition', status_code=202)
def retry(fid: int, bid: int, iid: int, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS, lock=True)
    batch = service.get_batch(db, fid, bid, user, lock=True)
    return service.enqueue(db, batch, service.get_item(db, bid, iid, lock=True), retry=True,
        max_attempts=request.app.state.settings.recognition_max_attempts, now=request.app.state.clock())


@router.post('/families/{fid}/intake/batches/{bid}/candidates', status_code=201)
def create_candidate(fid: int, bid: int, body: CandidateCreate, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS, lock=True)
    return service.create_candidate(db, service.get_batch(db, fid, bid, user, lock=True), body)


@router.put('/families/{fid}/intake/batches/{bid}/candidates/{cid}')
def update_candidate(fid: int, bid: int, cid: int, body: CandidatePatch, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS, lock=True)
    batch = service.get_batch(db, fid, bid, user, lock=True)
    return service.update_candidate(db, batch, service.get_candidate(db, bid, cid, lock=True), body)


@router.post('/families/{fid}/intake/batches/{bid}/confirm')
def confirm(fid: int, bid: int, body: Confirmation, user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    return service.confirm(db, family, user, service.get_batch(db, fid, bid, user, lock=True), body)


@router.get('/families/{fid}/intake/batches/{bid}/operations/{operation_id}')
def operation(fid: int, bid: int, operation_id: str, user=Depends(current_user), db: Session = Depends(get_db)):
    family_access(db, fid, user, EDITORS)
    service.get_batch(db, fid, bid, user)
    result = lookup(db, fid, user.id, 'batch:' + str(bid), operation_id)
    return result.response if result else unknown(operation_id)


@router.post('/families/{fid}/intake/batches/{bid}/operations/{operation_id}/resolve')
def resolve(fid: int, bid: int, operation_id: str, body: Confirmation, user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    if operation_id != body.operation_id:
        fail(422, 'VALIDATION_ERROR', '操作标识不一致')
    return service.resolve_confirmation(db, family, user, service.get_batch(db, fid, bid, user, lock=True), body)
