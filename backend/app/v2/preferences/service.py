from copy import deepcopy
from sqlalchemy import select
from pydantic import ValidationError
from app.v2.core.errors import fail
from app.v2.families.access import check_version
from app.v2.families.models import Membership
from app.v2.preferences.models import PreferenceProfile, PreferenceSettings, FeedbackEvent
from app.v2.preferences.schemas import InitialPreferences


def settings_json(settings):
    return {'mode': settings.mode,
            'designated_member_id': str(settings.designated_member_id) if settings.designated_member_id is not None else None,
            'thermal_preference': settings.thermal_preference, 'fit_preference': settings.fit_preference,
            'avoid_high_neck': settings.avoid_high_neck, 'version': settings.version}


def profile_json(profile):
    styles = profile.styles if profile else []
    tags = profile.inferred_tags if profile else []
    weights = {tag['style']: tag['weight'] for tag in tags}
    weights.update({style: 1 for style in styles})
    return {'styles': list(styles), 'version': profile.version if profile else 0,
            'inferred_tags': deepcopy(tags), 'learning_version': profile.learning_version if profile else 0,
            'effective_weights': weights}


def validate_designated(db, family_id, member_id):
    if member_id is not None:
        member = db.scalar(select(Membership).where(Membership.id == member_id,
                                                   Membership.family_id == family_id,
                                                   Membership.status == 'active').with_for_update())
        if member is None:
            fail(422, 'INVALID_MEMBER', '请选择本家庭的有效成员')


def create_defaults(db, child, preferences):
    validate_designated(db, child.family_id, preferences.designated_member_id)
    db.add(PreferenceSettings(child_id=child.id, **preferences.model_dump(exclude={'styles'})))
    db.add(PreferenceProfile(child_id=child.id, owner_key='family', styles=preferences.styles))
    db.flush()


def get_settings(db, child_id, lock=False):
    query = select(PreferenceSettings).where(PreferenceSettings.child_id == child_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.execute(query).scalar_one()


def update_settings(db, child, body):
    # Family is already locked before resolving children, settings or members.
    settings = get_settings(db, child.id, lock=True)
    check_version(settings.version, body.expected_version)
    values = {key: value for key, value in settings_json(settings).items() if key != 'version'}
    values.update(body.model_dump(exclude_unset=True, exclude={'expected_version'}))
    try:
        validated = InitialPreferences(**values)
    except ValidationError:
        fail(422, 'VALIDATION_ERROR', '仅指定成员模式需要选择成员，请检查偏好依据')
    validate_designated(db, child.family_id, validated.designated_member_id)
    for key, value in validated.model_dump(exclude={'styles'}).items():
        setattr(settings, key, value)
    settings.version += 1
    db.flush()
    return settings_json(settings)


def get_profile(db, child_id, owner_key, lock=False):
    query = select(PreferenceProfile).where(PreferenceProfile.child_id == child_id,
                                           PreferenceProfile.owner_key == owner_key)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def put_profile(db, child, member, target, body):
    owner = 'family' if target == 'family' else 'member:' + str(member.id)
    profile = get_profile(db, child.id, owner, lock=True)
    check_version(profile.version if profile else 0, body.expected_version)
    if profile is None:
        profile = PreferenceProfile(child_id=child.id, owner_key=owner, membership_id=member.id,
                                    styles=body.styles, version=1)
        db.add(profile)
    else:
        suppress(db, profile, set(profile.styles) - set(body.styles))
        profile.styles = body.styles
        profile.version += 1
        refresh_learning(db, profile)
    db.flush()
    return profile_json(profile)


LEARNING_RULE_VERSION = 'aesthetic-evidence-v1'
STYLE_KEYS = ('clean_daily', 'sporty', 'soft_natural', 'playful_print')


def ensure_profile(db, child_id, owner, member_id):
    profile = get_profile(db, child_id, owner, lock=True)
    if profile is None:
        profile = PreferenceProfile(child_id=child_id, owner_key=owner,
            membership_id=member_id if owner != 'family' else None, styles=[], version=1,
            inferred_tags=[], suppression_cutoffs={}, learning_version=0)
        db.add(profile)
        db.flush()
    return profile


def styles_from_snapshot(snapshot):
    # Describe observed categorical features, never use unavailable/fit reasons.
    items = [i for i in snapshot['main_items'] if i.get('category') != 'shoes']
    result = []
    if items and all(i.get('pattern') == 'solid' for i in items):
        result.append('clean_daily')
    if any(i.get('pattern') in ('print', 'dots') for i in items):
        result.append('playful_print')
    if items and all(set(i.get('colors') or []) and set(i['colors']) <= {'white', 'beige', 'brown', 'green'} for i in items):
        result.append('soft_natural')
    if snapshot['scene'] == 'sport':
        result.append('sporty')
    return result


def event_json(row):
    return {'event_id': row.event_id, 'actor_id': str(row.actor_id), 'child_id': str(row.child_id),
        'membership_id': str(row.membership_id), 'owner_key': row.owner_key,
        'attribution': 'family' if row.owner_key == 'family' else 'actor_personal',
        'source_subject': deepcopy(row.source_subject), 'plan_id': str(row.plan_id),
        'plan_version': row.plan_version, 'signal': row.signal, 'reason': row.reason,
        'styles': list(row.styles), 'created_at': row.created_at.isoformat() + 'Z'}


def suppress(db, profile, styles):
    if not styles:
        return
    # Locked row reads see the latest committed facts under MySQL repeatable-read.
    ids = db.scalars(select(FeedbackEvent.id).where(FeedbackEvent.child_id == profile.child_id,
        FeedbackEvent.owner_key == profile.owner_key).order_by(FeedbackEvent.id).with_for_update()).all()
    cutoff = max(ids, default=0)
    profile.suppression_cutoffs = {**profile.suppression_cutoffs,
        **{style: max(cutoff, profile.suppression_cutoffs.get(style, 0)) for style in styles}}


def refresh_learning(db, profile):
    from app.v2.outfits.models import OutfitPlan
    rows = db.execute(select(FeedbackEvent, OutfitPlan.status, OutfitPlan.version).join(OutfitPlan,
        OutfitPlan.id == FeedbackEvent.plan_id).where(FeedbackEvent.child_id == profile.child_id,
        FeedbackEvent.owner_key == profile.owner_key).order_by(FeedbackEvent.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    latest_selections = {}
    for row, status, plan_version in rows:
        if row.signal == 'selection' and status == 'selected' and row.plan_version == plan_version:
            latest_selections[row.plan_id] = row.id
    tags = []
    for style in STYLE_KEYS:
        cutoff = profile.suppression_cutoffs.get(style, 0)
        # One latest explicit opinion per physical plan; selection is a weak fallback.
        evidence = {}
        for row, status, plan_version in rows:
            if row.id <= cutoff or style not in row.styles:
                continue
            if row.signal == 'selection' and row.id != latest_selections.get(row.plan_id):
                continue
            if row.reason not in ('aesthetic', 'selection'):
                continue
            old = evidence.get(row.plan_id)
            if old is None or row.signal != 'selection' or old.signal == 'selection':
                evidence[row.plan_id] = row
        positive = [r for r in evidence.values() if r.signal != 'dislike']
        negative = [r for r in evidence.values() if r.signal == 'dislike']
        agreeing = positive if len(positive) > len(negative) else negative
        if len(agreeing) < 3 or len(positive) == len(negative):
            continue
        agreeing.sort(key=lambda r: r.id)
        direction = 'like' if agreeing is positive else 'dislike'
        strength = sum(.25 if r.signal == 'selection' else 1 for r in agreeing)
        weight = round(min(.5, strength / 6), 4) * (1 if direction == 'like' else -1)
        tags.append({'style': style, 'direction': direction, 'weight': weight,
            'evidence_count': len(agreeing), 'evidence': [{k: event_json(r)[k] for k in
                ('event_id', 'plan_id', 'plan_version', 'signal', 'reason', 'created_at')} for r in agreeing[-20:]],
            'rule_version': LEARNING_RULE_VERSION})
    if tags != profile.inferred_tags:
        profile.inferred_tags = tags
        profile.learning_version += 1
        profile.version += 1
    db.flush()
    return profile


def record_event(db, family, child, member, user, revision, event_id, signal, reason, styles, request_hash, now):
    basis = revision.snapshot['preference_subject']
    owner = 'family' if basis['mode'] == 'family' else 'member:' + str(member.id)
    profile = ensure_profile(db, child.id, owner, member.id)
    row = FeedbackEvent(family_id=family.id, child_id=child.id, actor_id=user.id,
        membership_id=member.id, owner_key=owner, event_id=event_id, request_hash=request_hash,
        plan_id=revision.plan_id, plan_version=revision.version, revision_id=revision.id,
        source_subject=deepcopy(basis), signal=signal, reason=reason,
        styles=list(styles), created_at=now)
    db.add(row)
    db.flush()
    refresh_learning(db, profile)
    if signal == 'selection':
        # Editing can change the preference owner; retire the old owner's weak
        # evidence in the same transaction without moving explicit opinions.
        owners = set(db.scalars(select(FeedbackEvent.owner_key).where(
            FeedbackEvent.plan_id == revision.plan_id).with_for_update()).all())
        for old_owner in owners - {owner}:
            old_profile = get_profile(db, child.id, old_owner, lock=True)
            if old_profile:
                refresh_learning(db, old_profile)
    return {'event': event_json(row), 'profile': profile_json(profile), 'target': 'family' if owner == 'family' else 'me'}


def submit_feedback(db, family, child, member, user, body, now):
    from app.v2.outfits.models import OutfitPlan, PlanRevision
    from app.v2.recognition.operations import digest
    request_hash = digest(body.model_dump(mode='json'))
    previous = db.scalar(select(FeedbackEvent).where(FeedbackEvent.family_id == family.id,
        FeedbackEvent.actor_id == user.id, FeedbackEvent.event_id == body.event_id)
        .with_for_update().execution_options(populate_existing=True))
    if previous:
        if previous.request_hash != request_hash or previous.child_id != child.id:
            fail(409, 'IDEMPOTENCY_CONFLICT', '此反馈标识已用于不同内容')
        return {'event': event_json(previous), 'profile': profile_json(get_profile(db, child.id, previous.owner_key, lock=True)),
                'target': 'family' if previous.owner_key == 'family' else 'me'}
    revision = db.scalar(select(PlanRevision).join(OutfitPlan, OutfitPlan.id == PlanRevision.plan_id).where(
        OutfitPlan.id == body.plan_id, OutfitPlan.family_id == family.id, OutfitPlan.child_id == child.id,
        PlanRevision.version == body.plan_version).with_for_update().execution_options(populate_existing=True))
    if revision is None:
        fail(404, 'NOT_FOUND', '原方案版本不属于当前孩子或家庭')
    return record_event(db, family, child, member, user, revision, body.event_id, body.signal,
        body.reason, body.styles or styles_from_snapshot(revision.snapshot), request_hash, now)


def tag_action(db, child, member, target, style, body):
    owner = 'family' if target == 'family' else 'member:' + str(member.id)
    profile = get_profile(db, child.id, owner, lock=True)
    check_version(profile.version if profile else 0, body.expected_version)
    profile = profile or ensure_profile(db, child.id, owner, member.id)
    if body.action == 'accept':
        if any(t['style'] == style and t['direction'] == 'dislike' for t in profile.inferred_tags):
            fail(422, 'NEGATIVE_TAG_ACCEPT_UNSUPPORTED', '不喜欢的推断不能采纳为喜欢的风格；可以删除或明确修改风格')
        if style not in profile.styles:
            profile.styles = [*profile.styles, style]
    else:
        suppress(db, profile, {style})
        profile.styles = [s for s in profile.styles if s != style]
    profile.version += 1
    refresh_learning(db, profile)
    db.flush()
    return profile_json(profile)
