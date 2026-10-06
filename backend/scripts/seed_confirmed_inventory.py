"""Fill a development intake draft from confirmed labels, without model calls.

Run from backend with ``python -m scripts.seed_confirmed_inventory --help``.
The default validates and previews; only --apply writes an atomic DB transaction.
Private image files survive a failed transaction and are safe to reuse on retry.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.v2.children.service import get_child
from app.v2.core.config import V2Settings
from app.v2.core.database import build_engine, session_factory
from app.v2.core.errors import DomainError, fail
from app.v2.families.access import family_access
from app.v2.families.models import MutationReceipt
from app.v2.identity.models import User
from app.v2.media.models import MediaAsset
from app.v2.media.service import normalize_image
from app.v2.media.storage import FileStorage
from app.v2.recognition import service
from app.v2.recognition.models import Candidate, IntakeItem
from app.v2.recognition.schemas import BatchCreate, CandidateCreate, ItemCreate


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_BYTES = 12 * 1024 * 1024
LABEL_FIELDS = ('draft_id', 'description', 'bbox', 'category', 'colors', 'pattern',
                'thickness', 'fields_needing_review')
IMAGE_FIELDS = ('group_id', 'split', 'scene', 'possible_related_images', 'open_questions')
MIMES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}


@dataclass(frozen=True)
class PreparedInventory:
    sha256: str
    items: list[dict]
    images: dict[str, tuple[bytes, str, int, int]]
    unknown_field_counts: dict[str, int]


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field in confirmed inputs')
        result[key] = value
    return result


def _read_json(path):
    path = Path(path)
    if path.stat().st_size > DEFAULT_MAX_BYTES:
        raise ValueError('Confirmed input JSON is too large')
    raw = path.read_bytes()
    def reject_constant(value):
        raise ValueError('Non-finite value in confirmed inputs')
    result = json.loads(raw, object_pairs_hook=_unique_json_pairs, parse_constant=reject_constant)
    if not isinstance(result, dict):
        raise ValueError('Confirmed input must be a JSON object')
    return result, hashlib.sha256(raw).hexdigest()


def _bound_source(relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError('Missing source path binding')
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Source path must stay inside backend')
    resolved = (BACKEND_ROOT / path).resolve()
    if not resolved.is_relative_to(BACKEND_ROOT.resolve()):
        raise ValueError('Source path must stay inside backend')
    return resolved


def _candidate_fields(item, child_id):
    description = item['description']
    if not isinstance(description, str):
        raise ValueError('Label description must be text')
    # Provenance belongs to the import report; this name can later become a garment name.
    name = re.split('[。！？\\n]', description, maxsplit=1)[0].strip()[:80]
    return {'client_id': 'confirmed-label:' + item['draft_id'],
            'name': name, 'category': item['category'],
            'colors': item['colors'], 'pattern': item['pattern'] or 'unknown',
            'thickness': item['thickness'] or 'unknown',
            'owners': [{'child_id': child_id, 'fit': 'unknown'}], 'selected': False}


def prepare_inventory(inventory_path, image_root, confirmation_path, *, max_bytes=DEFAULT_MAX_BYTES):
    """Verify all bindings, label projections and original photos before writes."""
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('Image byte limit must be positive')
    inventory_path, image_root, confirmation_path = map(
        lambda path: Path(path).resolve(), (inventory_path, image_root, confirmation_path))
    inventory, inventory_sha = _read_json(inventory_path)
    confirmation, _ = _read_json(confirmation_path)
    if (inventory.get('schema_version') != 1 or inventory.get('kind') != 'confirmed_main_product_inventory'
            or confirmation.get('schema_version') != 1
            or confirmation.get('kind') != 'user_main_product_dataset_confirmation'
            or confirmation.get('confirmed_by') != 'user_in_current_chat'
            or confirmation.get('scope') != 'main_product_only'
            or confirmation.get('unknown_fields_policy') != 'preserve_null_without_inference'):
        raise ValueError('User-confirmed main-product inputs are required')
    if (inventory.get('confirmation_record') != confirmation_path.name
            or confirmation.get('inventory_file') != inventory_path.name
            or confirmation_path.parent != inventory_path.parent):
        raise ValueError('Confirmation does not bind this inventory file')
    for field in ('source_annotations', 'source_annotations_sha256', 'source_path_base',
                  'source_image_root_from_backend', 'confirmed_on'):
        if not inventory.get(field) or inventory.get(field) != confirmation.get(field):
            raise ValueError('Inventory and confirmation source bindings differ')
    if inventory['source_path_base'] != 'backend':
        raise ValueError('Unsupported source path base')
    if _bound_source(inventory['source_image_root_from_backend']) != image_root:
        raise ValueError('Image root does not match the confirmed source')
    annotations, annotations_sha = _read_json(_bound_source(inventory['source_annotations']))
    if (annotations_sha != inventory['source_annotations_sha256']
            or annotations.get('schema_version') != 1
            or annotations.get('kind') != 'ai_annotation_review_draft'
            or annotations.get('image_root_from_backend') != inventory['source_image_root_from_backend']):
        raise ValueError('Source annotations hash or source binding changed')
    items, source_items = inventory.get('items'), annotations.get('items')
    if not isinstance(items, list) or not items or not isinstance(source_items, list) or not source_items:
        raise ValueError('Confirmed inventory and annotations must contain items')
    expected, image_hashes = {}, {}
    for image in source_items:
        if not isinstance(image, dict):
            raise ValueError('Invalid source annotation image')
        name, source_sha = image.get('image'), image.get('sha256')
        if (not isinstance(name, str) or Path(name).name != name or name in image_hashes
                or Path(name).suffix.lower() not in MIMES
                or not isinstance(source_sha, str) or not re.fullmatch(r'[0-9a-f]{64}', source_sha)):
            raise ValueError('Invalid or duplicate source image binding')
        image_hashes[name] = source_sha
        suggestions = image.get('suggestions')
        if not isinstance(suggestions, list) or not suggestions:
            raise ValueError('Source image requires main-product suggestions')
        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                raise ValueError('Invalid source label')
            draft_id = suggestion.get('draft_id')
            if not isinstance(draft_id, str) or not draft_id or len(draft_id) > 100 or draft_id in expected:
                raise ValueError('Invalid or duplicate source label identity')
            expected[draft_id] = {'source_image': name, 'source_sha256': source_sha,
                **{key: suggestion.get(key) for key in LABEL_FIELDS},
                **{key: image.get(key) for key in IMAGE_FIELDS}}
    ids, draft_ids, used_images = set(), set(), set()
    for item in items:
        if not isinstance(item, dict) or type(item.get('id')) is not int or item['id'] <= 0 or item['id'] in ids:
            raise ValueError('Invalid or duplicate inventory object ID')
        ids.add(item['id'])
        draft_id = item.get('draft_id')
        if draft_id not in expected or draft_id in draft_ids:
            raise ValueError('Invalid or duplicate inventory source identity')
        draft_ids.add(draft_id)
        if any(item.get(key) != value for key, value in expected[draft_id].items()):
            raise ValueError('Inventory label differs from confirmed source annotations')
        bbox = item.get('bbox')
        if bbox is not None and (not isinstance(bbox, list) or len(bbox) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in bbox)
                or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
            raise ValueError('Invalid source context bbox')
        # Validate production field enums before any storage or DB mutation.
        CandidateCreate(item_id=1, **_candidate_fields(item, 1))
        used_images.add(item['source_image'])
    unknown = {key: sum(item[key] is None for item in items) for key in ('category', 'pattern', 'thickness')}
    if (draft_ids != set(expected) or used_images != set(image_hashes)
            or type(confirmation.get('inventory_object_count')) is not int
            or confirmation['inventory_object_count'] != len(items)
            or type(confirmation.get('source_image_count')) is not int
            or confirmation['source_image_count'] != len(image_hashes)
            or confirmation.get('unknown_field_counts') != unknown):
        raise ValueError('Confirmation counts or complete label scope differ')
    normalized = {}
    for name, source_sha in image_hashes.items():
        path = image_root / name
        if path.is_symlink() or not path.resolve().is_relative_to(image_root):
            raise ValueError('Source image must remain inside the confirmed image root')
        if path.stat().st_size > max_bytes:
            raise ValueError('Source image exceeds the configured byte limit')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source_sha:
            raise ValueError('Source image hash changed')
        normalized[name] = normalize_image(raw, MIMES[path.suffix.lower()], max_bytes)
    return PreparedInventory(inventory_sha, items, normalized, {**unknown, 'fit': len(items)})


def _identity(prepared, user_id, family_id, child_id):
    payload = json.dumps([prepared.sha256, user_id, family_id, child_id], separators=(',', ':'))
    return 'confirmed-inventory:' + hashlib.sha256(payload.encode()).hexdigest()


def seed_inventory(db, storage, *, user_id, family_id, child_id, inventory_path,
                   image_root, confirmation_path, max_bytes=DEFAULT_MAX_BYTES, dry_run=True):
    """Populate one actor-owned review batch; the caller commits its transaction."""
    for identifier in (user_id, family_id, child_id):
        if type(identifier) is not int or identifier <= 0:
            raise ValueError('Target user, family and child IDs must be positive integers')
    prepared = prepare_inventory(inventory_path, image_root, confirmation_path, max_bytes=max_bytes)
    user = db.get(User, user_id)
    if user is None:
        fail(404, 'NOT_FOUND', '录入者不存在')
    family, _ = family_access(db, family_id, user, ('admin', 'editor'), lock=True)
    get_child(db, family_id, child_id, lock=True)
    key = _identity(prepared, user_id, family_id, child_id)
    previous = db.scalar(select(MutationReceipt).where(
        MutationReceipt.actor_id == user_id, MutationReceipt.operation == 'intake_batch:' + str(family_id),
        MutationReceipt.idempotency_key == key).with_for_update())
    batch = service.get_batch(db, family_id, int(previous.response_body['id']), user, lock=True) if previous else None
    report = {'dry_run': bool(dry_run), 'source': 'confirmed_main_product_labels',
        'inventory_sha256': prepared.sha256, 'family_id': str(family_id), 'user_id': str(user_id),
        'child_id': str(child_id), 'batch_id': str(batch.id) if batch else None,
        'source_images': len(prepared.images), 'inventory_objects': len(prepared.items),
        'unknown_field_counts': prepared.unknown_field_counts,
        'created': {'batches': 0, 'items': 0, 'candidates': 0, 'media_assets': 0},
        'reused': {'batches': 0, 'items': 0, 'candidates': 0, 'media_assets': 0},
        'model_calls': 0, 'automatically_confirmed': 0}
    if batch is not None:
        report['reused'] = {'batches': 1,
            'items': db.scalar(select(func.count()).select_from(IntakeItem).where(IntakeItem.batch_id == batch.id)),
            'candidates': db.scalar(select(func.count()).select_from(Candidate).where(Candidate.batch_id == batch.id)),
            'media_assets': len(set(db.scalars(select(IntakeItem.asset_id).where(
                IntakeItem.batch_id == batch.id, IntakeItem.asset_id.is_not(None)))))}
        return report  # Never revisit fields after a parent edits, discards or confirms.
    if dry_run:
        return report
    # All database writes, including the receipt, either succeed together or roll back.
    with db.begin_nested():
        created = service.create_batch(db, family, user, BatchCreate(default_child_id=child_id), key)
        batch = service.get_batch(db, family_id, int(created['id']), user, lock=True)
        report['batch_id'], report['created']['batches'] = str(batch.id), 1
        image_items = {}
        for name, (content, digest, width, height) in prepared.images.items():
            asset = db.scalar(select(MediaAsset).where(
                MediaAsset.family_id == family_id, MediaAsset.sha256 == digest).with_for_update())
            if asset is None:
                object_key = storage.put(family_id, digest, content)
                asset = MediaAsset(family_id=family_id, sha256=digest, object_key=object_key,
                                   width=width, height=height, content_type='image/jpeg')
                db.add(asset)
                db.flush()
                report['created']['media_assets'] += 1
            else:
                if (not asset.object_key.startswith(f'families/{family_id}/')
                        or storage.get(asset.object_key) != content):
                    fail(409, 'ASSET_STORAGE_CONFLICT', '已有照片存储校验不一致')
                report['reused']['media_assets'] += 1
            value = service.create_item(db, batch, ItemCreate(client_id='confirmed-image:' + name, source='album'))
            item = service.get_item(db, batch.id, int(value['id']), lock=True)
            item.asset_id = asset.id
            image_items[name] = item
            report['created']['items'] += 1
        for label in prepared.items:
            item = image_items[label['source_image']]
            value = service.create_candidate(db, batch, CandidateCreate(
                item_id=item.id, **_candidate_fields(label, child_id)))
            candidate = service.get_candidate(db, batch.id, int(value['id']), lock=True)
            candidate.bbox = label['bbox']  # Context only: retain the full private original.
            # Imported unknown fit is a batch default, not a parent-created per-item exception.
            candidate.ownership_exception = False
            report['created']['candidates'] += 1
        db.flush()
    return report


def validate_local_settings(settings):
    if settings.env != 'development':
        raise ValueError('This importer requires the development environment')
    url = make_url(settings.database_url)
    if url.get_backend_name() == 'mysql':
        if url.host not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('This importer requires a local database server')
        if url.database not in ('zhida_kids_v2_dev', 'zhida_kids_v2_test', 'zhida_kids_v2_migration_test'):
            raise ValueError('This importer requires an isolated development or test database')
    elif url.get_backend_name() == 'sqlite':
        name = url.database or ''
        if name not in ('', ':memory:') and not re.fullmatch(r'.*[_-](dev|test)\.db', Path(name).name):
            raise ValueError('This importer requires a development or test SQLite database')
    else:
        raise ValueError('Unsupported local development database')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--confirmation', type=Path, required=True)
    parser.add_argument('--family-id', type=int, required=True)
    parser.add_argument('--user-id', type=int, required=True)
    parser.add_argument('--child-id', type=int, required=True)
    parser.add_argument('--apply', action='store_true', help='write the review draft; default is a dry run')
    args = parser.parse_args(argv)
    engine = None
    try:
        settings = V2Settings()
        validate_local_settings(settings)
        engine = build_engine(settings.database_url)
        with session_factory(engine)() as db, db.begin():
            report = seed_inventory(db, FileStorage(settings.private_storage_dir), user_id=args.user_id,
                family_id=args.family_id, child_id=args.child_id, inventory_path=args.inventory,
                image_root=args.images, confirmation_path=args.confirmation,
                max_bytes=settings.upload_max_bytes, dry_run=not args.apply)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except DomainError as error:
        print(json.dumps({'error': {'code': error.code, 'message': error.message}}, ensure_ascii=False))
        return 1
    except (ValueError, OSError):
        # Validation errors can contain input values or credentials: expose no raw exception.
        print(json.dumps({'error': {'code': 'INVALID_CONFIRMED_INPUT',
                                  'message': '本地开发配置或确认来源校验失败，未完成导入'}}, ensure_ascii=False))
        return 1
    except Exception:
        print(json.dumps({'error': {'code': 'IMPORT_FAILED', 'message': '导入未完成，数据库事务已回滚'}}, ensure_ascii=False))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
