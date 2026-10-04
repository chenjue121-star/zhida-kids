from sqlalchemy import select
from app.v2.core.clock import utcnow
from app.v2.core.errors import DomainError, fail
from app.v2.families.access import check_version
from app.v2.families.service import receipt
from app.v2.children.models import Child
from app.v2.children.service import get_child
from app.v2.wardrobe.models import Clothing, ChildClothing, ClothingRemoval
from app.v2.recognition.operations import run_operation, operation_response, not_executed


def get_garment(db, family_id, garment_id, lock=False):
    query = select(Clothing).where(Clothing.family_id == family_id, Clothing.id == garment_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    garment = db.scalar(query)
    if garment is None:
        fail(404, 'NOT_FOUND', '衣物不存在或不属于当前家庭')
    return garment


def owner_json(child, fit):
    return {'child_id': str(child.id), 'nickname': child.nickname, 'fit': fit,
            'archived': child.archived_at is not None}


def owners_json(db, garment, lock=False):
    query = select(ChildClothing, Child).join(Child, Child.id == ChildClothing.child_id).where(
            ChildClothing.clothing_id == garment.id, ChildClothing.ended_at.is_(None),
            Child.archived_at.is_(None)).order_by(Child.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return [owner_json(child, relation.fit) for relation, child in db.execute(query)]


def garment_json(db, garment, lock=False):
    owners = owners_json(db, garment, lock=lock)
    history = {}
    last_owners = []
    history_query = select(ClothingRemoval).where(ClothingRemoval.clothing_id == garment.id).order_by(ClothingRemoval.id)
    relations_query = select(ChildClothing, Child).join(Child, Child.id == ChildClothing.child_id).where(
        ChildClothing.clothing_id == garment.id).order_by(Child.id)
    if lock:
        history_query = history_query.with_for_update().execution_options(populate_existing=True)
        relations_query = relations_query.with_for_update().execution_options(populate_existing=True)
    for removal in db.scalars(history_query):
        last_owners = []
        for owner in removal.owners:
            child_query = select(Child).where(Child.id == int(owner['child_id']))
            if lock:
                child_query = child_query.with_for_update().execution_options(populate_existing=True)
            child = db.scalar(child_query)
            history[owner['child_id']] = {**owner, 'archived': child is None or child.archived_at is not None}
            last_owners.append(history[owner['child_id']])
    for relation, child in db.execute(relations_query):
        if relation.ended_at is not None or child.archived_at is not None:
            history[str(child.id)] = owner_json(child, relation.fit)
    return {'id': str(garment.id), 'version': garment.version, 'name': garment.name,
            'category': garment.category, 'colors': garment.colors, 'pattern': garment.pattern,
            'thickness': garment.thickness, 'state': garment.state,
            'asset_id': str(garment.asset_id) if garment.asset_id else None,
            'archived_at': garment.archived_at.isoformat() + 'Z' if garment.archived_at else None,
            'owners': owners, 'history_owners': list(history.values()), 'last_owners': last_owners}


def validate_owners(db, family_id, owners):
    if not owners or len({int(o['child_id']) for o in owners}) != len(owners):
        fail(422, 'VALIDATION_ERROR', '请选择至少一名孩子，每个孩子只能选择一次')
    for owner in sorted(owners, key=lambda o: int(o['child_id'])):
        get_child(db, family_id, int(owner['child_id']), lock=True)
        if owner.get('fit') not in ('small', 'fit', 'large', 'unknown'):
            fail(422, 'VALIDATION_ERROR', '请明确确认每名孩子当前的合身情况')


def replace_owners(db, garment, owners, now=None):
    validate_owners(db, garment.family_id, owners)
    wanted = {int(owner['child_id']): owner['fit'] for owner in owners}
    relations = {r.child_id: r for r in db.scalars(select(ChildClothing).where(
        ChildClothing.clothing_id == garment.id).with_for_update().execution_options(populate_existing=True))}
    for child_id, relation in relations.items():
        if child_id not in wanted and relation.ended_at is None:
            relation.ended_at = now or utcnow()
    for child_id, fit in wanted.items():
        if child_id in relations:
            relations[child_id].fit = fit
            relations[child_id].ended_at = None
        else:
            db.add(ChildClothing(clothing_id=garment.id, child_id=child_id, fit=fit))
    db.flush()


def require_active(garment):
    if garment.archived_at is not None:
        fail(409, 'RESTORE_REQUIRED', '这件衣物已移出，请先核对并恢复')


def update(db, garment, body):
    require_active(garment)
    check_version(garment.version, body.expected_version)
    changes = body.model_dump(exclude_unset=True, exclude={'expected_version'})
    if changes:
        for key, value in changes.items():
            setattr(garment, key, value)
        garment.version += 1
        db.flush()
    return garment_json(db, garment, lock=True)


def update_owners(db, garment, body):
    require_active(garment)
    check_version(garment.version, body.expected_version)
    replace_owners(db, garment, [o.model_dump() for o in body.owners])
    garment.version += 1
    db.flush()
    return garment_json(db, garment, lock=True)


def transfer(db, garment, body):
    require_active(garment)
    check_version(garment.version, body.expected_version)
    if len(owners_json(db, garment, lock=True)) != 1:
        fail(409, 'SHARED_TRANSFER_CONFLICT', '使用关系已变化，请重新核对共用孩子')
    replace_owners(db, garment, [{'child_id': body.child_id, 'fit': body.fit}])
    garment.version += 1
    db.flush()
    return garment_json(db, garment, lock=True)


def archive(db, garment, user, expected_version, now=None):
    if garment.archived_at is not None:
        return garment_json(db, garment, lock=True)
    check_version(garment.version, expected_version)
    moment = now or utcnow()
    # Include archived children in the immutable last-use snapshot.
    snapshot = [owner_json(child, relation.fit) for relation, child in db.execute(
        select(ChildClothing, Child).join(Child, Child.id == ChildClothing.child_id).where(
            ChildClothing.clothing_id == garment.id, ChildClothing.ended_at.is_(None)).order_by(Child.id)
            .with_for_update().execution_options(populate_existing=True))]
    db.add(ClothingRemoval(clothing_id=garment.id, removed_by=user.id, owners=snapshot, removed_at=moment))
    for relation in db.scalars(select(ChildClothing).where(ChildClothing.clothing_id == garment.id,
                                                         ChildClothing.ended_at.is_(None)).with_for_update()):
        relation.ended_at = moment
    garment.archived_at = moment
    garment.version += 1
    db.flush()
    return garment_json(db, garment, lock=True)


def restore(db, garment, body):
    if garment.archived_at is None:
        return garment_json(db, garment, lock=True)
    check_version(garment.version, body.expected_version)
    replace_owners(db, garment, [o.model_dump() for o in body.owners])
    garment.archived_at = None
    garment.version += 1
    db.flush()
    return garment_json(db, garment, lock=True)


def list_garments(db, family_id, *, child_id=None, category=None, state=None, fit=None,
                  shared=None, archived=False, history_child_id=None, cursor=None, limit=30):
    if child_id is not None:
        get_child(db, family_id, child_id)
    if history_child_id is not None:
        if db.scalar(select(Child.id).where(Child.id == history_child_id, Child.family_id == family_id)) is None:
            fail(404, 'NOT_FOUND', '历史孩子不属于当前家庭')
    query = select(Clothing).where(Clothing.family_id == family_id)
    query = query.where(Clothing.archived_at.is_not(None) if archived else Clothing.archived_at.is_(None))
    all_items = [garment_json(db, g) for g in db.scalars(query.order_by(Clothing.id))]
    filtered = []
    for item in all_items:
        owners = item['owners']
        relevant = [o for o in owners if child_id is None or o['child_id'] == str(child_id)]
        if child_id is not None and not relevant:
            continue
        if category is not None and item['category'] != category:
            continue
        if state is not None and item['state'] != state:
            continue
        if fit is not None and not any(o['fit'] == fit for o in relevant):
            continue
        if shared is not None and (len(owners) > 1) != shared:
            continue
        if history_child_id is not None and not any(o['child_id'] == str(history_child_id) for o in item['last_owners']):
            continue
        filtered.append(item)
    after = [g for g in filtered if cursor is None or int(g['id']) > cursor]
    page = after[:limit]
    result = {'items': page, 'total': len(filtered), 'family_total': len(all_items),
              'next_cursor': page[-1]['id'] if len(after) > limit else None}
    if archived:
        history = {}
        for item in all_items:
            for owner in item['last_owners']:
                history[owner['child_id']] = {'id': owner['child_id'], 'nickname': owner['nickname'],
                                              'archived': owner['archived']}
        result['history_children'] = [history[key] for key in sorted(history, key=int)]
    return result


def bulk(db, family, user, body, now=None):
    def execute():
        results = []
        # Same lock order for every batch. Return results in original UI order.
        result_by_id = {}
        for item in sorted(body.items, key=lambda i: i.id):
            try:
                with db.begin_nested():
                    garment = get_garment(db, family.id, item.id, lock=True)
                    if body.action == 'archive':
                        result = archive(db, garment, user, item.expected_version, now)
                    else:
                        require_active(garment)
                        if garment.state != body.state:
                            check_version(garment.version, item.expected_version)
                            garment.state = body.state
                            garment.version += 1
                            db.flush()
                        result = garment_json(db, garment, lock=True)
                result_by_id[item.id] = {'id': str(item.id), 'status': 'success', 'kind': 'existing', 'garment': result, 'error': None}
            except DomainError as error:
                result_by_id[item.id] = {'id': str(item.id), 'status': 'failed', 'kind': 'existing', 'garment': None,
                                         'error': {'code': error.code, 'message': error.message}}
        results = [result_by_id[item.id] for item in body.items]
        return operation_response(body.operation_id, results)
    return run_operation(db, family, user, 'wardrobe', body.operation_id, body.model_dump(mode='json'), execute)


def resolve_bulk(db, family, user, body):
    return run_operation(db, family, user, 'wardrobe', body.operation_id, body.model_dump(mode='json'),
                         lambda: not_executed(body.operation_id, [i.model_dump() for i in body.items], 'id'))


def single_operation(db, family, user, garment, action, body, key=None, resolve=False, now=None):
    if not resolve and key != body.operation_id:
        fail(422, 'VALIDATION_ERROR', '请求标识须与 operation_id 一致')
    canonical = {**body.model_dump(mode='json'), 'action': action, 'id': garment.id}
    def execute():
        if resolve:
            return not_executed(body.operation_id, [{'id': garment.id}], 'id')
        result = archive(db, garment, user, body.expected_version, now) if action == 'archive' else restore(db, garment, body)
        return operation_response(body.operation_id, [{'id': str(garment.id), 'status': 'success',
            'kind': 'existing', 'garment': result, 'error': None}])
    result = run_operation(db, family, user, 'wardrobe', body.operation_id, canonical, execute)
    if resolve:
        return result
    entry = result['results'][0]
    if entry['status'] == 'failed':
        fail(409, entry['error']['code'], entry['error']['message'])
    return entry['garment']
