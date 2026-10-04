from sqlalchemy import select
from app.v2.core.clock import local_today, utcnow
from app.v2.core.errors import fail
from app.v2.families.access import check_version
from app.v2.families.service import receipt
from app.v2.children.models import Child, ChildMeasurement
from app.v2.preferences import service as preferences


def get_child(db, family_id, child_id, lock=False):
    query = select(Child).where(Child.family_id == family_id, Child.id == child_id, Child.archived_at.is_(None))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    child = db.scalar(query)
    if child is None:
        fail(404, 'NOT_FOUND', '孩子档案不存在或已归档')
    return child


def measurement_json(measurement):
    if measurement is None:
        return None
    return {'id': str(measurement.id), 'height_cm': float(measurement.height_cm) if measurement.height_cm is not None else None,
            'weight_kg': float(measurement.weight_kg) if measurement.weight_kg is not None else None,
            'measured_on': measurement.measured_on.isoformat()}


def child_json(db, child):
    measurement = db.scalar(select(ChildMeasurement).where(ChildMeasurement.child_id == child.id)
                            .order_by(ChildMeasurement.measured_on.desc(), ChildMeasurement.id.desc()).limit(1))
    settings = preferences.get_settings(db, child.id)
    profile = preferences.get_profile(db, child.id, 'family')
    return {'id': str(child.id), 'family_id': str(child.family_id), 'nickname': child.nickname,
            'birthday': child.birthday.isoformat() if child.birthday else None,
            'age_months': child.age_months, 'age_recorded_on': child.age_recorded_on.isoformat() if child.age_recorded_on else None,
            'skin_tone': child.skin_tone, 'version': child.version,
            'latest_measurement': measurement_json(measurement),
            'preference_summary': {**preferences.settings_json(settings), 'styles': profile.styles}}


def list_children(db, family_id):
    return [child_json(db, child) for child in db.scalars(select(Child).where(
        Child.family_id == family_id, Child.archived_at.is_(None)).order_by(Child.id))]


def validate_date(value, family, now):
    if value > local_today(family.timezone, now):
        fail(422, 'VALIDATION_ERROR', '日期不能晚于家庭所在地的今天')


def create_child(db, family, user, body, key, now=None):
    def create():
        if body.birthday is not None:
            validate_date(body.birthday, family, now)
        if body.measurement:
            validate_date(body.measurement.measured_on, family, now)
        child = Child(family_id=family.id, **body.model_dump(exclude={'measurement', 'preferences'}),
                      age_recorded_on=local_today(family.timezone, now) if body.age_months is not None else None)
        db.add(child)
        db.flush()
        preferences.create_defaults(db, child, body.preferences)
        if body.measurement:
            db.add(ChildMeasurement(child_id=child.id, **body.measurement.model_dump()))
            db.flush()
        return child_json(db, child)
    return receipt(db, user, 'create_child:' + str(family.id), key, body.model_dump(mode='json'), create)


def update_child(db, family, child, body, now=None):
    check_version(child.version, body.expected_version)
    if body.birthday is not None:
        validate_date(body.birthday, family, now)
    for key, value in body.model_dump(exclude_unset=True, exclude={'expected_version'}).items():
        setattr(child, key, value)
    if body.birthday is not None:
        child.age_months = None
        child.age_recorded_on = None
    elif body.age_months is not None:
        child.birthday = None
        child.age_recorded_on = local_today(family.timezone, now)
    child.version += 1
    db.flush()
    return child_json(db, child)


def archive_child(db, child, expected_version, now=None):
    check_version(child.version, expected_version)
    child.archived_at = now or utcnow()
    child.version += 1
    db.flush()


def add_measurement(db, family, child, user, body, key, now=None):
    def create():
        validate_date(body.measured_on, family, now)
        measurement = ChildMeasurement(child_id=child.id, **body.model_dump())
        db.add(measurement)
        db.flush()
        return measurement_json(measurement)
    return receipt(db, user, 'measurement:' + str(child.id), key, body.model_dump(mode='json'), create)
