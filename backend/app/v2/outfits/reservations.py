import jwt
from sqlalchemy import select
from app.v2.children.models import Child
from app.v2.core.errors import fail
from app.v2.identity.models import User
from app.v2.outfits.models import Reservation, OutfitPlan
from app.v2.outfits.signature import draft_binding
from app.v2.recognition.operations import digest


def occupancy(db, family_id, target_date, lock=False):
    query = select(Reservation, OutfitPlan, Child, User).join(OutfitPlan, Reservation.plan_id == OutfitPlan.id)
    query = query.join(Child, Reservation.child_id == Child.id).join(User, OutfitPlan.updated_by == User.id)
    query = query.where(Reservation.family_id == family_id, Reservation.target_date == target_date)
    query = query.order_by(Reservation.garment_id, OutfitPlan.id, Reservation.usage)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    grouped = {}
    for reservation, plan, child, user in db.execute(query):
        gid = str(reservation.garment_id)
        grouped.setdefault(gid, {'garment_id': gid, 'sources': []})['sources'].append({
            'child_id': str(child.id), 'nickname': child.nickname, 'plan_id': str(plan.id),
            'sequence': plan.sequence, 'version': plan.version, 'usage': reservation.usage,
            'selected_by': user.nickname, 'selected_by_id': str(user.id),
            'target_date': plan.target_date.isoformat(), 'arrangement': reservation.arrangement})
    return list(grouped.values())


def conflicts(occupancy_rows, body):
    usages = {}
    for usage, items in (('main', body.main_items), ('backup', body.backup.items)):
        for item in items:
            usages.setdefault(str(item.garment_id), []).append(usage)
    results = []
    for row in occupancy_rows:
        if row['garment_id'] not in usages:
            continue
        sources = [source for source in row['sources'] if source['child_id'] != str(body.child_id)
                   and source['plan_id'] != str(body.target_plan_id)]
        if sources:
            arrangements = [{'plan_id': s['plan_id'], 'version': s['version'], 'arrangement': s['arrangement']}
                for s in row['sources'] if s.get('arrangement') and s['plan_id'] != str(body.target_plan_id)]
            results.append({'garment_id': row['garment_id'], 'usage': usages[row['garment_id']],
                            'sources': sources, 'existing_arrangements': arrangements})
    return results


def grant_body(body, user, family_id, conflict, periods, reason):
    return {'family_id': str(family_id), 'actor_id': str(user.id), 'child_id': str(body.child_id),
        'target_date': body.target_date.isoformat(), 'garment_id': conflict['garment_id'],
        'usage': conflict['usage'], 'target_plan_id': str(body.target_plan_id) if body.target_plan_id else None,
        'draft_id': body.draft_id, 'draft_signature': draft_binding(body),
        'source_fingerprint': digest(conflict['sources']), 'sources': conflict['sources'],
        'arrangement_fingerprint': digest(conflict.get('existing_arrangements', [])),
        'periods': periods, 'reason': reason}


def validate_periods(body, conflict):
    periods = [{**p.model_dump(), 'child_id': str(p.child_id)} for p in body.periods]
    needed = {str(body.child_id)} | {s['child_id'] for s in conflict['sources']}
    if {p['child_id'] for p in periods} != needed or len(periods) != len(needed):
        fail(422, 'SHARING_PERIODS_REQUIRED', '请明确安排全部涉及孩子的时段')
    if any(p['start'] >= p['end'] for p in periods):
        fail(422, 'SHARING_PERIODS_INVALID', '请填写有效时段')
    ordered = sorted(periods, key=lambda p: p['start'])
    if any(left['end'] > right['start'] for left, right in zip(ordered, ordered[1:])):
        fail(422, 'SHARING_PERIODS_OVERLAP', '共用时段不能重叠')
    for source in conflict.get('existing_arrangements', []):
        previous = source['arrangement']
        for existing in previous['periods']:
            proposed = next((p for p in periods if p['child_id'] == existing['child_id']), None)
            if proposed != existing:
                fail(409, 'SHARING_REVIEW_REQUIRED', '已有分时安排发生变化，请先核对来源方案')
    return periods


def create_grant(body, user, family_id, occupancy_rows, settings):
    conflict = next((c for c in conflicts(occupancy_rows, body) if c['garment_id'] == str(body.garment_id)), None)
    if conflict is None:
        fail(409, 'SHARING_REVIEW_REQUIRED', '共用来源已变化，请重新核对')
    value = grant_body(body, user, family_id, conflict, validate_periods(body, conflict), body.reason.strip())
    token = jwt.encode({'iss': 'zhida-sharing-v2', 'sub': str(user.id), 'grant': value},
                       settings.jwt_secret.get_secret_value(), algorithm='HS256')
    return {**value, 'token': token}


def verified_grants(body, user, family_id, conflicts_rows, settings):
    accepted = {}
    for conflict in conflicts_rows:
        for provided in body.sharing_grants:
            try:
                value = jwt.decode(provided['token'], settings.jwt_secret.get_secret_value(), algorithms=['HS256'],
                    issuer='zhida-sharing-v2', options={'require': ['iss', 'sub', 'grant']})['grant']
                if {key: val for key, val in provided.items() if key != 'token'} != value:
                    continue
                expected = grant_body(body, user, family_id, conflict, value['periods'], value['reason'])
                if value == expected:
                    accepted[conflict['garment_id']] = value
            except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
                continue
    return accepted
