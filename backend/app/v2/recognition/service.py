from uuid import uuid4
from sqlalchemy import select, func
from app.v2.core.clock import utcnow
from app.v2.core.errors import DomainError, fail
from app.v2.families.access import check_version
from app.v2.families.service import receipt
from app.v2.children.service import get_child
from app.v2.recognition.models import IntakeBatch, IntakeItem, Candidate, RecognitionAttempt
from app.v2.recognition.operations import digest, run_operation, operation_response, not_executed
from app.v2.wardrobe.models import Clothing
from app.v2.wardrobe import service as wardrobe


def get_batch(db, family_id, batch_id, user, lock=False):
    query = select(IntakeBatch).where(IntakeBatch.family_id == family_id, IntakeBatch.id == batch_id,
                                     IntakeBatch.created_by == user.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    batch = db.scalar(query)
    if batch is None:
        fail(404, 'NOT_FOUND', '录入草稿不存在或不属于你')
    return batch


def get_item(db, batch_id, item_id, lock=False):
    query = select(IntakeItem).where(IntakeItem.batch_id == batch_id, IntakeItem.id == item_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    item = db.scalar(query)
    if item is None:
        fail(404, 'NOT_FOUND', '照片项不属于当前批次')
    return item


def get_candidate(db, batch_id, candidate_id, lock=False):
    query = select(Candidate).where(Candidate.batch_id == batch_id, Candidate.id == candidate_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    candidate = db.scalar(query)
    if candidate is None:
        fail(404, 'NOT_FOUND', '候选不属于当前批次')
    return candidate


def candidate_json(db, candidate, batch=None):
    item = db.get(IntakeItem, candidate.item_id)
    batch = batch or db.get(IntakeBatch, candidate.batch_id)
    duplicates = []
    if item.asset_id:
        duplicates = [wardrobe.garment_json(db, g) for g in db.scalars(select(Clothing).where(
            Clothing.family_id == batch.family_id, Clothing.asset_id == item.asset_id).order_by(Clothing.id))]
    from app.v2.children.models import Child
    owner_list = []
    for owner in candidate.owners:
        child = db.get(Child, int(owner['child_id']))
        owner_list.append({**owner, 'child_id': str(owner['child_id']),
            'nickname': child.nickname if child else '', 'archived': child is None or child.archived_at is not None})
    return {'id': str(candidate.id), 'version': candidate.version, 'item_id': str(candidate.item_id),
            'client_id': candidate.client_id, 'name': candidate.name, 'category': candidate.category,
            'colors': candidate.colors, 'pattern': candidate.pattern, 'thickness': candidate.thickness,
            'state': candidate.state, 'asset_id': str(item.asset_id) if item.asset_id else None,
            'owners': owner_list,
            'archived_at': None, 'history_owners': [], 'last_owners': [], 'selected': candidate.selected,
            'discarded': candidate.discarded, 'ownership_exception': candidate.ownership_exception,
            'confirmed_garment_id': str(candidate.confirmed_garment_id) if candidate.confirmed_garment_id else None,
            'duplicate_garments': duplicates, 'bbox': candidate.bbox, 'dirty_fields': candidate.dirty_fields}


def item_json(db, item, batch=None):
    return {'id': str(item.id), 'client_id': item.client_id, 'source': item.source,
            'version': item.version, 'discarded': item.discarded,
            'asset_id': str(item.asset_id) if item.asset_id else None, 'status': item.status,
            'error': item.error.get('message') if isinstance(item.error, dict) else item.error,
            'candidates': [candidate_json(db, c, batch) for c in db.scalars(select(Candidate).where(
                Candidate.item_id == item.id).order_by(Candidate.id))]}


def batch_json(db, batch):
    items = [item_json(db, item, batch) for item in db.scalars(select(IntakeItem).where(
        IntakeItem.batch_id == batch.id).order_by(IntakeItem.id))]
    pending_count = sum(not c['discarded'] and c['confirmed_garment_id'] is None
        for item in items if not item['discarded'] for c in item['candidates'])
    unresolved_count = sum(not item['discarded'] and (item['status'] in ('queued', 'running') or
        (not item['candidates'] and item['status'] in ('manual', 'failed', 'uncertain'))) for item in items)
    return {'id': str(batch.id), 'version': batch.version, 'default_child_id': str(batch.default_child_id),
            'created_by': str(batch.created_by), 'items': items,
            'candidates': [c for item in items for c in item['candidates']],
            'items_count': len(items), 'candidates_count': sum(len(item['candidates']) for item in items),
            'pending_candidates_count': pending_count, 'unresolved_items_count': unresolved_count,
            'has_pending': bool(pending_count or unresolved_count)}


def create_batch(db, family, user, body, key):
    def execute():
        get_child(db, family.id, body.default_child_id, lock=True)
        batch = IntakeBatch(family_id=family.id, created_by=user.id, default_child_id=body.default_child_id)
        db.add(batch)
        db.flush()
        return batch_json(db, batch)
    return receipt(db, user, 'intake_batch:' + str(family.id), key, body.model_dump(mode='json'), execute)


def list_batches(db, family, user):
    batches = [batch_json(db, batch) for batch in db.scalars(select(IntakeBatch).where(
        IntakeBatch.family_id == family.id, IntakeBatch.created_by == user.id).order_by(IntakeBatch.id.desc()))]
    return [batch for batch in batches if batch['has_pending']]


def create_item(db, batch, body):
    previous = db.scalar(select(IntakeItem).where(IntakeItem.batch_id == batch.id,
                                                 IntakeItem.client_id == body.client_id).with_for_update())
    if previous:
        if previous.source != body.source:
            fail(409, 'IDEMPOTENCY_CONFLICT', '照片标识已用于不同来源')
        return item_json(db, previous, batch)
    item = IntakeItem(batch_id=batch.id, client_id=body.client_id, source=body.source, status='manual')
    db.add(item)
    batch.version += 1
    db.flush()
    return item_json(db, item, batch)


def discard_item(db, batch, item, body):
    if item.discarded:
        return item_json(db, item, batch)
    check_version(item.version, body.expected_version)
    item.discarded = True
    item.version += 1
    batch.version += 1
    for candidate in db.scalars(select(Candidate).where(Candidate.item_id == item.id,
            Candidate.confirmed_garment_id.is_(None)).with_for_update()):
        candidate.discarded = True
        candidate.selected = False
        candidate.version += 1
        candidate.dirty_fields = sorted(set(candidate.dirty_fields) | {'discarded', 'selected'})
    db.flush()
    return item_json(db, item, batch)


def require_item(item):
    if item.discarded:
        fail(409, 'CANDIDATE_DISCARDED', '该照片已明确放弃')


def create_candidate(db, batch, body):
    item = get_item(db, batch.id, body.item_id, lock=True)
    require_item(item)
    request_hash = digest(body.model_dump(mode='json'))
    previous = db.scalar(select(Candidate).where(Candidate.batch_id == batch.id,
                                                Candidate.client_id == body.client_id).with_for_update())
    if previous:
        if previous.request_hash != request_hash:
            fail(409, 'IDEMPOTENCY_CONFLICT', '手填候选标识已用于不同内容')
        return candidate_json(db, previous, batch)
    fields = body.model_dump(exclude={'item_id', 'owners'})
    owners = [o.model_dump() for o in body.owners] if body.owners is not None else [
        {'child_id': batch.default_child_id, 'fit': 'fit'}]
    wardrobe.validate_owners(db, batch.family_id, owners)
    default_owners = [{'child_id': batch.default_child_id, 'fit': 'fit'}]
    ownership_exception = sorted(owners, key=lambda o: o['child_id']) != default_owners
    candidate = Candidate(batch_id=batch.id, item_id=item.id, owners=owners, request_hash=request_hash,
                          ownership_exception=ownership_exception,
                          dirty_fields=sorted(body.model_fields_set - {'client_id', 'item_id'}), **fields)
    db.add(candidate)
    item.version += 1
    batch.version += 1
    db.flush()
    return candidate_json(db, candidate, batch)


def update_candidate(db, batch, candidate, body):
    if candidate.confirmed_garment_id:
        fail(409, 'ALREADY_CONFIRMED', '候选已入库，请进入衣物详情编辑')
    require_item(get_item(db, batch.id, candidate.item_id, lock=True))
    check_version(candidate.version, body.expected_version)
    fields = body.model_dump(exclude_unset=True, exclude={'expected_version'})
    if 'owners' in fields:
        wardrobe.validate_owners(db, batch.family_id, fields['owners'])
        candidate.ownership_exception = True
    for key, value in fields.items():
        setattr(candidate, key, value)
    if candidate.discarded:
        candidate.selected = False
    candidate.dirty_fields = sorted(set(candidate.dirty_fields) | set(fields))
    candidate.version += 1
    batch.version += 1
    db.flush()
    return candidate_json(db, candidate, batch)


def enqueue(db, batch, item, *, retry=False, max_attempts=3, now=None):
    require_item(item)
    if not item.asset_id:
        fail(422, 'IMAGE_REQUIRED', '请先上传照片，或直接手填')
    if item.status == 'uncertain':
        fail(409, 'RECOGNITION_UNCERTAIN', '上次识别结果尚未确定，请手填，不能重复调用')
    if item.status in ('queued', 'running'):
        return item_json(db, item, batch)
    attempts = db.scalar(select(func.count()).select_from(RecognitionAttempt).where(RecognitionAttempt.item_id == item.id))
    if attempts >= max_attempts:
        fail(409, 'RETRY_LIMIT', '识别次数已达上限，请继续手填')
    # The caller rechecks current editor permission under the family lock.
    # A historical revoked error cannot prevent an explicitly restored editor
    # from resuming their own draft after that capability check.
    item.generation += 1
    item.status, item.error = 'queued', None
    item.version += 1
    batch.version += 1
    db.add(RecognitionAttempt(item_id=item.id, generation=item.generation,
        request_id=uuid4().hex, available_at=now or utcnow()))
    db.flush()
    return item_json(db, item, batch)


def confirm(db, family, user, batch, body):
    def execute():
        results = {}
        for entry in sorted(body.entries, key=lambda e: e.candidate_id):
            try:
                with db.begin_nested():
                    candidate = get_candidate(db, batch.id, entry.candidate_id, lock=True)
                    if candidate.confirmed_garment_id:
                        garment = wardrobe.get_garment(db, family.id, candidate.confirmed_garment_id, lock=True)
                        kind = 'existing'
                    else:
                        item = get_item(db, batch.id, candidate.item_id, lock=True)
                        require_item(item)
                        if candidate.discarded:
                            fail(409, 'CANDIDATE_DISCARDED', '该候选已明确放弃')
                        check_version(candidate.version, entry.expected_version)
                        if not candidate.selected:
                            fail(422, 'CANDIDATE_NOT_SELECTED', '请明确选中要入库的候选')
                        if not candidate.category:
                            fail(422, 'CATEGORY_REQUIRED', '请先确认衣物类别')
                        wardrobe.validate_owners(db, family.id, candidate.owners)
                        if entry.action == 'existing':
                            garment = wardrobe.get_garment(db, family.id, entry.existing_garment_id, lock=True)
                            wardrobe.require_active(garment)
                            check_version(garment.version, entry.expected_garment_version)
                            current = {int(o['child_id']) for o in wardrobe.owners_json(db, garment, lock=True)}
                            if not {int(o['child_id']) for o in candidate.owners} <= current:
                                fail(409, 'OWNER_REVIEW_REQUIRED', '待确认孩子尚未使用这件衣物，请先核对共用关系')
                            kind = 'existing'
                        else:
                            garment = Clothing(family_id=family.id, created_by=user.id, source_candidate_id=candidate.id,
                                name=candidate.name or {'top': '上衣', 'bottom': '下装', 'outerwear': '外套',
                                    'dress': '连衣裙', 'onesie': '连体衣', 'shoes': '鞋', 'accessory': '配饰'}[candidate.category],
                                category=candidate.category, colors=candidate.colors, pattern=candidate.pattern,
                                thickness=candidate.thickness, state=candidate.state, asset_id=item.asset_id)
                            db.add(garment)
                            db.flush()
                            wardrobe.replace_owners(db, garment, candidate.owners)
                            kind = 'new'
                        candidate.confirmed_garment_id = garment.id
                        candidate.confirmation_kind = kind
                        candidate.version += 1
                        batch.version += 1
                        db.flush()
                    result = wardrobe.garment_json(db, garment, lock=True)
                results[entry.candidate_id] = {'candidate_id': str(entry.candidate_id), 'status': 'success',
                    'kind': kind, 'garment': result, 'error': None}
            except DomainError as error:
                results[entry.candidate_id] = {'candidate_id': str(entry.candidate_id), 'status': 'failed',
                    'kind': entry.action, 'garment': None, 'error': {'code': error.code, 'message': error.message}}
        return operation_response(body.operation_id, [results[e.candidate_id] for e in body.entries])
    return run_operation(db, family, user, 'batch:' + str(batch.id), body.operation_id,
                         body.model_dump(mode='json'), execute)


def resolve_confirmation(db, family, user, batch, body):
    return run_operation(db, family, user, 'batch:' + str(batch.id), body.operation_id,
        body.model_dump(mode='json'), lambda: not_executed(body.operation_id, [e.model_dump() for e in body.entries]))
