"""Import an explicit legacy export into a rehearsal SQLite database only.

No legacy connection is accepted; remote assets and source diary claims remain
provenance. The caller owns the outer transaction and commits the whole import.
"""
from datetime import date, datetime, time
from hashlib import sha256
import json
import math
from typing import get_args

from sqlalchemy import select

from app.v2.children.models import Child, ChildMeasurement
from app.v2.families.models import Family, Membership
from app.v2.identity.models import User
from app.v2.preferences.models import PreferenceProfile, PreferenceSettings
from app.v2.release.models import LegacySourceRecord
from app.v2.wardrobe.models import ChildClothing, Clothing
from app.v2.wardrobe.schemas import Category, Color, Pattern, Thickness

ENTITIES = ('users', 'children', 'clothing', 'outfit_diaries')
CATEGORIES = {'上衣': 'top', '裤子': 'bottom', '外套': 'outerwear', '连衣裙': 'dress',
              '连体衣': 'onesie', '鞋子': 'shoes', '配饰': 'accessory'}
STATES = {'active': 'ready', 'ready': 'ready', 'washing': 'washing', 'missing': 'missing',
          'removed': 'ready', 'archived': 'ready'}


class LegacyConflict(ValueError):
    """A stable source identifier was previously imported with different content."""


def _id(value):
    if type(value) not in (int, str) or not str(value).isdigit() or int(value) <= 0:
        raise ValueError('Legacy IDs must be positive integer identifiers')
    value = str(int(value))
    if len(value) > 128:
        raise ValueError('Legacy source ID is too long')
    return value


def _text(value, maximum, default=''):
    value = default if value is None else value
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError('Legacy text is invalid or requires manual review')
    return value


def _date(value):
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise ValueError('Legacy date requires manual review') from None


def _measurement(value):
    if value is None or value == '':
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 999999.99:
        raise ValueError('Legacy measurement requires manual review')
    rounded = round(value, 2)
    if rounded <= 0:
        raise ValueError('Legacy measurement requires manual review')
    return rounded


def _hash(payload):
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                             allow_nan=False).encode()).hexdigest()


def _prepare(source, namespace, existing):
    if not isinstance(namespace, str) or not namespace.strip() or len(namespace) > 64:
        raise ValueError('A stable nonempty source namespace of at most 64 characters is required')
    if not isinstance(source, dict) or source.get('schema_version') != 1:
        raise ValueError('Legacy export schema_version must be 1')
    recorded_on = _date(source.get('recorded_on'))
    prepared, keys = [], set()
    for entity in ENTITIES:
        rows = source.get(entity)
        if not isinstance(rows, list):
            raise ValueError('Legacy export must explicitly include all four source tables')
        for raw in rows:
            if not isinstance(raw, dict):
                raise ValueError('Legacy rows must be objects')
            sid = _id(raw.get('id'))
            key = (entity, sid)
            if key in keys:
                raise ValueError('Duplicate legacy source ID')
            keys.add(key)
            payload_hash = _hash(raw)
            if key in existing and existing[key].payload_hash != payload_hash:
                raise LegacyConflict('Source payload changed; manual reconciliation is required')
            values = {}
            if entity == 'users':
                openid = _text(raw.get('openid'), 128)
                if not openid.strip():
                    raise ValueError('Legacy openid is required')
                values = {'openid': 'legacy:' + sha256((namespace + '\0' + openid).encode()).hexdigest(),
                          'nickname': _text(raw.get('nickname'), 80), 'city': _text(raw.get('city'), 120)}
            elif entity == 'children':
                values = {'user_id': _id(raw.get('user_id')), 'nickname': _text(raw.get('nickname'), 80),
                          'birthday': _date(raw.get('birthday')), 'height': _measurement(raw.get('height')),
                          'weight': _measurement(raw.get('weight')),
                          'skin_tone': raw.get('skin_tone') if raw.get('skin_tone') in ('light', 'medium', 'deep') else None}
                if not values['nickname'].strip():
                    raise ValueError('Legacy child nickname is required')
            elif entity == 'clothing':
                category = CATEGORIES.get(raw.get('type'), raw.get('type'))
                status = raw.get('status', 'active')
                if category not in get_args(Category) or status not in STATES:
                    raise ValueError('Legacy clothing category/state requires manual review')
                color = raw.get('main_color')
                values = {'child_id': _id(raw.get('child_id')), 'category': category,
                          'name': _text(raw.get('sub_type') or category, 80),
                          'colors': [color if color in get_args(Color) else 'unknown'],
                          'pattern': raw.get('pattern') if raw.get('pattern') in get_args(Pattern) else 'unknown',
                          'thickness': raw.get('thickness') if raw.get('thickness') in get_args(Thickness) else 'unknown',
                          'state': STATES[status], 'archived_at': datetime.combine(recorded_on, time()) if status in ('removed', 'archived') else None}
            else:
                values = {'child_id': _id(raw.get('child_id')), 'date': _date(raw.get('date'))}
                if not isinstance(raw.get('clothing_ids', []), list):
                    raise ValueError('Legacy diary clothing_ids must be a list')
                for clothing_id in raw.get('clothing_ids', []):
                    _id(clothing_id)
            prepared.append((entity, sid, raw, payload_hash, values))
    known = keys | set(existing)
    for entity, _, _, _, values in prepared:
        if entity == 'children' and ('users', values['user_id']) not in known:
            raise ValueError('Legacy child references an absent user')
        if entity in ('clothing', 'outfit_diaries') and ('children', values['child_id']) not in known:
            raise ValueError('Legacy row references an absent child')
    user_identities = [values['openid'] for entity, _, _, _, values in prepared if entity == 'users']
    if len(set(user_identities)) != len(user_identities):
        raise ValueError('Duplicate legacy openid requires manual review')
    return recorded_on, prepared


def import_legacy(db, source, namespace):
    if db.get_bind().dialect.name != 'sqlite':
        raise ValueError('Legacy import is restricted to isolated SQLite rehearsals')
    existing = {(row.entity, row.source_id): row for row in db.scalars(select(LegacySourceRecord).where(
        LegacySourceRecord.source_namespace == namespace))}
    recorded_on, prepared = _prepare(source, namespace, existing)
    counts = {'imported': 0, 'reused': 0, 'remote_assets_fetched': 0, 'legacy_diaries_converted': 0}
    # sqlite3 legacy transaction mode does not BEGIN on SELECT; without an
    # explicit BEGIN, releasing the first SAVEPOINT commits outside the caller.
    connection = db.connection()
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql('BEGIN')
    with db.begin_nested():
        for entity, sid, raw, payload_hash, values in prepared:
            key = (entity, sid)
            if key in existing:
                counts['reused'] += 1
                continue
            target = None
            if entity == 'users':
                target = User(openid=values['openid'], nickname=values['nickname'])
                db.add(target)
                db.flush()
                family = Family(name=(values['nickname'] or '导入演练')[:72] + '的家庭', city=values['city'],
                                personal_owner_id=target.id, created_by=target.id)
                db.add(family)
                db.flush()
                db.add(Membership(family_id=family.id, user_id=target.id, role='admin'))
            elif entity == 'children':
                user_id = existing[('users', values['user_id'])].target_id
                family = db.scalar(select(Family).where(Family.personal_owner_id == user_id))
                target = Child(family_id=family.id, nickname=values['nickname'], birthday=values['birthday'],
                               skin_tone=values['skin_tone'])
                db.add(target)
                db.flush()
                if values['height'] is not None or values['weight'] is not None:
                    db.add(ChildMeasurement(child_id=target.id, height_cm=values['height'], weight_kg=values['weight'],
                                            measured_on=recorded_on))
                db.add(PreferenceSettings(child_id=target.id))
                db.add(PreferenceProfile(child_id=target.id, owner_key='family', styles=[]))
            elif entity == 'clothing':
                child = db.get(Child, existing[('children', values['child_id'])].target_id)
                family = db.get(Family, child.family_id)
                target = Clothing(family_id=family.id, created_by=family.created_by, name=values['name'],
                                  category=values['category'], colors=values['colors'], pattern=values['pattern'],
                                  thickness=values['thickness'], state=values['state'], archived_at=values['archived_at'])
                db.add(target)
                db.flush()
                db.add(ChildClothing(clothing_id=target.id, child_id=child.id, fit='unknown'))
            record = LegacySourceRecord(source_namespace=namespace, entity=entity, source_id=sid,
                                        payload_hash=payload_hash, payload=raw,
                                        target_table=target.__tablename__ if target else None,
                                        target_id=target.id if target else None)
            db.add(record)
            db.flush()
            existing[key] = record
            counts['imported'] += 1
    return counts
