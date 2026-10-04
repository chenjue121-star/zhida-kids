"""Fixed age/weather wardrobes exercise the full selected-plan calendar contract."""
from datetime import datetime
from uuid import uuid4

import pytest

from test_b_wardrobe_intake import batch, confirm
from test_c_outfits import plan_body, save


AGES = (0, 6, 12, 24, 36, 60, 83)
WEATHER = {
    'unknown': None,
    'mild': (18, 24),
    'hot': (29, 35),
    'freezing': (-3, 2),
}


def intake_wardrobe(client, root, headers, child_id):
    """Real B confirmation, including unavailable and unknown-fit physical objects."""
    b = batch(client, root, headers, child_id)
    path = root + '/intake/batches/' + b['id']
    garments = []
    definitions = (
        ('婴儿连体衣', 'onesie', 'medium', 'ready', 'fit'),
        ('纯色短袖', 'top', 'thin', 'ready', 'fit'),
        ('纯色长裤', 'bottom', 'thin', 'ready', 'fit'),
        ('厚上衣', 'top', 'thick', 'ready', 'fit'),
        ('厚裤', 'bottom', 'thick', 'ready', 'fit'),
        ('连衣裙', 'dress', 'medium', 'ready', 'fit'),
        ('保暖外套', 'outerwear', 'thick', 'ready', 'fit'),
        ('运动鞋', 'shoes', 'medium', 'ready', 'fit'),
        ('待洗衣物', 'top', 'thin', 'washing', 'fit'),
        ('尚未核对合身', 'onesie', 'medium', 'ready', 'unknown'),
    )
    for name, category, thickness, state, fit in definitions:
        item = client.post(path + '/items', headers=headers, json={
            'client_id': uuid4().hex, 'source': 'manual'}).json()
        response = client.post(path + '/candidates', headers=headers, json={
            'item_id': item['id'], 'client_id': uuid4().hex, 'name': name,
            'category': category, 'colors': ['white'], 'pattern': 'solid',
            'thickness': thickness, 'state': state,
            'owners': [{'child_id': child_id, 'fit': fit}], 'selected': True})
        assert response.status_code == 201, response.text
        result = confirm(client, root, headers, b, [response.json()])
        assert result.status_code == 200, result.text
        garments.append(result.json()['results'][0]['garment'])
    return garments


@pytest.mark.parametrize('age_months', AGES)
@pytest.mark.parametrize('weather_kind', WEATHER)
def test_fixed_zero_to_six_wardrobes_keep_calendar_as_selected_fact(
        client, family_factory, auth, age_months, weather_kind):
    client.app.state.clock = lambda: datetime(2026, 10, 4, 4)
    family, users = family_factory(('admin', 'viewer'))
    root, headers = '/v2/families/' + family['id'], auth(users[0])
    response = client.post(root + '/children', headers=headers, json={
        'nickname': '固定月龄' + str(age_months), 'age_months': age_months})
    assert response.status_code == 201, response.text
    kid = response.json()
    assert kid['latest_measurement'] is None
    intake_wardrobe(client, root, headers, kid['id'])
    temperatures = WEATHER[weather_kind]
    def forecast(payload):
        result = {'target_date': payload['target_date'], 'city': payload['city'],
                  'status': 'known' if temperatures else 'unknown'}
        if temperatures:
            result.update(temp_min=temperatures[0], temp_max=temperatures[1])
        return result
    client.app.state.forecast_provider = forecast
    recommended = client.post(root + '/outfits/recommend', headers=headers, json={
        'child_id': kid['id'], 'target_date': '2026-10-04', 'scene': 'outdoor',
        'preference_mode': 'family', 'draft_id': uuid4().hex, 'request_id': uuid4().hex})
    assert recommended.status_code == 200, recommended.text
    suggestion = recommended.json()
    assert suggestion['items'], suggestion
    assert all(item['state'] == 'ready' and item['fit'] == 'fit' for item in suggestion['items'])
    categories = {item['category'] for item in suggestion['items']}
    if age_months >= 12:
        assert 'shoes' in categories
    if weather_kind == 'freezing':
        assert 'outerwear' in categories
    if weather_kind == 'hot':
        assert all(item['thickness'] != 'thick' for item in suggestion['items'])
    selected, _ = save(client, root, headers, plan_body(
        kid, suggestion['items'], target_date='2026-10-04', scene='outdoor'))
    assert selected.status_code == 200, selected.text
    listing = client.get(root + '/outfits/calendar', headers=auth(users[1]), params={
        'child_id': kid['id'], 'start_date': '2026-10-01', 'end_date': '2026-10-31'})
    assert listing.status_code == 200, listing.text
    assert len(listing.json()['plans']) == 1
    plan = listing.json()['plans'][0]
    assert plan['id'] == selected.json()['plan']['id']
    assert plan['status'] == 'selected'
    assert not {'worn', 'worn_at', 'wear_count', 'last_worn_at'} & plan.keys()
    # Moving the clock cannot invent actual wearing or delete history.
    client.app.state.clock = lambda: datetime(2026, 10, 7, 4)
    later = client.get(root + '/outfits/plans/' + plan['id'], headers=headers)
    assert later.status_code == 200, later.text
    assert later.json()['status'] == 'selected'
    assert later.json()['main_items'] == plan['main_items']


def test_d_full_family_permissions_cover_calendar_cancel_feedback_and_reuse(
        client, family_factory, auth, login):
    family, users = family_factory(('admin', 'editor', 'viewer'))
    root, headers = '/v2/families/' + family['id'], auth(users[0])
    client.app.state.clock = lambda: datetime(2026, 10, 4, 4)
    kid = client.post(root + '/children', headers=headers, json={
        'nickname': '权限回归', 'age_months': 24}).json()
    garments = intake_wardrobe(client, root, headers, kid['id'])
    plan_response, _ = save(client, root, headers, plan_body(
        kid, garments[1:3], target_date='2026-10-04'))
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()['plan']
    detail = root + '/outfits/plans/' + plan['id']
    viewer = auth(users[2])
    assert client.get(detail, headers=viewer).status_code == 200
    assert client.post(detail + '/cancel', headers=viewer, json={
        'expected_version': plan['version'], 'operation_id': uuid4().hex}).status_code == 403
    assert client.post(detail + '/reuse', headers=viewer, json={
        'expected_source_version': plan['version'], 'child_id': kid['id'],
        'target_date': '2026-10-05', 'draft_id': uuid4().hex}).status_code == 403
    assert client.post(root + '/children/' + kid['id'] + '/feedback', headers=viewer, json={
        'event_id': uuid4().hex, 'plan_id': plan['id'], 'plan_version': plan['version'],
        'signal': 'like', 'reason': 'aesthetic', 'styles': ['clean_daily']}).status_code == 403
    outsider = auth(login('D-outsider-' + uuid4().hex))
    assert client.get(detail, headers=outsider).status_code == 404
    calendar = root + '/outfits/calendar?start_date=2026-10-01&end_date=2026-10-31'
    assert client.get(calendar, headers=outsider).status_code == 404
    members = client.get(root + '/members', headers=headers).json()
    editor = next(member for member in members if member['user_id'] == users[1]['user']['id'])
    version = client.get(root, headers=headers).json()['version']
    removed = client.request('DELETE', root + '/members/' + editor['id'], headers=headers,
                             json={'expected_family_version': version})
    assert removed.status_code in (200, 204), removed.text
    assert client.get(detail, headers=auth(users[1])).status_code == 404
