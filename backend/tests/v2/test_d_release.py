"""Offline release evidence uses synthetic data and new SQLite directories only."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import json

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session


FIXTURE = Path(__file__).parent / 'fixtures' / 'phase_d_legacy_wardrobe.json'


def release_modules():
    assert importlib.util.find_spec('app.v2.release') is not None, 'Phase D release tooling is required'
    from app.v2.release import legacy, models, rehearsal
    return legacy, models, rehearsal


def dataset():
    return json.loads(FIXTURE.read_text())


def destination(tmp_path):
    release_modules()
    from app.v2.core.database import load_metadata
    engine = create_engine('sqlite:///' + str(tmp_path / 'destination.sqlite'))
    load_metadata().create_all(engine)
    return engine


def test_legacy_mapping_schema_and_source_only_diaries(tmp_path):
    legacy, models, _ = release_modules()
    from app.v2.children.models import Child, ChildMeasurement
    from app.v2.families.models import Family, Membership
    from app.v2.outfits.models import OutfitPlan
    from app.v2.preferences.models import FeedbackEvent, PreferenceProfile
    from app.v2.wardrobe.models import ChildClothing, Clothing
    engine = destination(tmp_path)
    with Session(engine) as db, db.begin():
        result = legacy.import_legacy(db, dataset(), 'synthetic-release-v1')
        assert result['imported'] == 31
        assert db.scalar(select(func.count()).select_from(Family)) == 1
        assert db.scalar(select(func.count()).select_from(Membership).where(Membership.role == 'admin')) == 1
        assert db.scalar(select(func.count()).select_from(Child)) == 7
        assert db.scalar(select(func.count()).select_from(ChildMeasurement)) == 1
        assert db.scalar(select(func.count()).select_from(Clothing)) == 21
        assert set(db.scalars(select(ChildClothing.fit))) == {'unknown'}
        assert db.scalar(select(func.count()).select_from(OutfitPlan)) == 0
        assert db.scalar(select(func.count()).select_from(FeedbackEvent)) == 0
        assert all(p.styles == [] and p.inferred_tags == [] for p in db.scalars(select(PreferenceProfile)))
        diaries = db.scalars(select(models.LegacySourceRecord).where(models.LegacySourceRecord.entity == 'outfit_diaries')).all()
        assert len(diaries) == 2 and all(row.target_id is None and row.target_table is None for row in diaries)
        assert diaries[0].payload['rating'] == 5
        clothes = db.scalars(select(Clothing)).all()
        assert all(g.asset_id is None for g in clothes)
        assert {g.state for g in clothes} == {'ready', 'washing', 'missing'}
        assert sum(g.archived_at is not None for g in clothes) == 1
        assert result['remote_assets_fetched'] == 0
    engine.dispose()


def test_source_provenance_is_immutable_in_application_sessions(tmp_path):
    legacy, models, _ = release_modules()
    engine = destination(tmp_path)
    with Session(engine) as db, db.begin():
        legacy.import_legacy(db, dataset(), 'immutable')
    with Session(engine) as db:
        row = db.scalar(select(models.LegacySourceRecord))
        row.payload_hash = '0' * 64
        with pytest.raises(ValueError, match='immutable'):
            db.flush()
        db.rollback()
        db.delete(db.scalar(select(models.LegacySourceRecord)))
        with pytest.raises(ValueError, match='immutable'):
            db.flush()
    engine.dispose()


def test_reimport_is_idempotent_and_namespace_separates_source_ids(tmp_path):
    legacy, models, _ = release_modules()
    from app.v2.identity.models import User
    engine = destination(tmp_path)
    with Session(engine) as db, db.begin():
        legacy.import_legacy(db, dataset(), 'source-one')
        repeat = legacy.import_legacy(db, dataset(), 'source-one')
        assert repeat['imported'] == 0 and repeat['reused'] == 31
        legacy.import_legacy(db, dataset(), 'source-two')
        assert db.scalar(select(func.count()).select_from(models.LegacySourceRecord)) == 62
        users = db.scalars(select(User)).all()
        assert len(users) == 2 and users[0].openid != users[1].openid
        assert all(u.openid.startswith('legacy:') and 'synthetic-parent' not in u.openid for u in users)
    engine.dispose()


def test_changed_source_conflict_rolls_back_new_rows(tmp_path):
    legacy, models, _ = release_modules()
    from app.v2.identity.models import User
    engine = destination(tmp_path)
    with Session(engine) as db, db.begin():
        legacy.import_legacy(db, dataset(), 'source-one')
        altered = deepcopy(dataset())
        altered['users'].insert(0, {'id': 999, 'openid': 'new-source-parent', 'nickname': 'new'})
        altered['clothing'][-1]['main_color'] = 'red'
        with pytest.raises(legacy.LegacyConflict, match='changed'):
            legacy.import_legacy(db, altered, 'source-one')
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(models.LegacySourceRecord)) == 31
    engine.dispose()


def test_successful_import_stays_inside_callers_outer_transaction(tmp_path):
    legacy, models, _ = release_modules()
    engine = destination(tmp_path)
    with Session(engine) as db:
        legacy.import_legacy(db, dataset(), 'rolled-back')
        db.rollback()
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(models.LegacySourceRecord)) == 0
    engine.dispose()


@pytest.mark.parametrize('change', ['duplicate', 'orphan', 'bad_date', 'bad_category', 'bad_state'])
def test_invalid_source_never_partially_imports(tmp_path, change):
    legacy, models, _ = release_modules()
    source = dataset()
    if change == 'duplicate':
        source['children'].append(deepcopy(source['children'][0]))
    elif change == 'orphan':
        source['clothing'][0]['child_id'] = 999
    elif change == 'bad_date':
        source['children'][0]['birthday'] = 'tomorrow'
    elif change == 'bad_category':
        source['clothing'][0]['type'] = 'unreviewed-type'
    else:
        source['clothing'][0]['status'] = 'unreviewed-state'
    engine = destination(tmp_path)
    with Session(engine) as db, db.begin():
        with pytest.raises(ValueError):
            legacy.import_legacy(db, source, 'invalid')
        assert db.scalar(select(func.count()).select_from(models.LegacySourceRecord)) == 0
    engine.dispose()


def test_fixed_wardrobe_covers_zero_to_six_years_and_source_urls_are_provenance(tmp_path):
    legacy, models, _ = release_modules()
    from app.v2.children.models import Child
    from app.v2.outfits.service import age_months
    from datetime import date
    engine = destination(tmp_path)
    with Session(engine) as db, db.begin():
        legacy.import_legacy(db, dataset(), 'age-matrix')
        ages = sorted(age_months(c, date(2026, 10, 4)) for c in db.scalars(select(Child)))
        assert ages == [0, 6, 12, 24, 48, 72, 83]
        row = db.scalar(select(models.LegacySourceRecord).where(models.LegacySourceRecord.entity == 'clothing', models.LegacySourceRecord.source_id == '1'))
        assert row.payload['photo_url'] == 'https://unfetched.example.invalid/legacy/one.jpg'
        assert row.payload['wear_count'] == 17
    engine.dispose()


def test_fixed_wardrobe_real_http_multi_child_weather_and_viewer_permissions(tmp_path):
    from datetime import datetime
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from app.v2.core.config import V2Settings
    from app.v2.main import create_app
    from app.v2.children.models import Child
    from app.v2.families.models import Family, Membership
    from app.v2.identity.models import User
    from app.v2.wardrobe.models import ChildClothing, Clothing
    legacy, _, _ = release_modules()
    engine = destination(tmp_path)
    with Session(engine) as db, db.begin():
        legacy.import_legacy(db, dataset(), 'fixed-http')
        parent = db.scalar(select(User))
        code = parent.openid
        family = db.scalar(select(Family))
        fid = family.id
        kids = list(db.scalars(select(Child).order_by(Child.id)))
        kid_ids = [c.id for c in kids]
        viewer = User(openid='synthetic-viewer')
        db.add(viewer)
        db.flush()
        db.add(Membership(family_id=fid, user_id=viewer.id, role='viewer'))
    settings = V2Settings(_env_file=None, database_url='sqlite://', jwt_secret='test-fixed-http-secret-at-least-32-characters',
                          env='test', private_storage_dir=str(tmp_path / 'media'),
                          recognition_provider='disabled', outfit_provider='disabled')
    app = create_app(settings, engine, lambda code: {'openid': code})
    app.state.clock = lambda: datetime(2026, 10, 4, 8)
    forecast = {'status': 'unknown'}
    app.state.forecast_provider = lambda payload: {**forecast, 'target_date': payload['target_date']}
    with TestClient(app) as client:
        token = client.post('/v2/auth/wechat-login', json={'code': code}).json()['token']
        headers = {'Authorization': 'Bearer ' + token}
        root = f'/v2/families/{fid}'

        def recommend(cid):
            response = client.post(root + '/outfits/recommend', headers=headers, json={
                'child_id': str(cid), 'target_date': '2026-10-04', 'scene': 'outdoor',
                'preference_mode': 'family', 'draft_id': uuid4().hex, 'request_id': uuid4().hex})
            assert response.status_code == 200, response.text
            return response.json()

        assert all(not recommend(cid)['items'] for cid in kid_ids)
        # Explicit synthetic parent review, through the production owners API.
        listing = client.get(root + '/garments', headers=headers, params={'limit': 100}).json()['items']
        for garment in listing:
            reviewed = client.put(root + '/garments/' + garment['id'] + '/owners', headers=headers,
                                  json={'expected_version': garment['version'], 'owners': [
                                      {'child_id': owner['child_id'], 'fit': 'fit'} for owner in garment['owners']]})
            assert reviewed.status_code == 200, reviewed.text
        with Session(engine) as db:
            owners = {}
            for relation in db.scalars(select(ChildClothing)):
                owners.setdefault(relation.child_id, set()).add(str(relation.clothing_id))
        for cid in kid_ids:
            result = recommend(cid)
            assert result['items']
            assert {item['garment_id'] for item in result['items']} <= owners[cid]
            assert all(item['state'] == 'ready' and item['fit'] == 'fit' for item in result['items'])
        forecast.update(status='known', temp_min=4, temp_max=8)
        assert recommend(kid_ids[3])['items'] and recommend(kid_ids[5])['items']
        assert not recommend(kid_ids[0])['items']
        forecast.update(status='known', temp_min=29, temp_max=34)
        assert all(item['category'] != 'outerwear' for item in recommend(kid_ids[3])['items'])
        # Malformed/nonfinite upstream temperatures become unknown, with no fake forecast.
        forecast.update(status='known', temp_min=float('nan'), temp_max=34)
        context = client.get(root + '/outfits/context', headers=headers,
                             params={'child_id': kid_ids[3], 'date_mode': 'tomorrow'}).json()
        assert context['weather']['status'] == 'unknown' and context['target_date'] == '2026-10-05'
        viewer_token = client.post('/v2/auth/wechat-login', json={'code': 'synthetic-viewer'}).json()['token']
        viewer_headers = {'Authorization': 'Bearer ' + viewer_token}
        assert client.get(root + '/garments', headers=viewer_headers).status_code == 200
        blocked = client.post(root + '/outfits/recommend', headers=viewer_headers, json={
            'child_id': kid_ids[0], 'target_date': '2026-10-04', 'scene': 'daily',
            'preference_mode': 'family', 'draft_id': uuid4().hex, 'request_id': uuid4().hex})
        assert blocked.status_code == 403
    engine.dispose()


def test_backup_restores_bytes_rows_and_detects_corruption(tmp_path):
    _, _, rehearsal = release_modules()
    source = tmp_path / 'source.sqlite'
    engine = create_engine('sqlite:///' + str(source))
    with engine.begin() as db:
        db.execute(text('CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT)'))
        db.execute(text("INSERT INTO sample VALUES (1, 'source')"))
    engine.dispose()
    media = tmp_path / 'media'
    (media / 'family').mkdir(parents=True)
    (media / 'family' / 'image.bin').write_bytes(b'private-media-bytes')
    manifest = rehearsal.backup_bundle(source, media, tmp_path / 'backup')
    assert manifest['schema_version'] == 1
    restore = rehearsal.restore_bundle(tmp_path / 'backup', tmp_path / 'restore')
    assert (Path(restore['media_dir']) / 'family/image.bin').read_bytes() == b'private-media-bytes'
    assert rehearsal.database_fingerprint(source) == rehearsal.database_fingerprint(Path(restore['database_path']))
    assert (tmp_path / 'backup' / 'database.sqlite').stat().st_mode & 0o777 == 0o600
    (tmp_path / 'backup' / 'media/family/image.bin').write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash'):
        rehearsal.restore_bundle(tmp_path / 'backup', tmp_path / 'corrupt-restore')
    assert not (tmp_path / 'corrupt-restore').exists()


def test_guard_refuses_existing_output_symlinks_and_restore_drift(tmp_path):
    _, _, rehearsal = release_modules()
    source = tmp_path / 'source.sqlite'
    engine = create_engine('sqlite:///' + str(source))
    with engine.begin() as db:
        db.execute(text('CREATE TABLE sample (id INTEGER)'))
    engine.dispose()
    media = tmp_path / 'media'
    media.mkdir()
    existing = tmp_path / 'existing'
    existing.mkdir()
    with pytest.raises(ValueError, match='new'):
        rehearsal.backup_bundle(source, media, existing)
    (media / 'escape').symlink_to(source)
    with pytest.raises(ValueError, match='symlink'):
        rehearsal.backup_bundle(source, media, tmp_path / 'unsafe')
    (media / 'escape').unlink()
    rehearsal.backup_bundle(source, media, tmp_path / 'backup')
    restore = rehearsal.restore_bundle(tmp_path / 'backup', tmp_path / 'restore')
    engine = create_engine('sqlite:///' + restore['database_path'])
    with engine.begin() as db:
        db.execute(text('INSERT INTO sample VALUES (9)'))
    engine.dispose()
    with pytest.raises(ValueError, match='drift'):
        rehearsal.verify_restored(tmp_path / 'backup', tmp_path / 'restore')


def test_backup_fingerprint_detects_index_changes_and_private_directory_modes(tmp_path):
    _, _, rehearsal = release_modules()
    source = tmp_path / 'source.sqlite'
    engine = create_engine('sqlite:///' + str(source))
    with engine.begin() as db:
        db.execute(text('CREATE TABLE sample (id INTEGER)'))
    engine.dispose()
    before = rehearsal.database_fingerprint(source)
    engine = create_engine('sqlite:///' + str(source))
    with engine.begin() as db:
        db.execute(text('CREATE INDEX sample_id ON sample(id)'))
    engine.dispose()
    assert before != rehearsal.database_fingerprint(source)
    media = tmp_path / 'media'
    (media / 'family' / 'nested').mkdir(parents=True)
    (media / 'family' / 'nested' / 'image.bin').write_bytes(b'bytes')
    rehearsal.backup_bundle(source, media, tmp_path / 'backup')
    assert all(p.stat().st_mode & 0o777 == 0o700 for p in (tmp_path / 'backup').rglob('*') if p.is_dir())


def test_real_source_is_refused_without_creating_output(tmp_path):
    _, _, rehearsal = release_modules()
    source = dataset()
    source['synthetic'] = False
    path = tmp_path / 'real-export.json'
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match='synthetic'):
        rehearsal.run_rehearsal(path, tmp_path / 'run')
    assert not (tmp_path / 'run').exists()


def test_corrupted_database_and_nested_restore_preserve_source(tmp_path):
    _, _, rehearsal = release_modules()
    corrupted = tmp_path / 'corrupt.sqlite'
    corrupted.write_bytes(b'not a SQLite database')
    media = tmp_path / 'media'
    media.mkdir()
    with pytest.raises(ValueError, match='integrity'):
        rehearsal.backup_bundle(corrupted, media, tmp_path / 'backup')
    assert not (tmp_path / 'backup').exists()
    source = tmp_path / 'source.sqlite'
    engine = create_engine('sqlite:///' + str(source))
    with engine.begin() as db:
        db.execute(text('CREATE TABLE sample (id INTEGER)'))
    engine.dispose()
    rehearsal.backup_bundle(source, media, tmp_path / 'backup')
    with pytest.raises(ValueError, match='outside'):
        rehearsal.restore_bundle(tmp_path / 'backup', tmp_path / 'backup' / 'nested-restore')
    assert not (tmp_path / 'backup' / 'nested-restore').exists()
    assert rehearsal.restore_bundle(tmp_path / 'backup', tmp_path / 'valid-restore')


def test_backup_manifest_cannot_escape_its_directory(tmp_path):
    _, _, rehearsal = release_modules()
    source = tmp_path / 'source.sqlite'
    engine = create_engine('sqlite:///' + str(source))
    with engine.begin() as db:
        db.execute(text('CREATE TABLE sample (id INTEGER)'))
    engine.dispose()
    media = tmp_path / 'media'
    media.mkdir()
    rehearsal.backup_bundle(source, media, tmp_path / 'backup')
    manifest_path = tmp_path / 'backup' / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['files']['media/../../source.sqlite'] = manifest['files']['database.sqlite']
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='unsafe'):
        rehearsal.restore_bundle(tmp_path / 'backup', tmp_path / 'escape-restore')
    assert not (tmp_path / 'escape-restore').exists()


def test_release_rollback_rehearsal_has_ready_head_and_never_converts_diary(tmp_path):
    _, _, rehearsal = release_modules()
    result = rehearsal.run_rehearsal(FIXTURE, tmp_path / 'run')
    assert result['status'] == 'passed'
    assert result['engine'] == 'sqlite'
    assert result['source_kind'] == 'synthetic'
    assert result['head'] == '0005_personalization_calendar'
    assert result['ready_before_release'] == result['ready_after_restore'] == 200
    assert result['reimport_reused'] == 31
    assert result['legacy_diaries_converted'] == 0
    assert result['restored_matches_backup'] is True
    assert result['restore_media_bytes_verified'] is True
    assert result['real_deployment_performed'] is False
    assert (tmp_path / 'run' / 'report.json').exists()
    with pytest.raises(ValueError, match='new'):
        rehearsal.run_rehearsal(FIXTURE, tmp_path / 'run')
