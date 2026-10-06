"""Confirmed labels become private review drafts, never owned clothes or AI jobs."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.v2.children.models import Child
from app.v2.core.errors import DomainError
from app.v2.families.models import Family, Membership
from app.v2.identity.models import User
from app.v2.media.models import MediaAsset
from app.v2.media.storage import FileStorage
from app.v2.recognition.models import Candidate, IntakeBatch, IntakeItem, RecognitionAttempt
from app.v2.wardrobe.models import Clothing


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


@pytest.fixture
def source(tmp_path, monkeypatch):
    from scripts import seed_confirmed_inventory as seed
    monkeypatch.setattr(seed, 'BACKEND_ROOT', tmp_path)
    image_root = tmp_path / 'images'
    image_root.mkdir()
    images, inventory_items = [], []
    for number, color in enumerate(('blue', 'red'), 1):
        stream = io.BytesIO()
        image = Image.new('RGB', (40 + number, 60), color)
        exif = Image.Exif()
        exif[0x010E] = 'private photo description'
        image.save(stream, format='JPEG', exif=exif)
        raw = stream.getvalue()
        name = f'c{number:03d}.jpg'
        (image_root / name).write_bytes(raw)
        suggestions = []
        for index in range(2 if number == 1 else 1):
            suggestion = {'draft_id': f'c{number:03d}-o{index + 1:02d}',
                          'description': f'蓝色上衣 {number}-{index}', 'bbox': [.1, .1, .9, .9],
                          'category': None if number == 2 else 'top', 'colors': [color],
                          'pattern': None if number == 2 else 'solid', 'thickness': None,
                          'fields_needing_review': ['bbox']}
            suggestions.append(suggestion)
            inventory_items.append({**suggestion, 'id': len(inventory_items) + 1,
                'source_image': name, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                'possible_related_images': [], 'open_questions': [],
                'group_id': 'test-source', 'split': 'development', 'scene': 'product_screenshot'})
        images.append({'image': name, 'sha256': hashlib.sha256(raw).hexdigest(),
            'suggestions': suggestions, 'group_id': 'test-source', 'split': 'development',
            'scene': 'product_screenshot', 'possible_related_images': [], 'open_questions': []})
    annotations = tmp_path / 'annotations.json'
    write_json(annotations, {'schema_version': 1, 'kind': 'ai_annotation_review_draft',
                            'image_root_from_backend': 'images', 'items': images})
    digest = hashlib.sha256(annotations.read_bytes()).hexdigest()
    common = {'schema_version': 1, 'source_annotations': 'annotations.json',
              'source_annotations_sha256': digest, 'source_path_base': 'backend',
              'source_image_root_from_backend': 'images', 'confirmed_on': '2026-10-05'}
    inventory = tmp_path / 'garments.json'
    confirmation = tmp_path / 'confirmation.json'
    write_json(inventory, {**common, 'kind': 'confirmed_main_product_inventory',
                           'confirmation_record': 'confirmation.json', 'items': inventory_items})
    write_json(confirmation, {**common, 'kind': 'user_main_product_dataset_confirmation',
        'confirmed_by': 'user_in_current_chat', 'scope': 'main_product_only',
        'unknown_fields_policy': 'preserve_null_without_inference',
        'inventory_file': 'garments.json', 'source_image_count': 2, 'inventory_object_count': 3,
        'unknown_field_counts': {'category': 1, 'pattern': 1, 'thickness': 3}})
    return seed, {'inventory_path': inventory, 'image_root': image_root,
                  'confirmation_path': confirmation}


@pytest.fixture
def target(engine, tmp_path):
    with Session(engine, expire_on_commit=False) as db:
        user = User(openid='seed-owner', nickname='家长')
        other = User(openid='other-parent')
        viewer = User(openid='viewer')
        db.add_all([user, other, viewer])
        db.flush()
        family = Family(name='Home', city='Shanghai', created_by=user.id)
        foreign = Family(name='Foreign', city='Shanghai', created_by=other.id)
        db.add_all([family, foreign])
        db.flush()
        db.add_all([Membership(family_id=family.id, user_id=user.id, role='admin'),
                    Membership(family_id=foreign.id, user_id=other.id, role='admin'),
                    Membership(family_id=family.id, user_id=viewer.id, role='viewer')])
        child = Child(family_id=family.id, nickname='宝宝')
        other_child = Child(family_id=foreign.id, nickname='外家孩子')
        db.add_all([child, other_child])
        db.commit()
        yield db, FileStorage(tmp_path / 'private'), {
            'user_id': user.id, 'family_id': family.id, 'child_id': child.id,
            'other_user_id': other.id, 'other_child_id': other_child.id, 'viewer_id': viewer.id}


def identifiers(target):
    return {key: target[2][key] for key in ('user_id', 'family_id', 'child_id')}


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def assert_empty(db, storage):
    for model in (IntakeBatch, IntakeItem, Candidate, MediaAsset, RecognitionAttempt, Clothing):
        assert count(db, model) == 0
    assert not storage.root.exists()


def test_dry_run_validates_inputs_and_actor_without_writing(source, target):
    seed, paths = source
    db, storage, _ = target
    report = seed.seed_inventory(db, storage, **identifiers(target), **paths)
    assert report['dry_run'] is True
    assert report['batch_id'] is None
    assert report['inventory_objects'] == 3 and report['source_images'] == 2
    assert report['source'] == 'confirmed_main_product_labels'
    assert report['unknown_field_counts'] == {'category': 1, 'pattern': 1, 'thickness': 3, 'fit': 3}
    assert_empty(db, storage)


def test_apply_keeps_unknown_unselected_drafts_and_private_full_images(source, target):
    seed, paths = source
    db, storage, ids = target
    report = seed.seed_inventory(db, storage, **identifiers(target), **paths, dry_run=False)
    assert report['created'] == {'batches': 1, 'items': 2, 'candidates': 3, 'media_assets': 2}
    assert report['model_calls'] == 0 and report['automatically_confirmed'] == 0
    batch = db.get(IntakeBatch, int(report['batch_id']))
    assert batch.created_by == ids['user_id'] and batch.default_child_id == ids['child_id']
    candidates = list(db.scalars(select(Candidate).order_by(Candidate.id)))
    assert candidates[-1].category is None and candidates[-1].pattern == 'unknown'
    assert all(c.thickness == 'unknown' and not c.selected and not c.discarded for c in candidates)
    assert all(c.owners == [{'child_id': ids['child_id'], 'fit': 'unknown'}] for c in candidates)
    assert all(c.attempt_id is None and c.confirmed_garment_id is None for c in candidates)
    assert all(c.ownership_exception is False for c in candidates)
    assert all(c.bbox == [.1, .1, .9, .9] for c in candidates)
    assert [c.name for c in candidates] == ['蓝色上衣 1-0', '蓝色上衣 1-1', '蓝色上衣 2-0']
    assert all(item.status == 'manual' and item.generation == 0 for item in db.scalars(select(IntakeItem)))
    assert count(db, RecognitionAttempt) == count(db, Clothing) == 0
    assets = list(db.scalars(select(MediaAsset).order_by(MediaAsset.id)))
    assert [(a.width, a.height) for a in assets] == [(41, 60), (42, 60)]
    for asset in assets:
        assert asset.object_key.startswith(f'families/{ids["family_id"]}/')
        stored = storage.get(asset.object_key)
        assert hashlib.sha256(stored).hexdigest() == asset.sha256
        with Image.open(io.BytesIO(stored)) as picture:
            assert not picture.getexif()
        assert (storage.root / asset.object_key).stat().st_mode & 0o777 == 0o600


def test_repeated_import_does_not_rewrite_edits_discard_or_confirmed_candidate(source, target):
    seed, paths = source
    db, storage, ids = target
    first = seed.seed_inventory(db, storage, **identifiers(target), **paths, dry_run=False)
    db.commit()
    candidates = list(db.scalars(select(Candidate).order_by(Candidate.id)))
    edited, discarded, confirmed = candidates
    edited.name, edited.selected, edited.version = '家长改名', True, 5
    edited.owners = [{'child_id': ids['child_id'], 'fit': 'large'}]
    edited.ownership_exception = True
    edited.dirty_fields = ['name', 'selected', 'owners']
    discarded.discarded, discarded.version = True, 4
    clothing = Clothing(family_id=ids['family_id'], created_by=ids['user_id'], name='已确认',
                        category='top', colors=['blue'], source_candidate_id=confirmed.id)
    db.add(clothing)
    db.flush()
    confirmed.confirmed_garment_id, confirmed.version = clothing.id, 7
    photo = db.scalar(select(IntakeItem).order_by(IntakeItem.id))
    photo.discarded, photo.version = True, 8
    db.commit()
    second = seed.seed_inventory(db, storage, **identifiers(target), **paths, dry_run=False)
    assert second['batch_id'] == first['batch_id']
    assert second['created'] == {'batches': 0, 'items': 0, 'candidates': 0, 'media_assets': 0}
    assert (count(db, IntakeBatch), count(db, IntakeItem), count(db, Candidate), count(db, MediaAsset)) == (1, 2, 3, 2)
    assert (edited.name, edited.selected, edited.version, edited.owners) == (
        '家长改名', True, 5, [{'child_id': ids['child_id'], 'fit': 'large'}])
    assert discarded.discarded and discarded.version == 4
    assert confirmed.confirmed_garment_id == clothing.id and confirmed.version == 7
    assert edited.ownership_exception is True
    assert photo.discarded and photo.version == 8
    assert count(db, Clothing) == 1 and count(db, RecognitionAttempt) == 0


@pytest.mark.parametrize('tamper', ['inventory', 'annotations', 'image', 'confirmation_hash',
                                  'confirmation_inventory', 'confirmation_count', 'confirmation_unknown'])
def test_source_or_confirmation_tampering_rejected_before_any_write(source, target, tamper):
    seed, paths = source
    db, storage, _ = target
    if tamper == 'inventory':
        document = json.loads(paths['inventory_path'].read_text())
        document['items'][0]['colors'] = ['green']
        write_json(paths['inventory_path'], document)
    elif tamper == 'annotations':
        (paths['inventory_path'].parent / 'annotations.json').write_text('{}')
    elif tamper == 'image':
        (paths['image_root'] / 'c002.jpg').write_bytes(b'tampered')
    else:
        document = json.loads(paths['confirmation_path'].read_text())
        if tamper == 'confirmation_hash':
            document['source_annotations_sha256'] = '0' * 64
        elif tamper == 'confirmation_inventory':
            document['inventory_file'] = 'another.json'
        elif tamper == 'confirmation_count':
            document['inventory_object_count'] = 999
        else:
            document['unknown_field_counts']['thickness'] = 0
        write_json(paths['confirmation_path'], document)
    with pytest.raises(ValueError):
        seed.seed_inventory(db, storage, **identifiers(target), **paths, dry_run=False)
    assert_empty(db, storage)


@pytest.mark.parametrize(('replacement', 'error_code'), [
    ('other_user_id', 'NOT_FOUND'), ('other_child_id', 'NOT_FOUND'), ('viewer_id', 'FORBIDDEN')])
def test_actor_family_child_permissions_checked_before_write(source, target, replacement, error_code):
    seed, paths = source
    db, storage, ids = target
    target_ids = identifiers(target)
    target_ids['child_id' if replacement == 'other_child_id' else 'user_id'] = ids[replacement]
    with pytest.raises(DomainError) as error:
        seed.seed_inventory(db, storage, **target_ids, **paths, dry_run=False)
    assert error.value.code == error_code
    assert_empty(db, storage)


def test_all_db_changes_rollback_if_storage_fails_and_retry_reuses_private_bytes(source, target):
    seed, paths = source
    db, storage, _ = target
    class FailsSecondImage:
        def __init__(self):
            self.calls = 0
        def put(self, *args):
            self.calls += 1
            if self.calls == 2:
                raise OSError('disk unavailable')
            return storage.put(*args)
        def get(self, key):
            return storage.get(key)
    with pytest.raises(OSError):
        seed.seed_inventory(db, FailsSecondImage(), **identifiers(target), **paths, dry_run=False)
    for model in (IntakeBatch, IntakeItem, Candidate, MediaAsset, RecognitionAttempt, Clothing):
        assert count(db, model) == 0
    assert len(list(storage.root.rglob('*.jpg'))) == 1
    report = seed.seed_inventory(db, storage, **identifiers(target), **paths, dry_run=False)
    assert report['created']['candidates'] == 3
    assert len(list(storage.root.rglob('*.jpg'))) == 2


def test_existing_family_asset_is_reused(source, target):
    seed, paths = source
    db, storage, ids = target
    from app.v2.media.service import normalize_image
    raw = (paths['image_root'] / 'c001.jpg').read_bytes()
    normalized, digest, width, height = normalize_image(raw, 'image/jpeg')
    asset = MediaAsset(family_id=ids['family_id'], sha256=digest, width=width, height=height,
                      object_key=storage.put(ids['family_id'], digest, normalized))
    db.add(asset)
    db.commit()
    report = seed.seed_inventory(db, storage, **identifiers(target), **paths, dry_run=False)
    assert report['created']['media_assets'] == 1 and report['reused']['media_assets'] == 1
    item = db.scalar(select(IntakeItem).order_by(IntakeItem.id))
    assert item.asset_id == asset.id


def test_import_never_uses_extra_evaluation_availability_or_fit_facts(source, target):
    seed, paths = source
    db, storage, ids = target
    inventory = json.loads(paths['inventory_path'].read_text())
    for item in inventory['items']:
        item.update({'fit': 'fit', 'state': 'washing', 'selected': True,
                     'owners': [{'child_id': ids['other_child_id'], 'fit': 'fit'}], 'age_months': 36})
    write_json(paths['inventory_path'], inventory)
    seed.seed_inventory(db, storage, **identifiers(target), **paths, dry_run=False)
    for candidate in db.scalars(select(Candidate)):
        assert candidate.owners == [{'child_id': ids['child_id'], 'fit': 'unknown'}]
        assert candidate.selected is False and candidate.state == 'ready'
    assert count(db, Clothing) == 0


def test_unconfirmed_images_are_accessible_only_to_the_creator_editor(source, target):
    seed, paths = source
    db, storage, ids = target
    seed.seed_inventory(db, storage, **identifiers(target), **paths, dry_run=False)
    another_editor = User(openid='same-family-editor')
    db.add(another_editor)
    db.flush()
    db.add(Membership(family_id=ids['family_id'], user_id=another_editor.id, role='editor'))
    db.commit()
    asset = db.scalar(select(MediaAsset).order_by(MediaAsset.id))
    from types import SimpleNamespace
    from app.v2.media.router import content
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    response = content(ids['family_id'], asset.id, request, db.get(User, ids['user_id']), db)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'private, no-store'
    for user_id in (ids['viewer_id'], ids['other_user_id'], another_editor.id):
        with pytest.raises(DomainError) as error:
            content(ids['family_id'], asset.id, request, db.get(User, user_id), db)
        assert error.value.code == 'NOT_FOUND'


def test_cli_default_dry_run_then_explicit_apply_with_real_isolated_sqlite(source, tmp_path, monkeypatch, capsys):
    seed, paths = source
    from app.v2.core.config import V2Settings
    from app.v2.core.database import build_engine, load_metadata
    url = 'sqlite:///' + str(tmp_path / 'import_test.db')
    engine = build_engine(url)
    load_metadata().create_all(engine)
    with Session(engine) as db:
        user = User(openid='cli-parent')
        db.add(user)
        db.flush()
        family = Family(name='CLI', created_by=user.id)
        db.add(family)
        db.flush()
        db.add(Membership(family_id=family.id, user_id=user.id, role='admin'))
        child = Child(family_id=family.id, nickname='宝宝')
        db.add(child)
        db.flush()
        ids = [str(family.id), str(user.id), str(child.id)]
        db.commit()
    engine.dispose()
    settings = V2Settings(_env_file=None, database_url=url, jwt_secret='offline-import-test-secret',
                          env='development', private_storage_dir=str(tmp_path / 'cli-private'))
    monkeypatch.setattr(seed, 'V2Settings', lambda: settings)
    arguments = ['--inventory', str(paths['inventory_path']), '--images', str(paths['image_root']),
                 '--confirmation', str(paths['confirmation_path']),
                 '--family-id', ids[0], '--user-id', ids[1], '--child-id', ids[2]]
    assert seed.main(arguments) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry['dry_run'] is True and dry['batch_id'] is None
    assert not Path(settings.private_storage_dir).exists()
    engine = build_engine(url)
    with Session(engine) as db:
        assert count(db, IntakeBatch) == count(db, Candidate) == 0
    engine.dispose()
    assert seed.main([*arguments, '--apply']) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied['dry_run'] is False and applied['created']['candidates'] == 3
    engine = build_engine(url)
    with Session(engine) as db:
        assert count(db, IntakeBatch) == 1 and count(db, Candidate) == 3
        assert count(db, Clothing) == count(db, RecognitionAttempt) == 0
    engine.dispose()


@pytest.mark.parametrize(('env', 'url', 'accepted'), [
    ('development', 'mysql+pymysql://user:secret@127.0.0.1/zhida_kids_v2_dev', True),
    ('development', 'sqlite://', True),
    ('production', 'sqlite://', False),
    ('test', 'sqlite://', False),
    ('development', 'mysql+pymysql://user:secret@remote/zhida_kids_v2_dev', False),
    ('development', 'mysql+pymysql://user:secret@localhost/zhida_kids', False),
    ('development', 'sqlite:////tmp/production.db', False),
])
def test_cli_settings_guard_is_development_and_local_dev_test_database_only(source, env, url, accepted):
    seed, _ = source
    from types import SimpleNamespace
    settings = SimpleNamespace(env=env, database_url=url)
    if accepted:
        seed.validate_local_settings(settings)
    else:
        with pytest.raises(ValueError, match='development|local|database') as error:
            seed.validate_local_settings(settings)
        assert 'secret' not in str(error.value)
