from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.v2.core.database import get_db
from app.v2.core.errors import fail
from app.v2.identity.tokens import current_user
from app.v2.families.access import family_access
from app.v2.media.models import MediaAsset
from app.v2.media.service import normalize_image
from app.v2.recognition import service
from app.v2.recognition.models import IntakeBatch, IntakeItem
from app.v2.wardrobe.models import Clothing

router = APIRouter()
EDITORS = ('admin', 'editor')


@router.put('/families/{fid}/intake/batches/{bid}/items/{iid}/upload')
async def upload(fid: int, bid: int, iid: int, request: Request, user=Depends(current_user),
                 db: Session = Depends(get_db)):
    # Authenticate before accepting bytes, then release this read transaction.
    family_access(db, fid, user, EDITORS)
    service.get_batch(db, fid, bid, user)
    db.rollback()
    max_bytes = request.app.state.settings.upload_max_bytes
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > max_bytes:
            fail(413, 'IMAGE_TOO_LARGE', '照片过大，请选择较小图片')
    content, sha256, width, height = normalize_image(bytes(raw), request.headers.get('content-type', ''), max_bytes)
    # Private storage is outside the database lock/transaction; recheck permissions after it.
    object_key = request.app.state.storage.put(fid, sha256, content)
    family_access(db, fid, user, EDITORS, lock=True)
    batch = service.get_batch(db, fid, bid, user, lock=True)
    item = service.get_item(db, bid, iid, lock=True)
    service.require_item(item)
    if item.asset_id:
        existing = db.get(MediaAsset, item.asset_id)
        if existing.sha256 != sha256:
            fail(409, 'IMAGE_ALREADY_UPLOADED', '照片已上传，不能替换已有候选的原图；请新增照片项')
        return service.item_json(db, item, batch)
    asset = db.scalar(select(MediaAsset).where(MediaAsset.family_id == fid, MediaAsset.sha256 == sha256).with_for_update())
    if asset is None:
        asset = MediaAsset(family_id=fid, sha256=sha256, object_key=object_key, width=width, height=height)
        db.add(asset)
        db.flush()
    item.asset_id = asset.id
    return service.enqueue(db, batch, item, max_attempts=request.app.state.settings.recognition_max_attempts,
                           now=request.app.state.clock())


@router.get('/families/{fid}/assets/{asset_id}/content')
def content(fid: int, asset_id: int, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    _, member = family_access(db, fid, user)
    asset = db.scalar(select(MediaAsset).where(MediaAsset.id == asset_id, MediaAsset.family_id == fid))
    confirmed = db.scalar(select(Clothing.id).where(Clothing.family_id == fid, Clothing.asset_id == asset_id).limit(1))
    own_draft = None
    if member.role in EDITORS:
        own_draft = db.scalar(select(IntakeItem.id).join(IntakeBatch).where(IntakeBatch.family_id == fid,
            IntakeBatch.created_by == user.id, IntakeItem.asset_id == asset_id).limit(1))
    if asset is None or (confirmed is None and own_draft is None):
        fail(404, 'NOT_FOUND', '图片不存在或无查看权限')
    object_key, content_type = asset.object_key, asset.content_type
    db.rollback()
    try:
        data = request.app.state.storage.get(object_key)
    except (OSError, ValueError):
        fail(404, 'NOT_FOUND', '图片暂不可用')
    # Recheck role/reference after potentially slow storage I/O; never serve public static files.
    _, member = family_access(db, fid, user)
    confirmed = db.scalar(select(Clothing.id).where(Clothing.family_id == fid, Clothing.asset_id == asset_id).limit(1))
    if confirmed is None:
        if member.role not in EDITORS or db.scalar(select(IntakeItem.id).join(IntakeBatch).where(
                IntakeBatch.family_id == fid, IntakeBatch.created_by == user.id, IntakeItem.asset_id == asset_id).limit(1)) is None:
            fail(404, 'NOT_FOUND', '图片不存在或无查看权限')
    return Response(data, media_type=content_type, headers={'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff'})
