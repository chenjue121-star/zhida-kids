from datetime import date, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from app.v2.core.clock import local_today
from app.v2.core.database import get_db
from app.v2.core.errors import fail
from app.v2.families.access import family_access
from app.v2.identity.tokens import current_user
from app.v2.preferences.service import get_settings
from app.v2.children.service import get_child
from app.v2.outfits import service
from app.v2.outfits.schemas import Constraints, Recommend, Candidates, BackupRequest, Draft, Sharing, Save, Scene, Mode, Cancel, Reuse

router = APIRouter(prefix='/families/{fid}/outfits')


@router.get('/context')
def context(fid: int, request: Request, child_id: int = Query(..., gt=0),
    date_mode: Literal['today', 'tomorrow'] | None = None, target_date: date | None = None,
    scene: Scene = 'daily', preference_mode: Mode | None = None,
    designated_member_id: int | None = Query(None, gt=0), city: str | None = Query(None, min_length=1, max_length=120),
    lat: float | None = Query(None, ge=-90, le=90), lon: float | None = Query(None, ge=-180, le=180),
    user=Depends(current_user), db: Session = Depends(get_db)):
    family, _ = family_access(db, fid, user)
    child = get_child(db, fid, child_id)
    settings = get_settings(db, child.id)
    today = local_today(family.timezone, request.app.state.clock())
    if target_date is not None and date_mode is not None:
        fail(422, 'VALIDATION_ERROR', '请使用实际日期或日期模式其中之一')
    target = target_date or today + timedelta(days=date_mode == 'tomorrow')
    mode = preference_mode or settings.mode
    member_id = designated_member_id if preference_mode else settings.designated_member_id
    from pydantic import ValidationError
    try:
        body = Constraints(child_id=child_id, target_date=target, scene=scene, preference_mode=mode,
            designated_member_id=member_id, city=city, lat=lat, lon=lon, draft_id='context')
    except ValidationError:
        fail(422, 'VALIDATION_ERROR', '请核对地点和偏好依据')
    return service.context(db, request, fid, user, body)


@router.post('/recommend')
def recommend(fid: int, body: Recommend, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    return service.recommend(db, request, fid, user, body)


@router.post('/candidates')
def candidates(fid: int, body: Candidates, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    return service.candidates(db, request, fid, user, body)


@router.post('/backup')
def backup(fid: int, body: BackupRequest, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    return service.backup(db, request, fid, user, body)


@router.post('/review')
def review(fid: int, body: Draft, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    return service.review(db, request, fid, user, body)


@router.post('/sharing')
def sharing(fid: int, body: Sharing, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    return service.sharing(db, request, fid, user, body)


@router.post('/plans')
def save(fid: int, body: Save, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    return service.save(db, request, fid, user, body)


@router.get('/operations/{operation_id}')
def operation(fid: int, operation_id: str, user=Depends(current_user), db: Session = Depends(get_db)):
    return service.operation(db, fid, user, operation_id)


@router.post('/operations/{operation_id}/resolve')
def resolve(fid: int, operation_id: str, body: Save, request: Request,
            user=Depends(current_user), db: Session = Depends(get_db)):
    if operation_id != body.operation_id:
        fail(422, 'VALIDATION_ERROR', '原操作身份不一致')
    return service.save(db, request, fid, user, body, resolve=True)


@router.get('/calendar')
def calendar(fid: int, request: Request, start_date: date, end_date: date,
             child_id: int | None = Query(None, gt=0), include_cancelled: bool = False,
             user=Depends(current_user), db: Session = Depends(get_db)):
    return service.calendar(db, request, fid, user, start_date, end_date, child_id, include_cancelled)


@router.get('/plans/{pid}')
def plan_detail(fid: int, pid: int, user=Depends(current_user), db: Session = Depends(get_db)):
    return service.plan_detail(db, fid, user, pid)


@router.post('/plans/{pid}/cancel')
def cancel(fid: int, pid: int, body: Cancel, request: Request,
           user=Depends(current_user), db: Session = Depends(get_db)):
    return service.cancel(db, request, fid, user, pid, body)


@router.post('/plans/{pid}/cancel/resolve')
def resolve_cancel(fid: int, pid: int, body: Cancel, request: Request,
                   user=Depends(current_user), db: Session = Depends(get_db)):
    return service.cancel(db, request, fid, user, pid, body, resolve=True)


@router.post('/plans/{pid}/reuse')
def reuse(fid: int, pid: int, body: Reuse, request: Request,
          user=Depends(current_user), db: Session = Depends(get_db)):
    return service.reuse(db, request, fid, user, pid, body)
