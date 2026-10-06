"""Read-only preparation and pure attribute scoring for the frozen 16-crop pilot.

No provider, application, settings, environment loading, network or file writes.
This diagnostic uses the user's overall confirmation of the main-product
inventory. It is neither independent human review nor full-screenshot detection
accuracy. Bounding boxes are a separate availability/validity diagnostic only.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import get_args

from PIL import Image

from app.v2.wardrobe.schemas import Category, Color, Pattern

PILOT_SIZE = 16
FIELDS = ('category', 'colors', 'pattern')
KIND = 'confirmed_single_crop_attribute_development_pilot'
SCOPE = ('干净单件裁图属性开发诊断；真值来自用户对75个主商品的整体确认，'
         '没有独立人工复核，不代表47张原图的端到端准确率；不评分定位或厚薄。')
_VALUES = {field: set(get_args(kind)) - {'unknown'} for field, kind in
           zip(FIELDS, (Category, Color, Pattern))}


def _read_document(path, kind):
    path = Path(path).resolve()
    raw = path.read_bytes()
    document = json.loads(raw)
    if not isinstance(document, dict) or type(document.get('schema_version')) is not int or \
            document['schema_version'] != 1 or document.get('kind') != kind:
        raise ValueError(f'a versioned {kind} document is required')
    return path, raw, document


def _answered(field, value):
    if field == 'colors':
        return isinstance(value, (list, tuple)) and bool(value) and all(
            isinstance(color, str) and color in _VALUES[field] for color in value)
    return isinstance(value, str) and value in _VALUES[field]


def _truth(item):
    if not isinstance(item, dict):
        raise ValueError('attribute truth must be an object')
    for field in FIELDS:
        if not _answered(field, item.get(field)):
            raise ValueError(f'{field} truth must be known')
    return {field: deepcopy(item[field]) for field in FIELDS} | {'thickness': None}


def _valid_bbox(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    return all(type(v) in (int, float) and 0 <= v <= 1 and math.isfinite(v) for v in value) and \
        value[0] < value[2] and value[1] < value[3]


def _crop_bytes(image_root, photo):
    name = photo.get('path')
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        raise ValueError('crop path must be a safe relative JPEG path')
    relative = PurePosixPath(name)
    if relative.is_absolute() or PureWindowsPath(name).drive or '..' in relative.parts or \
            relative.suffix.lower() not in ('.jpg', '.jpeg'):
        raise ValueError('crop path must be a safe relative JPEG path')
    path = (image_root / name).resolve()
    if not path.is_relative_to(image_root) or path.stat().st_size > 12 * 1024 * 1024:
        raise ValueError('crop path or size is invalid')
    raw = path.read_bytes()
    expected = photo.get('sha256')
    if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected) or \
            hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('frozen crop hash changed')
    with Image.open(io.BytesIO(raw)) as image:
        if image.format != 'JPEG' or image.width * image.height > 24_000_000 or \
                (image.width, image.height) != (photo.get('width'), photo.get('height')):
            raise ValueError('frozen crop format or dimensions changed')
        image.load()
    return name, expected


def derive_crop_pilot(inventory_path, bundle_path, image_root, *, confirmation_path):
    """Return a new 16-entry pilot from confirmed inventory and verified crops.

    All inputs are read and checked; no manifest or image is written. The returned
    entry ``image`` is relative to ``image_root`` and ``truth`` has no target bbox.
    """
    inventory_path, inventory_raw, inventory = _read_document(inventory_path, 'confirmed_main_product_inventory')
    bundle_path, bundle_raw, bundle = _read_document(bundle_path, 'frozen_outfit_development_comparison')
    confirmation_path, confirmation_raw, confirmation = _read_document(
        confirmation_path, 'user_main_product_dataset_confirmation')
    image_root = Path(image_root).resolve()
    items, photos = inventory.get('items'), bundle.get('photos')
    if not isinstance(items, list) or not isinstance(photos, dict) or \
            len(photos) != PILOT_SIZE or bundle.get('pilot_objects') != PILOT_SIZE:
        raise ValueError('the frozen pilot must contain exactly 16 crops')
    if bundle.get('visual_review') != 'codex_checked':
        raise ValueError('frozen crop visual review must be complete')
    inventory_hash = hashlib.sha256(inventory_raw).hexdigest()
    if bundle.get('inventory_sha256') != inventory_hash:
        raise ValueError('frozen inventory hash changed')
    if len(items) != 75 or bundle.get('inventory_objects') != len(items) or \
            confirmation.get('inventory_object_count') != len(items) or confirmation.get('source_image_count') != 47:
        raise ValueError('confirmation must refer to the complete 75-product, 47-image inventory')
    annotation_hash = inventory.get('source_annotations_sha256')
    if not isinstance(annotation_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', annotation_hash) or \
            inventory.get('confirmation_record') != confirmation_path.name or \
            confirmation.get('inventory_file') != inventory_path.name or \
            annotation_hash != confirmation.get('source_annotations_sha256'):
        raise ValueError('inventory confirmation provenance does not match')
    if confirmation.get('is_full_screenshot_end_to_end_recognition_ground_truth') is not False:
        raise ValueError('this confirmation is not full-screenshot detection ground truth')
    by_id = {}
    for item in items:
        gid = item.get('id') if isinstance(item, dict) else None
        if type(gid) is int and gid > 0:
            gid = str(gid)
        if not isinstance(gid, str) or not gid.strip() or gid in by_id:
            raise ValueError('inventory object IDs must be distinct nonempty strings')
        by_id[gid] = item
    entries = []
    for gid, photo in photos.items():
        if gid not in by_id or not isinstance(photo, dict):
            raise ValueError('frozen crop must map to one confirmed inventory object')
        item = by_id[gid]
        if any(photo.get(field) != item.get(field) for field in ('source_image', 'source_sha256', 'bbox')):
            raise ValueError('frozen crop source mapping changed')
        if item.get('split') != 'development' or not isinstance(item.get('group_id'), str) or not item['group_id'].strip():
            raise ValueError('crop pilot must retain its development source group')
        if item.get('thickness') not in (None, 'unknown'):
            raise ValueError('this pilot has unknown thickness and does not score it')
        truth = _truth(item)
        name, digest = _crop_bytes(image_root, photo)
        entries.append({'garment_id': gid, 'image': name, 'sha256': digest,
                        'group_id': item['group_id'], 'split': 'development', 'truth': truth,
                        'source_image': item['source_image'], 'source_sha256': item['source_sha256']})
    if len({entry['image'] for entry in entries}) != PILOT_SIZE or \
            len({entry['sha256'] for entry in entries}) != PILOT_SIZE:
        raise ValueError('pilot crops must have distinct paths and image contents')
    return {'schema_version': 1, 'kind': KIND, 'scope': SCOPE, 'split': 'development',
            'scored_fields': list(FIELDS), 'unscored_fields': ['thickness'], 'entries': entries,
            'provenance': {'inventory_path': str(inventory_path), 'inventory_sha256': inventory_hash,
                           'bundle_path': str(bundle_path), 'bundle_sha256': hashlib.sha256(bundle_raw).hexdigest(),
                           'confirmation_path': str(confirmation_path),
                           'confirmation_sha256': hashlib.sha256(confirmation_raw).hexdigest(),
                           'inventory_object_count': len(items), 'source_image_count': 47,
                           'confirmation_method': confirmation.get('confirmation_method'),
                           'confirmed_by': confirmation.get('confirmed_by'),
                           'reviewer_count': confirmation.get('reviewer_count'),
                           'independent_dual_review': confirmation.get('independent_dual_review'),
                           'is_full_screenshot_end_to_end_recognition_ground_truth': False,
                           'crop_visual_review': bundle['visual_review']}}


def score_crop(predictions, truth, *, status='ok'):
    """Score one crop's known attributes without matching or fabricating a bbox.

    Only a successful result with exactly one object can answer attributes. Empty,
    multiple and failed results score zero over the same one-sample denominators.
    A null/missing/invalid bbox never changes attributes; its quality is separate.
    """
    truth = _truth(truth)
    if not isinstance(status, str) or not status:
        raise ValueError('result status must be a nonempty string')
    candidate = None
    if status != 'ok':
        reason = 'request_failed'
    elif not isinstance(predictions, list):
        reason = 'invalid_predictions'
    elif not predictions:
        reason = 'missing_candidate'
    elif len(predictions) != 1:
        reason = 'extra_candidates'
    elif not isinstance(predictions[0], dict):
        reason = 'invalid_candidate'
    else:
        reason, candidate = 'eligible', predictions[0]
    fields = {}
    for field in FIELDS:
        actual = candidate.get(field) if candidate is not None else None
        answered = candidate is not None and _answered(field, actual)
        correct = bool(answered and (set(actual) == set(truth[field]) if field == 'colors' else actual == truth[field]))
        fields[field] = {'correct': int(correct), 'answered': int(answered), 'total': 1,
                         'accuracy': float(correct), 'coverage': float(answered)}
    bbox = candidate.get('bbox') if candidate is not None else None
    available = _valid_bbox(bbox)
    joint = int(all(field['correct'] for field in fields.values()))
    return {'status': status, 'eligible': candidate is not None, 'eligibility_code': reason,
            'prediction_count': len(predictions) if isinstance(predictions, list) else None,
            'bbox_available': bool(available), 'bbox_invalid': bbox is not None and not available,
            'fields': fields, 'joint_correct': joint, 'joint_total': 1, 'joint_accuracy': float(joint)}


def score_pilot(pilot, records):
    """Align records by entry image and score all 16, retaining raw and normalized data.

    Missing records become ``missing_result`` samples. Duplicate/foreign images
    are rejected rather than silently selecting the most favorable prediction.
    Existing ``candidates``, ``raw_candidates``, usage and errors are preserved.
    Attributes use normalized candidates; bbox quality uses raw candidates when
    available so normalization to null cannot hide an invalid supplied box.
    """
    entries = pilot.get('entries') if isinstance(pilot, dict) else None
    if not isinstance(entries, list) or len(entries) != PILOT_SIZE or pilot.get('kind') != KIND:
        raise ValueError('a derived 16-crop pilot is required')
    names = {entry['image'] for entry in entries}
    hashes = {entry['image']: entry['sha256'] for entry in entries}
    if len(names) != PILOT_SIZE:
        raise ValueError('pilot image paths must be distinct')
    if not isinstance(records, list):
        raise ValueError('records must be a list of image-keyed results')
    by_image = {}
    for record in records:
        if not isinstance(record, dict) or record.get('image') not in names or record['image'] in by_image:
            raise ValueError('records must name distinct images from this pilot')
        expected = hashes[record['image']]
        identity = record.get('identity')
        if ('sha256' in record and record['sha256'] != expected) or \
                (isinstance(identity, dict) and 'image_sha256' in identity and identity['image_sha256'] != expected):
            raise ValueError('result image hash does not match the frozen crop')
        by_image[record['image']] = record
    scored = []
    for entry in entries:
        record = deepcopy(by_image.get(entry['image'], {'image': entry['image'], 'status': 'missing_result',
                                                       'source': 'missing', 'candidates': []}))
        score = score_crop(record.get('candidates'), entry['truth'], status=record.get('status', 'missing_result'))
        raw_candidates = record.get('raw_candidates')
        if score['eligible'] and isinstance(raw_candidates, list) and len(raw_candidates) == 1 and isinstance(raw_candidates[0], dict):
            raw_bbox = raw_candidates[0].get('bbox')
            score['bbox_available'] = bool(_valid_bbox(raw_bbox))
            score['bbox_invalid'] = raw_bbox is not None and not score['bbox_available']
        record.update(garment_id=entry['garment_id'], sha256=entry['sha256'], group_id=entry['group_id'],
                      truth=deepcopy(entry['truth']), score=score)
        scored.append(record)
    fields = {}
    for field in FIELDS:
        correct = sum(record['score']['fields'][field]['correct'] for record in scored)
        answered = sum(record['score']['fields'][field]['answered'] for record in scored)
        fields[field] = {'correct': correct, 'answered': answered, 'total': PILOT_SIZE,
                         'accuracy': correct / PILOT_SIZE, 'coverage': answered / PILOT_SIZE}
    joint = sum(record['score']['joint_correct'] for record in scored)
    return {'schema_version': 1, 'kind': 'single_crop_attribute_pilot_scores', 'scope': SCOPE,
            'images': PILOT_SIZE, 'independent_groups': len({entry['group_id'] for entry in entries}),
            'scored_fields': list(FIELDS), 'unscored_fields': ['thickness'], 'fields': fields,
            'joint_correct': joint, 'joint_total': PILOT_SIZE, 'joint_accuracy': joint / PILOT_SIZE,
            'bbox_available': sum(record['score']['bbox_available'] for record in scored),
            'bbox_invalid': sum(record['score']['bbox_invalid'] for record in scored),
            'status_counts': dict(Counter(record['score']['status'] for record in scored)),
            'eligibility_counts': dict(Counter(record['score']['eligibility_code'] for record in scored)),
            'provenance': deepcopy(pilot.get('provenance')), 'records': scored}
