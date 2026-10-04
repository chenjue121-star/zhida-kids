from copy import deepcopy
from uuid import uuid4

from sqlalchemy import delete, func, select, update

from app.v2.children.models import ChildMeasurement
from app.v2.children.service import get_child, child_json, measurement_json
from app.v2.core.clock import local_today
from app.v2.core.errors import fail
from app.v2.families.access import family_access, check_version
from app.v2.families.models import Membership
from app.v2.identity.models import User
from app.v2.outfits import rules, reservations, signature
from app.v2.outfits.models import OutfitPlan, PlanRevision, Recommendation, RecommendationRequest, Reservation
from app.v2.preferences import service as preferences
from app.v2.recognition.operations import digest, lookup, run_operation
from app.v2.wardrobe.models import Clothing, ChildClothing
from app.v2.wardrobe.service import garment_json, get_garment
from app.v2.weather import forecast

EDITORS = ('admin', 'editor')


class ForecastSnapshot(dict):
    """Transport metadata stays internal and is not serialized into API weather."""
    def __init__(self, values, binding):
        super().__init__(values)
        self.binding = binding


def weather_for(db, request, fid, user, body, write=True):
    """Read location, release checkout, perform I/O, and let capture recheck access."""
    family, _ = family_access(db, fid, user, EDITORS if write else None)
    payload = {'target_date': body.target_date.isoformat(), 'timezone': family.timezone,
               'city': body.city or family.city, 'lat': body.lat, 'lon': body.lon}
    binding = {'timezone': family.timezone, 'uses_default_city': body.city is None and body.lat is None,
               'default_city': family.city}
    db.rollback()
    provider = getattr(request.app.state, 'forecast_provider', None)
    try:
        weather = provider(payload) if provider is not None else forecast.fetch(
            request.app.state.settings, payload, getattr(request.app.state, 'weather_get', None))
    except Exception:
        weather = forecast.unknown(payload['target_date'], payload)
    if not isinstance(weather, dict) or weather.get('target_date') != payload['target_date']:
        weather = forecast.unknown(payload['target_date'], payload)
    if weather.get('status') == 'known':
        try:
            low, high = forecast.finite(weather['temp_min']), forecast.finite(weather['temp_max'])
            if low > high or not -90 <= low <= high <= 65:
                raise ValueError('Invalid forecast')
            weather = {**weather, 'temp_min': round(low, 1), 'temp_max': round(high, 1)}
        except (KeyError, TypeError, ValueError):
            weather = forecast.unknown(payload['target_date'], payload)
    return ForecastSnapshot(weather, binding)


def age_months(child, target):
    if child.birthday:
        return max(0, (target.year - child.birthday.year) * 12 + target.month - child.birthday.month -
                   (target.day < child.birthday.day))
    recorded = child.age_recorded_on or target
    elapsed = (target.year - recorded.year) * 12 + target.month - recorded.month
    return max(0, (child.age_months or 0) + elapsed)


def resolve_subject(db, family, member, child, body, lock):
    settings = preferences.get_settings(db, child.id, lock=lock)
    chosen = member
    if body.preference_mode == 'designated_member':
        query = select(Membership).where(Membership.id == body.designated_member_id,
            Membership.family_id == family.id, Membership.status == 'active')
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        chosen = db.scalar(query)
        if chosen is None:
            fail(422, 'INVALID_MEMBER', '请选择本家庭有效成员的偏好')
    owner = 'family' if body.preference_mode == 'family' else 'member:' + str(chosen.id)
    profile = preferences.get_profile(db, child.id, owner, lock=lock)
    subject = {'mode': body.preference_mode, 'owner_key': owner,
               'membership_id': str(chosen.id) if owner != 'family' else None,
               'profile_version': profile.version if profile else 0, 'settings_version': settings.version,
               'learning_version': profile.learning_version if profile else 0,
               'learning_rule_version': preferences.LEARNING_RULE_VERSION}
    return subject, preferences.settings_json(settings), preferences.profile_json(profile)['effective_weights']


def capture(db, fid, user, body, weather, lock=False, write=True):
    family, member = family_access(db, fid, user, EDITORS if write else None, lock=lock)
    binding = getattr(weather, 'binding', None)
    if binding and (binding['timezone'] != family.timezone or
                   (binding['uses_default_city'] and binding['default_city'] != family.city)):
        fail(409, 'INPUT_CHANGED', '家庭地点或时区已变化，请重新获取目标日天气')
    child = get_child(db, fid, body.child_id, lock=lock)
    subject, comfort, styles = resolve_subject(db, family, member, child, body, lock)
    query = select(Clothing, ChildClothing).join(ChildClothing, ChildClothing.clothing_id == Clothing.id).where(
        Clothing.family_id == fid, ChildClothing.child_id == child.id, ChildClothing.ended_at.is_(None)
    ).order_by(Clothing.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    garments = []
    for garment, relation in db.execute(query):
        value = garment_json(db, garment, lock=lock)
        value.update(garment_id=value['id'], expected_version=value['version'], fit=relation.fit)
        value['eligible'] = rules.eligible(value, weather, comfort)
        value['eligibility_reason'] = None if value['eligible'] else (
            '合身情况需核对' if relation.fit == 'unknown' else '当前可用、合身或舒适条件不符')
        garments.append(value)
    measurement_query = select(ChildMeasurement).where(ChildMeasurement.child_id == child.id).order_by(
        ChildMeasurement.measured_on.desc(), ChildMeasurement.id.desc()).limit(1)
    if lock:
        measurement_query = measurement_query.with_for_update().execution_options(populate_existing=True)
    measurement = measurement_json(db.scalar(measurement_query))
    occupancy = reservations.occupancy(db, fid, body.target_date, lock=lock)
    version = signature.input_version(family, child, measurement, subject, comfort, garments, occupancy, body, weather)
    return {'family': family, 'member': member, 'child': child, 'preference_subject': subject,
            'comfort': comfort, 'styles': styles, 'garments': garments, 'occupancy': occupancy,
            'weather': weather, 'input_version': version, 'age_months': age_months(child, body.target_date)}


def selected_plans(db, fid, child_id, target_date):
    query = select(OutfitPlan, PlanRevision).join(PlanRevision, (PlanRevision.plan_id == OutfitPlan.id) &
        (PlanRevision.version == OutfitPlan.version)).where(OutfitPlan.family_id == fid,
        OutfitPlan.child_id == child_id, OutfitPlan.target_date == target_date,
        OutfitPlan.status == 'selected').order_by(OutfitPlan.sequence)
    return [snapshot_json(plan, revision) for plan, revision in db.execute(query)]


def cached_recommendation(db, context, user):
    return db.scalar(select(Recommendation).where(Recommendation.family_id == context['family'].id,
        Recommendation.input_version == context['input_version'],
        (Recommendation.visibility == 'family') | (Recommendation.actor_id == user.id)
    ).order_by(Recommendation.id.desc()).limit(1))


def context(db, request, fid, user, body):
    weather = weather_for(db, request, fid, user, body, write=False)
    state = capture(db, fid, user, body, weather, write=False)
    suggestion = cached_recommendation(db, state, user)
    family, member, child = state['family'], state['member'], state['child']
    plans = selected_plans(db, fid, child.id, body.target_date)
    for plan in plans:
        plan['current_warnings'] = current_warnings(db, state, plan)
    return {'today': local_today(family.timezone, request.app.state.clock()).isoformat(),
        'timezone': family.timezone, 'target_date': body.target_date.isoformat(), 'role': member.role,
        'child': child_json(db, child), 'weather': weather, 'input_version': state['input_version'],
        'preference_subject': state['preference_subject'], 'preference_mode': body.preference_mode,
        'designated_member_id': str(body.designated_member_id) if body.designated_member_id else None,
        'scene': body.scene, 'garments': state['garments'], 'occupancy': state['occupancy'],
        'plans': plans,
        'suggestion': deepcopy(suggestion.response) if suggestion else None}


def current_warnings(db, state, plan):
    warnings = []
    current = {g['garment_id']: g for g in state['garments']}
    for item in plan['main_items'] + plan['backup']['items']:
        garment = current.get(item['garment_id'])
        if garment is None or not garment['eligible']:
            warnings.append({'code': 'CURRENT_GARMENT_UNAVAILABLE', 'garment_id': item['garment_id'],
                             'message': item['name'] + '当前可用或合身情况需要核对，已选内容已保留'})
        elif garment['version'] != item['version']:
            warnings.append({'code': 'CURRENT_GARMENT_CHANGED', 'garment_id': item['garment_id'],
                             'message': item['name'] + '资料已变化，已选快照已保留'})
    if signature.effective_weather(plan['weather']) != signature.effective_weather(state['weather']):
        warnings.append({'code': 'CURRENT_WEATHER_CHANGED', 'message': '目标日天气有变化，已选搭配已保留'})
    subject = plan['preference_subject']
    profile = preferences.get_profile(db, state['child'].id, subject['owner_key'])
    if subject['settings_version'] != state['comfort']['version'] or subject['profile_version'] != (profile.version if profile else 0) or \
            subject.get('learning_version', 0) != (profile.learning_version if profile else 0):
        warnings.append({'code': 'CURRENT_PREFERENCES_CHANGED', 'message': '偏好或舒适设置有变化，已选依据已保留'})
    grants = {g['garment_id']: g for g in plan.get('sharing_arrangements', [])}
    for gid in sorted({i['garment_id'] for i in plan['main_items'] + plan['backup']['items']}, key=int):
        sources = next((row['sources'] for row in state['occupancy'] if row['garment_id'] == gid), [])
        others = [s for s in sources if s['child_id'] != plan['child_id']]
        grant = grants.get(gid)
        if grant is None and others:
            warnings.append({'code': 'CURRENT_OCCUPANCY_CHANGED', 'garment_id': gid,
                'message': '其他孩子也已有此实物的使用安排，请使用前核对分时，已选内容已保留'})
        elif grant:
            arrangements = [{'plan_id': s['plan_id'], 'version': s['version'], 'arrangement': s['arrangement']}
                for s in sources if s.get('arrangement') and s['plan_id'] != plan['id']]
            if (digest(others) != grant['source_fingerprint'] or
                    digest(arrangements) != grant.get('arrangement_fingerprint')):
                warnings.append({'code': 'CURRENT_SHARING_CHANGED', 'garment_id': gid,
                    'message': '分时使用来源有变化，请使用前重新核对，已选内容已保留'})
    return warnings


def rule_parameters(state, body, occupy=True):
    blocked = [row['garment_id'] for row in state['occupancy'] if any(
        source['child_id'] != str(body.child_id) for source in row['sources'])] if occupy else []
    return {'scene': body.scene, 'age_months': state['age_months'], 'weather': state['weather'],
            'comfort': state['comfort'], 'styles': state['styles'], 'locked_ids': body.locked_ids,
            'excluded_ids': body.excluded_ids, 'occupied_ids': blocked,
            'exclude_combination': getattr(body, 'exclude_combination', [])}


def backup_errors(state, body, main, backup):
    if body.backup.mode == 'none':
        return []
    if not backup:
        return [{'code': 'BACKUP_REVIEW_REQUIRED', 'message': '请确认实际备用衣物或改为无备用'}]
    if {rules.identity(i) for i in backup} & set(map(str, body.excluded_ids)):
        return [{'code': 'EXCLUDED_ITEM', 'message': '本次不穿的实物仍在备用中'}]
    if body.backup.mode == 'full':
        if {rules.identity(i) for i in main} == {rules.identity(i) for i in backup}:
            return [{'code': 'BACKUP_DUPLICATE', 'message': '整套备用与主搭配为相同实物，请重新核对'}]
        return rules.validate(backup, body.scene, state['age_months'], state['weather'], state['comfort'])
    errors = []
    main_by_id = {rules.identity(i): i for i in main}
    all_combined = list(main)
    for item, entry in zip(backup, body.backup.items):
        replacement = str(entry.replaces_garment_id) if entry.replaces_garment_id else None
        original = main_by_id.get(replacement) if replacement else next(
            (i for i in main if i['category'] == item['category']), None)
        if original is None or original['category'] != item['category'] or rules.identity(original) == rules.identity(item):
            errors.append({'code': 'BACKUP_INCOMPATIBLE', 'garment_id': rules.identity(item),
                           'message': '局部备用需要明确兼容的替换位置'})
            continue
        combined = [i for i in main if rules.identity(i) != rules.identity(original)] + [item]
        errors.extend(rules.validate(combined, body.scene, state['age_months'], state['weather'], state['comfort']))
        all_combined = [i for i in all_combined if i['category'] != original['category']] + [item]
    errors.extend(rules.validate(all_combined, body.scene, state['age_months'], state['weather'], state['comfort']))
    return errors


def request_record(db, fid, user, body):
    return db.scalar(select(RecommendationRequest).where(RecommendationRequest.family_id == fid,
        RecommendationRequest.actor_id == user.id, RecommendationRequest.request_id == body.request_id)
        .with_for_update().execution_options(populate_existing=True))


def recommend(db, request, fid, user, body):
    family_access(db, fid, user, EDITORS, lock=True)
    previous = request_record(db, fid, user, body)
    request_hash = digest(body.model_dump(mode='json'))
    if previous:
        if previous.request_hash != request_hash:
            fail(409, 'IDEMPOTENCY_CONFLICT', '此请求标识已用于不同推荐条件')
        if previous.response is None:
            fail(409, 'RECOMMENDATION_PENDING', '原推荐结果待确认，请保留当前内容')
        response, original_version = deepcopy(previous.response), previous.input_version
        weather = weather_for(db, request, fid, user, body)
        current = capture(db, fid, user, body, weather, lock=True)
        if current['input_version'] != original_version:
            fail(409, 'INPUT_CHANGED', '原建议依据已变化，请保留草稿并重新获取建议')
        return response
    weather = weather_for(db, request, fid, user, body)
    state = capture(db, fid, user, body, weather, lock=True)
    # Weather I/O released the family lock; another identical request may have won.
    winner = request_record(db, fid, user, body)
    if winner is not None:
        if winner.request_hash != request_hash:
            fail(409, 'IDEMPOTENCY_CONFLICT', '此请求标识已用于不同推荐条件')
        if winner.response is None:
            fail(409, 'RECOMMENDATION_PENDING', '原推荐结果待确认，请保留当前内容')
        if winner.input_version != state['input_version']:
            fail(409, 'INPUT_CHANGED', '原建议依据已变化，请重新获取建议')
        return deepcopy(winner.response)
    cached = None if body.exclude_combination else cached_recommendation(db, state, user)
    attempt = RecommendationRequest(family_id=fid, actor_id=user.id, request_id=body.request_id,
        request_hash=request_hash, input_version=state['input_version'])
    db.add(attempt)
    if cached:
        response = {**deepcopy(cached.response), 'request_id': body.request_id, 'cached': True}
        attempt.status, attempt.response = 'completed', response
        db.flush()
        return response
    params = rule_parameters(state, body)
    baseline = rules.generate(state['garments'], **params)
    combinations = rules.options(state['garments'], **params)
    backup = [g for entry in body.backup.items for g in state['garments'] if g['garment_id'] == str(entry.garment_id)]
    if body.backup.mode != 'none':
        combinations = [combo for combo in combinations if not backup_errors(state, body, combo, backup)]
        if combinations:
            baseline['items'] = combinations[0]
        else:
            baseline.update(items=[], missing=[{'code': 'BACKUP_REVIEW_REQUIRED',
                'message': '无法保持已确认备用兼容，请家长重新核对或移除备用'}])
    db.flush()
    attempt_id, original_version = attempt.id, state['input_version']
    # Commit the durable request identity and release SQL before model transport.
    db.commit()
    source = 'rules'
    result = None
    if combinations:
        provider = getattr(request.app.state, 'outfit_provider', None)
        if provider is not None:
            try:
                result = provider.recommend({'scene': body.scene, 'styles': state['styles'], 'combinations': combinations})
            except Exception:
                baseline['warnings'].append({'code': 'PROVIDER_UNAVAILABLE', 'message': '推荐服务暂不可用，已按相同规则准备基础建议'})
        if result is not None:
            ids = result.get('garment_ids') if isinstance(result, dict) else None
            wanted = set(map(str, ids)) if isinstance(ids, list) else set()
            chosen = next((combo for combo in combinations if {rules.identity(i) for i in combo} == wanted and
                           len(combo) == len(ids)), None) if isinstance(ids, list) else None
            if chosen:
                baseline['items'], source = chosen, 'model'
                if isinstance(result.get('reason'), str):
                    baseline['reason'] = result['reason'][:300]
            else:
                baseline['warnings'].append({'code': 'PROVIDER_INVALID', 'message': '模型结果未通过核对，已使用相同规则的基础建议'})
    fresh = capture(db, fid, user, body, weather, lock=True)
    if fresh['input_version'] != original_version:
        fail(409, 'INPUT_CHANGED', '衣物、偏好或家庭安排已变化，请保留草稿并重新获取建议')
    response = {**baseline, 'request_id': body.request_id, 'input_version': original_version,
                'weather': weather, 'preference_subject': fresh['preference_subject'], 'source': source,
                'cached': False, 'rule_version': rules.RULE_VERSION}
    record = Recommendation(family_id=fid, child_id=body.child_id, actor_id=user.id,
        target_date=body.target_date, input_version=original_version,
        visibility='family' if body.preference_mode == 'family' else 'actor', response={})
    db.add(record)
    db.flush()
    response['recommendation_id'] = str(record.id)
    record.response = response
    attempt = db.get(RecommendationRequest, attempt_id)
    attempt.status, attempt.response = 'completed', response
    db.flush()
    return response


def selected_items(state, body):
    garments = {g['garment_id']: g for g in state['garments']}
    errors, groups = [], []
    for entries in (body.main_items, body.backup.items):
        items = []
        for entry in entries:
            item = garments.get(str(entry.garment_id))
            if item is None:
                errors.append({'code': 'GARMENT_UNAVAILABLE', 'garment_id': str(entry.garment_id),
                               'message': '该实物不存在或孩子已不能使用'})
            elif entry.expected_version != item['version']:
                errors.append({'code': 'GARMENT_CHANGED', 'garment_id': str(entry.garment_id),
                               'message': '衣物信息已变化，请重新核对'})
            else:
                items.append(deepcopy(item))
        groups.append(items)
    return groups[0], groups[1], errors


def review_state(state, body, user, settings):
    main, backup, missing = selected_items(state, body)
    missing.extend(rules.validate(main, body.scene, state['age_months'], state['weather'], state['comfort']))
    missing.extend(backup_errors(state, body, main, backup))
    ids = {rules.identity(i) for i in main}
    if not set(map(str, body.locked_ids)) <= ids:
        missing.append({'code': 'LOCKED_REQUIRED', 'message': '固定单品未保留，请先明确解除'})
    if {rules.identity(i) for i in main + backup} & set(map(str, body.excluded_ids)):
        missing.append({'code': 'EXCLUDED_ITEM', 'message': '本次不穿的实物仍在主搭配或备用中'})
    if body.backup_needs_review:
        missing.append({'code': 'BACKUP_REVIEW_REQUIRED', 'message': '主搭配已改变，请明确重新确认备用或移除'})
    conflicts = reservations.conflicts(state['occupancy'], body)
    grants = reservations.verified_grants(body, user, state['family'].id, conflicts, settings)
    conflicts = [{**conflict, 'resolved': conflict['garment_id'] in grants} for conflict in conflicts]
    warnings = []
    if state['weather'].get('status') != 'known':
        warnings.append({'code': 'WEATHER_UNKNOWN', 'message': '目标日天气暂未知，请家长核对衣物适宜性'})
    if any(i.get('thickness') == 'unknown' for i in main + backup):
        warnings.append({'code': 'THICKNESS_UNKNOWN', 'message': '部分衣物厚薄未知，请核对'})
    packing = list({rules.identity(i): i for i in main + backup}.values())
    return {'valid': not missing and all(c['resolved'] for c in conflicts),
        'input_version': state['input_version'], 'conflicts': conflicts, 'warnings': warnings,
        'missing': missing, 'packing_items': packing, 'weather': state['weather']}, main, backup, grants


def review(db, request, fid, user, body):
    weather = weather_for(db, request, fid, user, body)
    state = capture(db, fid, user, body, weather, lock=True)
    return review_state(state, body, user, request.app.state.settings)[0]


def backup_candidate_compatible(state, body, main, backup, candidate):
    parameters = (body.scene, state['age_months'], state['weather'], state['comfort'])
    if body.backup.mode == 'full':
        return ({rules.identity(i) for i in main} != {rules.identity(i) for i in backup} and
                not rules.validate_partial(backup, *parameters))
    main_by_id = {rules.identity(i): i for i in main}
    backup_by_id = {rules.identity(i): i for i in backup}
    combined = list(main)
    for entry in body.backup.items:
        item = backup_by_id.get(str(entry.garment_id))
        if item is None or not rules.eligible(item, state['weather'], state['comfort']):
            continue
        original = main_by_id.get(str(entry.replaces_garment_id)) if entry.replaces_garment_id else next(
            (i for i in main if i['category'] == item['category']), None)
        if original is None or original['category'] != item['category'] or rules.identity(original) == rules.identity(item):
            if rules.identity(item) == rules.identity(candidate):
                return False
            continue
        individual = [i for i in main if rules.identity(i) != rules.identity(original)] + [item]
        if rules.identity(item) == rules.identity(candidate) and rules.validate_partial(individual, *parameters):
            return False
        combined = [i for i in combined if i['category'] != original['category']] + [item]
    return not rules.validate_partial(combined, *parameters)


def candidates(db, request, fid, user, body):
    weather = weather_for(db, request, fid, user, body)
    state = capture(db, fid, user, body, weather, lock=True)
    if body.usage == 'main' and body.replace_id in body.locked_ids:
        fail(409, 'LOCKED_ITEM', '请先明确解除固定再替换')
    # Replacement must remain available when the old item became washing or
    # changed version. Proposals use current facts; final save still requires
    # explicit expected_version confirmation for every retained physical item.
    current = {g['garment_id']: g for g in state['garments']}
    entries = body.main_items if body.usage == 'main' else body.backup.items
    if not any(e.garment_id == body.replace_id for e in entries):
        fail(422, 'REPLACE_TARGET_REQUIRED', '请指定当前用途中的实物')
    if str(body.replace_id) not in current:
        # A retained draft slot can outlive archive/transfer. Read only its
        # family-scoped category to locate the slot, never restore ownership.
        former = garment_json(db, get_garment(db, fid, body.replace_id, lock=True), lock=True)
        current[str(body.replace_id)] = {**former, 'garment_id': former['id'], 'fit': 'unknown'}
    if body.usage == 'backup' and body.backup.mode == 'partial':
        target = next(e for e in entries if e.garment_id == body.replace_id)
        if target.replaces_garment_id and str(target.replaces_garment_id) not in current and any(
                e.garment_id == target.replaces_garment_id for e in body.main_items):
            former = get_garment(db, fid, target.replaces_garment_id, lock=True)
            current[str(former.id)] = {'id': str(former.id), 'garment_id': str(former.id),
                'category': former.category, 'state': former.state, 'fit': 'unknown', 'archived_at': former.archived_at}
    main = [current[str(e.garment_id)] for e in body.main_items if str(e.garment_id) in current]
    backup = [current[str(e.garment_id)] for e in body.backup.items if str(e.garment_id) in current]
    selected = main if body.usage == 'main' else backup
    original = next((i for i in selected if i['garment_id'] == str(body.replace_id)), None)
    if original is None:
        fail(422, 'REPLACE_TARGET_REQUIRED', '请指定当前用途中的实物')
    blocked = set(rule_parameters(state, body)['occupied_ids']) | set(map(str, body.excluded_ids))
    result = []
    for item in state['garments']:
        if (not rules.eligible(item, weather, state['comfort']) or item['category'] != original['category'] or
                item['garment_id'] in blocked | {i['garment_id'] for i in selected}):
            continue
        combined = [item if i['garment_id'] == original['garment_id'] else i for i in selected]
        if body.usage == 'main':
            valid = not rules.validate_partial(combined, body.scene, state['age_months'], weather, state['comfort'])
            value = item
        else:
            updated = body.model_copy(deep=True)
            entry = next(e for e in updated.backup.items if e.garment_id == body.replace_id)
            entry.garment_id, entry.expected_version = int(item['garment_id']), item['version']
            valid = backup_candidate_compatible(state, updated, main, combined, item)
            value = {**item, 'replaces_garment_id': str(entry.replaces_garment_id) if entry.replaces_garment_id else None}
        if valid:
            result.append(value)
    return {'items': result, 'input_version': state['input_version']}


def backup(db, request, fid, user, body):
    weather = weather_for(db, request, fid, user, body)
    state = capture(db, fid, user, body, weather, lock=True)
    main, _, _ = selected_items(state, body)
    blocked = set(rule_parameters(state, body)['occupied_ids']) | set(map(str, body.excluded_ids))
    if body.mode == 'full':
        choices = rules.options(state['garments'], **{**rule_parameters(state, body), 'locked_ids': [],
                'exclude_combination': [i['garment_id'] for i in main]})
        return {'mode': 'full', 'items': choices[0] if choices else [], 'input_version': state['input_version']}
    result = []
    for item in state['garments']:
        if item['garment_id'] in blocked | {i['garment_id'] for i in main}:
            continue
        for original in main:
            if original['category'] != item['category']:
                continue
            combined = [i for i in main if i['garment_id'] != original['garment_id']] + [item]
            if not rules.validate(combined, body.scene, state['age_months'], weather, state['comfort']):
                result.append({**item, 'replaces_garment_id': original['garment_id']})
    return {'mode': 'partial', 'items': result, 'input_version': state['input_version']}


def sharing(db, request, fid, user, body):
    weather = weather_for(db, request, fid, user, body)
    state = capture(db, fid, user, body, weather, lock=True)
    main, backup, missing = selected_items(state, body)
    if missing or any(not rules.eligible(i, weather, state['comfort']) for i in main + backup):
        fail(409, 'GARMENT_UNAVAILABLE', '请先核对当前单品的可用、合身和舒适条件')
    return {'grant': reservations.create_grant(body, user, fid, state['occupancy'], request.app.state.settings)}


def get_plan(db, fid, body):
    if body.target_plan_id is None:
        return None
    plan = db.scalar(select(OutfitPlan).where(OutfitPlan.id == body.target_plan_id,
        OutfitPlan.family_id == fid).with_for_update().execution_options(populate_existing=True))
    if plan is None or plan.child_id != body.child_id or plan.target_date != body.target_date:
        fail(404, 'NOT_FOUND', '方案不属于当前孩子或日期')
    check_version(plan.version, body.expected_version)
    if plan.status == 'cancelled':
        fail(409, 'PLAN_CANCELLED', '此方案已撤销，请复用为新草稿后重新选择')
    return plan


def save_snapshot(db, request, fid, user, body, state, plan, main, backup, grants):
    now = request.app.state.clock()
    if plan is None:
        sequence = (db.scalar(select(func.max(OutfitPlan.sequence)).where(OutfitPlan.family_id == fid,
            OutfitPlan.child_id == body.child_id, OutfitPlan.target_date == body.target_date)) or 0) + 1
        plan = OutfitPlan(family_id=fid, child_id=body.child_id, target_date=body.target_date, sequence=sequence,
            created_by=user.id, updated_by=user.id, created_at=now, updated_at=now, version=1)
        db.add(plan)
        db.flush()
    else:
        changed = db.execute(update(OutfitPlan).where(OutfitPlan.id == plan.id,
            OutfitPlan.version == body.expected_version).values(version=body.expected_version + 1,
            updated_by=user.id, updated_at=now))
        if changed.rowcount != 1:
            fail(409, 'VERSION_CONFLICT', '家人已修改此方案，请保留草稿并核对最新内容')
        db.refresh(plan)
    def freeze(item, entry):
        return {**deepcopy(item), 'replaces_garment_id': str(entry.replaces_garment_id) if entry.replaces_garment_id else None}
    snapshot = {'id': str(plan.id), 'family_id': str(fid), 'child_id': str(body.child_id),
        'target_date': body.target_date.isoformat(), 'sequence': plan.sequence, 'version': plan.version,
        'status': 'selected',
        'scene': body.scene, 'main_items': [freeze(i, e) for i, e in zip(main, body.main_items)],
        'backup': {'mode': body.backup.mode, 'items': [freeze(i, e) for i, e in zip(backup, body.backup.items)]},
        'preference_subject': deepcopy(state['preference_subject']), 'weather': deepcopy(state['weather']),
        'input_version': state['input_version'], 'recommendation_id': str(body.recommendation_id) if body.recommendation_id else None,
        'rule_version': rules.RULE_VERSION, 'selected_by': user.nickname, 'selected_by_id': str(user.id),
        'created_at': plan.created_at.isoformat() + 'Z', 'updated_at': now.isoformat() + 'Z',
        'sharing_arrangements': list(grants.values())}
    revision = PlanRevision(plan_id=plan.id, version=plan.version, snapshot=snapshot, created_by=user.id, created_at=now)
    db.add(revision)
    db.flush()
    db.execute(delete(Reservation).where(Reservation.plan_id == plan.id))
    for usage, items in (('main', main), ('backup', backup)):
        for item in items:
            gid = item['garment_id']
            db.add(Reservation(family_id=fid, target_date=body.target_date, plan_id=plan.id,
                revision_id=revision.id, child_id=body.child_id, garment_id=int(gid), usage=usage,
                arrangement=grants.get(gid)))
    db.flush()
    preferences.record_event(db, state['family'], state['child'], state['member'], user, revision,
        'selection:' + digest(body.operation_id), 'selection', 'selection', preferences.styles_from_snapshot(snapshot),
        digest({'operation_id': body.operation_id, 'plan_id': str(plan.id), 'version': plan.version}), now)
    return {'operation_id': body.operation_id, 'status': 'completed', 'plan': snapshot}


def save(db, request, fid, user, body, resolve=False):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    payload = body.model_dump(mode='json')
    previous = lookup(db, fid, user.id, 'outfits', body.operation_id)
    if previous is not None:
        if previous.request_hash != digest(payload):
            fail(409, 'IDEMPOTENCY_CONFLICT', '原操作内容已固定，请查询原保存结果')
        return deepcopy(previous.response)
    if resolve:
        return run_operation(db, family, user, 'outfits', body.operation_id, payload, lambda: {
            'operation_id': body.operation_id, 'status': 'completed', 'plan': None,
            'error': {'code': 'NOT_EXECUTED', 'message': '已核实原操作未执行，请重新核对后开始新尝试'}})
    weather = weather_for(db, request, fid, user, body)
    state = capture(db, fid, user, body, weather, lock=True)
    # Another save/resolve may have committed while weather I/O released the lock.
    family = state['family']
    def execute():
        plan = get_plan(db, fid, body)
        if state['input_version'] != body.input_version:
            fail(409, 'INPUT_CHANGED', '衣物、偏好、天气或使用安排已变化，请重新核对')
        review, main, backup, grants = review_state(state, body, user, request.app.state.settings)
        if not review['valid']:
            if any(not c['resolved'] for c in review['conflicts']):
                fail(409, 'RESERVATION_CONFLICT', '其他孩子已有使用安排，请替换或明确重新核对分时')
            first = review['missing'][0]
            fail(409, first['code'], first['message'])
        if weather.get('status') != 'known' and not body.weather_acknowledged:
            fail(409, 'WEATHER_ACK_REQUIRED', '目标日天气未知，请先明确核对适宜性')
        if body.recommendation_id:
            recommendation = db.scalar(select(Recommendation).where(Recommendation.id == body.recommendation_id,
                Recommendation.family_id == fid, Recommendation.child_id == body.child_id,
                Recommendation.target_date == body.target_date,
                (Recommendation.visibility == 'family') | (Recommendation.actor_id == user.id)))
            if recommendation is None:
                fail(404, 'NOT_FOUND', '原建议不属于当前授权上下文')
        return save_snapshot(db, request, fid, user, body, state, plan, main, backup, grants)
    return run_operation(db, family, user, 'outfits', body.operation_id, payload, execute)


def operation(db, fid, user, operation_id):
    family_access(db, fid, user, lock=True)
    record = lookup(db, fid, user.id, 'outfits', operation_id)
    return deepcopy(record.response) if record else {'operation_id': operation_id, 'status': 'unknown', 'plan': None}



def snapshot_json(plan, revision):
    snapshot = deepcopy(revision.snapshot)
    snapshot.setdefault('status', plan.status)
    return snapshot


def plan_record(db, fid, pid, lock=False):
    query = select(OutfitPlan).where(OutfitPlan.family_id == fid, OutfitPlan.id == pid)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    plan = db.scalar(query)
    if plan is None:
        fail(404, 'NOT_FOUND', '方案不存在或不属于当前家庭')
    revision_query = select(PlanRevision).where(PlanRevision.plan_id == plan.id, PlanRevision.version == plan.version)
    if lock:
        revision_query = revision_query.with_for_update().execution_options(populate_existing=True)
    revision = db.scalar(revision_query)
    if revision is None:
        fail(404, 'NOT_FOUND', '方案版本不存在')
    return plan, revision


def plan_detail(db, fid, user, pid):
    family_access(db, fid, user, lock=True)
    plan, revision = plan_record(db, fid, pid, lock=True)
    return snapshot_json(plan, revision)


def calendar(db, request, fid, user, start_date, end_date, child_id=None, include_cancelled=False):
    from app.v2.children.models import Child
    family, member = family_access(db, fid, user, lock=True)
    if end_date < start_date or (end_date - start_date).days >= 62:
        fail(422, 'VALIDATION_ERROR', '请选择最多 62 天的日期范围')
    if child_id is not None and db.scalar(select(Child.id).where(Child.id == child_id,
            Child.family_id == fid).with_for_update()) is None:
        fail(404, 'NOT_FOUND', '孩子档案不属于当前家庭')
    query = select(OutfitPlan, PlanRevision).join(PlanRevision,
        (PlanRevision.plan_id == OutfitPlan.id) & (PlanRevision.version == OutfitPlan.version)).where(
        OutfitPlan.family_id == fid, OutfitPlan.target_date >= start_date, OutfitPlan.target_date <= end_date)
    if child_id is not None:
        query = query.where(OutfitPlan.child_id == child_id)
    if not include_cancelled:
        query = query.where(OutfitPlan.status == 'selected')
    query = query.order_by(OutfitPlan.target_date, OutfitPlan.child_id, OutfitPlan.sequence, OutfitPlan.id)
    query = query.with_for_update().execution_options(populate_existing=True)
    return {'start_date': start_date.isoformat(), 'end_date': end_date.isoformat(),
        'plans': [snapshot_json(plan, revision) for plan, revision in db.execute(query)],
        'timezone': family.timezone, 'today': local_today(family.timezone, request.app.state.clock()).isoformat(),
        'role': member.role}


def cancel(db, request, fid, user, pid, body, resolve=False):
    family, _ = family_access(db, fid, user, EDITORS, lock=True)
    payload = {'plan_id': str(pid), 'action': 'cancel', **body.model_dump(mode='json')}
    # Check receipt before source version; replay remains readable after a newer revision.
    previous = lookup(db, fid, user.id, 'outfits', body.operation_id)
    if previous is not None:
        if previous.request_hash != digest(payload):
            fail(409, 'IDEMPOTENCY_CONFLICT', '此操作标识已用于不同内容')
        return deepcopy(previous.response)
    plan, revision = plan_record(db, fid, pid, lock=True)
    if resolve:
        return run_operation(db, family, user, 'outfits', body.operation_id, payload, lambda: {
            'operation_id': body.operation_id, 'status': 'completed', 'plan': None,
            'error': {'code': 'NOT_EXECUTED', 'message': '已核实原撤销未执行，请核对最新方案后重试'}})
    def execute():
        check_version(plan.version, body.expected_version)
        if plan.status != 'selected':
            fail(409, 'PLAN_CANCELLED', '此方案已撤销')
        now = request.app.state.clock()
        changed = db.execute(update(OutfitPlan).where(OutfitPlan.id == pid,
            OutfitPlan.version == body.expected_version, OutfitPlan.status == 'selected').values(
                version=body.expected_version + 1, status='cancelled', updated_by=user.id, updated_at=now))
        if changed.rowcount != 1:
            fail(409, 'VERSION_CONFLICT', '家人已更新方案，请核对最新内容')
        db.refresh(plan)
        snapshot = {**deepcopy(revision.snapshot), 'status': 'cancelled', 'version': plan.version,
            'updated_at': now.isoformat() + 'Z', 'cancelled_at': now.isoformat() + 'Z',
            'cancelled_by': user.nickname, 'cancelled_by_id': str(user.id)}
        db.add(PlanRevision(plan_id=plan.id, version=plan.version, snapshot=snapshot,
            created_by=user.id, created_at=now))
        db.execute(delete(Reservation).where(Reservation.plan_id == pid))
        db.flush()
        # Cancelled weak choices cease contributing; explicit opinions remain immutable.
        from app.v2.preferences.models import FeedbackEvent
        owners = set(db.scalars(select(FeedbackEvent.owner_key).where(FeedbackEvent.plan_id == pid)
            .with_for_update()).all())
        for owner in owners:
            profile = preferences.get_profile(db, plan.child_id, owner, lock=True)
            if profile:
                preferences.refresh_learning(db, profile)
        return {'operation_id': body.operation_id, 'status': 'completed', 'plan': snapshot}
    return run_operation(db, family, user, 'outfits', body.operation_id, payload, execute)


def reuse(db, request, fid, user, pid, body):
    from app.v2.outfits.schemas import Draft
    family_access(db, fid, user, EDITORS)
    source, revision = plan_record(db, fid, pid)
    check_version(source.version, body.expected_source_version)
    get_child(db, fid, body.child_id)
    scene = body.scene or revision.snapshot['scene']
    fresh = Draft(child_id=body.child_id, target_date=body.target_date, scene=scene,
        preference_mode=body.preference_mode, designated_member_id=body.designated_member_id,
        draft_id=body.draft_id, action_id=uuid4().hex)
    weather = weather_for(db, request, fid, user, fresh)
    # Weather transport released checkout and locks; recheck authorization and source.
    state = capture(db, fid, user, fresh, weather, lock=True)
    source, revision = plan_record(db, fid, pid, lock=True)
    check_version(source.version, body.expected_source_version)
    original = deepcopy(revision.snapshot)
    current = {g['garment_id']: g for g in state['garments']}
    source_ids = {int(i.get('garment_id') or i['id']) for i in original['main_items'] + original['backup']['items']}
    physical_versions = dict(db.execute(select(Clothing.id, Clothing.version).where(
        Clothing.family_id == fid, Clothing.id.in_(source_ids)).with_for_update()).all())
    def entry(item):
        garment_id = str(item.get('garment_id') or item['id'])
        current_item = current.get(garment_id)
        return {'garment_id': garment_id, 'expected_version': current_item['version'] if current_item else physical_versions.get(int(garment_id), item['version']),
            'replaces_garment_id': item.get('replaces_garment_id')}
    fresh = Draft(**{**fresh.model_dump(), 'main_items': [entry(i) for i in original['main_items']],
        'backup': {'mode': original['backup']['mode'], 'items': [entry(i) for i in original['backup']['items']]}})
    state = capture(db, fid, user, fresh, weather, lock=True)
    review = review_state(state, fresh, user, request.app.state.settings)[0]
    family, member, child = state['family'], state['member'], state['child']
    plans = selected_plans(db, fid, child.id, body.target_date)
    for plan in plans:
        plan['current_warnings'] = current_warnings(db, state, plan)
    context = {'today': local_today(family.timezone, request.app.state.clock()).isoformat(),
        'timezone': family.timezone, 'target_date': body.target_date.isoformat(), 'role': member.role,
        'child': child_json(db, child), 'weather': weather, 'input_version': state['input_version'],
        'preference_subject': state['preference_subject'], 'preference_mode': fresh.preference_mode,
        'designated_member_id': str(fresh.designated_member_id) if fresh.designated_member_id else None,
        'scene': fresh.scene, 'garments': state['garments'], 'occupancy': state['occupancy'],
        'plans': plans, 'suggestion': None}
    draft = fresh.model_dump(mode='json')
    for key in ('child_id', 'designated_member_id', 'target_plan_id', 'recommendation_id'):
        if draft[key] is not None:
            draft[key] = str(draft[key])
    for item in draft['main_items'] + draft['backup']['items']:
        item['garment_id'] = str(item['garment_id'])
        if item['replaces_garment_id'] is not None:
            item['replaces_garment_id'] = str(item['replaces_garment_id'])
    return {'source_plan_id': str(source.id), 'source_version': source.version,
        'draft': draft, 'review': review, 'context': context}
