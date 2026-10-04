from app.v2.recognition.operations import digest
from app.v2.outfits.rules import RULE_VERSION

WEATHER_FIELDS = ('status', 'target_date', 'city', 'lat', 'lon', 'temp_min', 'temp_max',
                  'condition', 'condition_code', 'humidity', 'precipitation_probability', 'wind_speed')


def effective_weather(weather):
    return {key: weather.get(key) for key in WEATHER_FIELDS}


def input_version(family, child, measurement, subject, comfort, garments, occupancy, body, weather):
    draft = body.model_dump(mode='json')
    backup = draft.get('backup', {'mode': 'none', 'items': []})
    backup = {**backup, 'items': sorted(backup['items'], key=lambda i: int(i['garment_id']))}
    return digest({'family': [str(family.id), family.version, family.timezone],
        'child': [str(child.id), child.version, child.birthday.isoformat() if child.birthday else None,
                  child.age_months, child.age_recorded_on.isoformat() if child.age_recorded_on else None],
        'measurement': measurement, 'preference_subject': subject, 'comfort': comfort,
        'garments': [[g['garment_id'], g['version'], g['fit'], g['state'], g['archived_at']] for g in garments],
        'occupancy': occupancy, 'scene': body.scene, 'target_date': body.target_date.isoformat(),
        'locked_ids': sorted(map(str, body.locked_ids)), 'excluded_ids': sorted(map(str, body.excluded_ids)),
        'main_items': sorted(draft.get('main_items', []), key=lambda i: int(i['garment_id'])),
        'backup': backup,
        'exclude_combination': sorted(map(str, draft.get('exclude_combination', []))),
        'weather': effective_weather(weather), 'rule_version': RULE_VERSION})


def draft_binding(body):
    payload = body.model_dump(mode='json', include={'child_id', 'target_date', 'scene', 'preference_mode',
        'designated_member_id', 'draft_id', 'action_id', 'main_items', 'backup', 'target_plan_id',
        'expected_version', 'locked_ids', 'excluded_ids', 'city', 'lat', 'lon'})
    return digest(payload)
