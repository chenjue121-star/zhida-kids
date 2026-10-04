"""Read-only image audits and validation of human-reviewed evaluation labels."""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import get_args

from PIL import Image, ImageOps

from app.v2.wardrobe.schemas import Category, Color, Pattern, Thickness


IMAGE_EXTENSIONS = frozenset({'.jpg', '.jpeg', '.png', '.webp'})
SPLITS = frozenset({'development', 'calibration', 'test'})
ATTRIBUTE_VALUES = {
    'category': get_args(Category), 'colors': get_args(Color),
    'pattern': get_args(Pattern), 'thickness': get_args(Thickness),
}


class ManifestError(ValueError):
    """A manifest cannot be used as reviewed evaluation ground truth."""


def _safe_image_path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        raise ManifestError('image path must be a safe relative path')
    relative = PurePosixPath(name)
    if relative.is_absolute() or PureWindowsPath(name).drive or '..' in relative.parts:
        raise ManifestError(f'image path must stay inside image_dir: {name!r}')
    if relative.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ManifestError(f'image path has an unsupported extension: {name!r}')
    try:
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ManifestError(f'image path resolves outside image_dir: {name!r}')
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, ManifestError):
            raise
        raise ManifestError(f'invalid image path: {name!r}') from exc
    return path


def _decode_image(data: bytes) -> dict:
    # verify checks file integrity; the second open forces real pixel decoding.
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image_format = image.format
        oriented = ImageOps.exif_transpose(image)
        oriented.load()
        return {'width': oriented.width, 'height': oriented.height, 'format': image_format}


def audit_images(image_dir: str | Path) -> dict:
    """Audit supported files in one directory without modifying any source file.

    Duplicates refer to original file bytes, including repeated invalid files.
    Dimensions describe the decoded image after applying its EXIF orientation.
    """
    root = Path(image_dir).resolve()
    entries = []
    first_by_hash = {}
    paths = sorted(root.iterdir(), key=lambda path: path.name)
    for candidate in paths:
        if candidate.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if not candidate.is_file() and not candidate.is_symlink():
            continue
        entry = {
            'image': candidate.name, 'sha256': None, 'valid': False,
            'width': None, 'height': None, 'format': None,
            'duplicate_of': None, 'error': None,
        }
        try:
            path = _safe_image_path(root, candidate.name)
            data = path.read_bytes()
            entry['sha256'] = hashlib.sha256(data).hexdigest()
            entry['duplicate_of'] = first_by_hash.get(entry['sha256'])
            first_by_hash.setdefault(entry['sha256'], candidate.name)
            entry.update(_decode_image(data))
            entry['valid'] = True
        except Exception as exc:
            entry['error'] = f'{type(exc).__name__}: {exc}'
        entries.append(entry)
    valid = sum(entry['valid'] for entry in entries)
    return {
        'total': len(entries), 'valid': valid,
        'unique_valid': sum(entry['valid'] and entry['duplicate_of'] is None for entry in entries),
        'invalid': len(entries) - valid,
        'duplicates': sum(entry['duplicate_of'] is not None for entry in entries),
        'entries': entries,
    }


def scaffold_manifest(audit: dict) -> dict:
    """Create review placeholders; never generate object labels from an image."""
    return {'schema_version': 1, 'entries': [
        {
            'image': entry['image'], 'sha256': entry['sha256'],
            'group_id': None, 'split': None, 'scene': None,
            'reviewed': False, 'objects': None,
        }
        for entry in audit['entries']
        if entry['valid'] is True and entry['duplicate_of'] is None
    ]}


def _validate_objects(objects: object, context: str) -> None:
    if not isinstance(objects, list) or len(objects) > 30:
        raise ManifestError(f'{context}: objects must be a list with at most 30 objects; [] means a reviewed negative')
    ids = set()
    for index, obj in enumerate(objects):
        object_context = f'{context}, objects[{index}]'
        if not isinstance(obj, dict):
            raise ManifestError(f'{object_context}: objects must contain JSON objects')
        object_id = obj.get('id')
        if not isinstance(object_id, str) or not object_id.strip():
            raise ManifestError(f'{object_context}: id must be a nonempty string')
        if object_id in ids:
            raise ManifestError(f'{object_context}: duplicate object id {object_id!r}')
        ids.add(object_id)
        bbox = obj.get('bbox')
        if (
            not isinstance(bbox, list) or len(bbox) != 4
            or any(type(value) not in (int, float) or not 0 <= value <= 1 or not math.isfinite(value) for value in bbox)
            or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]
        ):
            raise ManifestError(f'{object_context}: bbox must have four finite coordinates in [0, 1] and positive area')
        observable = obj.get('observable')
        if (
            not isinstance(observable, list)
            or any(not isinstance(field, str) or field not in ATTRIBUTE_VALUES for field in observable)
            or len(set(observable)) != len(observable)
        ):
            raise ManifestError(f'{object_context}: observable must list distinct category/colors/pattern/thickness fields')
        for field, values in ATTRIBUTE_VALUES.items():
            value = obj.get(field)
            if field not in observable:
                if value is not None:
                    raise ManifestError(f'{object_context}: unobservable {field} must be null or absent')
            elif field == 'colors':
                if (
                    not isinstance(value, list) or not value
                    or any(not isinstance(color, str) or color == 'unknown' or color not in values for color in value)
                    or len(set(value)) != len(value)
                ):
                    raise ManifestError(f'{object_context}: observable colors must be distinct known V2 colors')
            elif not isinstance(value, str) or value == 'unknown' or value not in values:
                raise ManifestError(f'{object_context}: observable {field} must be a known V2 value')


def load_manifest(path: str | Path, image_dir: str | Path, *, split: str | None = None) -> list[dict]:
    """Validate all reviewed records, including leakage, before filtering a split."""
    if split is not None and split not in SPLITS:
        raise ManifestError(f'split must be one of {sorted(SPLITS)}')
    try:
        document = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ManifestError(f'cannot read manifest JSON: {exc}') from exc
    if not isinstance(document, dict) or type(document.get('schema_version')) is not int or document['schema_version'] != 1:
        raise ManifestError('schema_version must be 1')
    entries = document.get('entries')
    if not isinstance(entries, list):
        raise ManifestError('entries must be a list')
    root = Path(image_dir).resolve()
    seen_images = set()
    seen_hashes = {}
    group_splits = {}
    for index, entry in enumerate(entries):
        context = f'entries[{index}]'
        if not isinstance(entry, dict):
            raise ManifestError(f'{context}: entry must be a JSON object')
        if entry.get('reviewed') is not True:
            raise ManifestError(f'{context}: reviewed must be true after human review')
        for field in ('group_id', 'scene'):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ManifestError(f'{context}: {field} must be a nonempty string')
        entry_split = entry.get('split')
        if not isinstance(entry_split, str) or entry_split not in SPLITS:
            raise ManifestError(f'{context}: split must be development, calibration, or test')
        group = entry['group_id']
        if group in group_splits and group_splits[group] != entry_split:
            raise ManifestError(f'{context}: group_id {group!r} leaks across split values')
        group_splits[group] = entry_split
        image = entry.get('image')
        image_path = _safe_image_path(root, image)
        if image in seen_images:
            raise ManifestError(f'{context}: duplicate image {image!r}')
        seen_images.add(image)
        try:
            data = image_path.read_bytes()
        except OSError as exc:
            raise ManifestError(f'{context}: cannot read image {image!r}: {exc}') from exc
        sha256 = hashlib.sha256(data).hexdigest()
        if entry.get('sha256') != sha256:
            raise ManifestError(f'{context}: sha256 hash does not match image {image!r}')
        if sha256 in seen_hashes:
            raise ManifestError(f'{context}: duplicate image content for {image!r} and {seen_hashes[sha256]!r}')
        seen_hashes[sha256] = image
        try:
            _decode_image(data)
        except Exception as exc:
            raise ManifestError(f'{context}: cannot decode image {image!r}: {exc}') from exc
        _validate_objects(entry.get('objects'), context)
    return [entry for entry in entries if split is None or entry['split'] == split]
