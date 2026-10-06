"""Freeze a small, explicitly simulated outfit experiment from confirmed inputs."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.v2.outfits import rules
from .protocol import garment_id

PILOT_IMAGES = (
    'c001.jpg', 'c006.jpg', 'c007.jpg', 'c008.jpg', 'c014.jpg',
    'c021.png', 'c022.png', 'c023.png', 'c024.png', 'c025.png', 'c030.png', 'c031.png',
    'c034.png', 'c036.png', 'c042.png', 'c043.png',
)
PREFERENCES = {'neutral': {}, 'clean': {'clean_daily': 1},
               'playful': {'playful_print': 1}, 'natural': {'soft_natural': 1}}
WEATHER_CONTEXTS = {'unknown': {'status': 'unknown'},
                    'transitional': {'status': 'known', 'temp_min': 16, 'temp_max': 21},
                    'warm': {'status': 'known', 'temp_min': 22, 'temp_max': 27}}
ASSUMPTIONS = ['日常场景、年龄36月、拥有这些衣物、ready和fit均为模拟实验条件。',
               '全部厚薄未知；不评价真实保暖、年龄适宜性或家庭实穿效果。',
               '单一development来源组；场景及疑似同款不代表独立家庭样本。']


def fingerprint(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _display_payload(case):
    by_id = {g['garment_id']: g for g in case['garments']}
    fields = ('garment_id', 'category', 'colors', 'pattern', 'thickness')
    return {'scene': case['scene'], 'styles': case['styles'],
            'combinations': [[{key: by_id[gid][key] for key in fields} for gid in combo]
                             for combo in case['combinations']]}


def _freeze_case(case, photos):
    parameters = {key: case[key] for key in ('scene', 'age_months', 'weather', 'comfort', 'styles',
                                            'locked_ids', 'excluded_ids', 'occupied_ids')}
    candidates = rules.options(case['garments'], **parameters)
    baseline = rules.generate(case['garments'], **parameters)
    case['retained_rule_candidate_count'] = len(candidates)
    case['combinations'] = [[rules.identity(g) for g in combo] for combo in candidates[:20]]
    case['baseline_ids'] = [rules.identity(g) for g in baseline['items']]
    case['baseline_warnings'] = baseline['warnings']
    case['baseline_missing'] = baseline['missing']
    referenced = {gid for combo in case['combinations'] for gid in combo}
    case['photos'] = {gid: photos[gid] for gid in sorted(referenced, key=int)}
    case['request_group'] = fingerprint({'text': _display_payload(case),
                                         'photos': {gid: p['sha256'] for gid, p in case['photos'].items()}})
    return case


def freeze_cases(items, photos):
    """Do not write synthetic availability or fit back into source annotations."""
    garments = [{'id': str(item['id']), 'garment_id': str(item['id']), 'name': '',
                 'category': item['category'], 'colors': item['colors'],
                 'pattern': item['pattern'] or 'unknown', 'thickness': item['thickness'] or 'unknown',
                 'state': 'ready', 'fit': 'fit', 'archived_at': None} for item in items]
    def new_case(case_id, weather, styles):
        return {'id': case_id, 'scene': 'daily', 'age_months': 36,
                'weather': dict(weather), 'comfort': {}, 'styles': dict(styles),
                'garments': [dict(g) for g in garments], 'locked_ids': [], 'excluded_ids': [],
                'occupied_ids': [], 'assumptions': list(ASSUMPTIONS)}
    cases = [_freeze_case(new_case(f'{style}-{weather}', context, weights), photos)
             for style, weights in PREFERENCES.items() for weather, context in WEATHER_CONTEXTS.items()]
    boundaries = []
    for name in ('missing_shoes', 'all_washing', 'fit_unknown', 'fixed_excluded', 'all_occupied'):
        case = new_case(name, WEATHER_CONTEXTS['unknown'], {})
        if name == 'missing_shoes':
            case['scene'] = 'outdoor'
        elif name == 'all_washing':
            for garment in case['garments']:
                garment['state'] = 'washing'
        elif name == 'fit_unknown':
            for garment in case['garments']:
                garment['fit'] = 'unknown'
        elif name == 'fixed_excluded':
            case['locked_ids'] = [garments[0]['garment_id']]
            case['excluded_ids'] = list(case['locked_ids'])
        else:
            case['occupied_ids'] = [g['garment_id'] for g in garments]
        boundaries.append(_freeze_case(case, photos))
    return cases, boundaries


def _font(size):
    for name in ('/System/Library/Fonts/PingFang.ttc',
                 '/System/Library/Fonts/STHeiti Medium.ttc',
                 '/System/Library/Fonts/Supplemental/Arial.ttf'):
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def _preview(items, photos, cases, output):
    font = _font(16)
    # All crops can be inspected at a useful size in two sheets.
    for start in range(0, len(items), 9):
        sheet = Image.new('RGB', (960, 1140), '#f5f5f5')
        draw = ImageDraw.Draw(sheet)
        for index, item in enumerate(items[start:start + 9]):
            x, y = index % 3 * 320, index // 3 * 380
            with Image.open(output / photos[str(item['id'])]['path']) as source:
                crop = ImageOps.contain(source, (300, 340))
                sheet.paste(crop, (x + (320 - crop.width) // 2, y + 25))
            draw.text((x + 10, y + 4), f"{item['id']} / {item['source_image']} / {item['category']}", fill='black', font=font)
        sheet.save(output / f'crop-review-{start // 9 + 1}.jpg', quality=92)
    preview = Image.new('RGB', (1200, 1020), '#f5f5f5')
    draw = ImageDraw.Draw(preview)
    draw.text((12, 8), '规则基线 · 模拟条件 · 尚无模型输出或审美评分', fill='black', font=_font(22))
    for index, case in enumerate(cases):
        x, y = index % 4 * 300, index // 4 * 320 + 50
        draw.text((x + 8, y + 5), case['id'], fill='black', font=font)
        chosen = case['baseline_ids']
        width = 280 // max(1, len(chosen))
        for position, gid in enumerate(chosen):
            with Image.open(output / photos[gid]['path']) as source:
                crop = ImageOps.contain(source, (width - 8, 235))
                preview.paste(crop, (x + 10 + position * width, y + 32))
            draw.text((x + 10 + position * width, y + 270), f'ID {gid}', fill='black', font=font)
    preview.save(output / 'baseline-preview.jpg', quality=92)


def prepare_bundle(inventory_path, source_root, output_dir):
    inventory_path, source_root, output = map(lambda p: Path(p).resolve(), (inventory_path, source_root, output_dir))
    if output == source_root or output.is_relative_to(source_root) or inventory_path.is_relative_to(output):
        raise ValueError('output must not contain inputs or be inside the source directory')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('output directory must be absent or empty')
    document = json.loads(inventory_path.read_text(encoding='utf-8'))
    if document.get('schema_version') != 1 or document.get('kind') != 'confirmed_main_product_inventory':
        raise ValueError('a confirmed main-product inventory is required')
    grouped = {}
    inventory_ids = set()
    for item in document['items']:
        gid = garment_id(item['id'])
        if gid in inventory_ids:
            raise ValueError('duplicate inventory object id')
        inventory_ids.add(gid)
        grouped.setdefault(item['source_image'], []).append({**item, 'id': gid})
    items, decoded = [], []
    for name in PILOT_IMAGES:
        matches = grouped.get(name, [])
        if len(matches) != 1:
            raise ValueError(f'{name}: pilot requires one confirmed main product')
        item = matches[0]
        if item['category'] not in ('top', 'bottom', 'outerwear', 'dress', 'onesie'):
            raise ValueError(f'{name}: category must be resolved')
        if item['pattern'] not in ('solid', 'stripe', 'plaid', 'print', 'dots'):
            raise ValueError(f'{name}: pattern must be resolved')
        data = (source_root / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != item['source_sha256']:
            raise ValueError(f'{name}: source hash changed')
        bbox = item['bbox']
        if (len(bbox) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in bbox)
                or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
            raise ValueError(f'{name}: invalid object bbox')
        with Image.open(source_root / name) as source:
            oriented = ImageOps.exif_transpose(source).convert('RGB')
            rectangle = (math.floor(bbox[0] * oriented.width), math.floor(bbox[1] * oriented.height),
                         math.ceil(bbox[2] * oriented.width), math.ceil(bbox[3] * oriented.height))
            decoded.append(oriented.crop(rectangle))
        items.append(item)
    if len({str(item['id']) for item in items}) != len(items):
        raise ValueError('duplicate pilot object id')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'images').mkdir()
    photos = {}
    for item, image in zip(items, decoded):
        gid = str(item['id'])
        image.thumbnail((1024, 1024))
        target = output / 'images' / f'{gid}.jpg'
        if not target.resolve().is_relative_to((output / 'images').resolve()):
            raise ValueError('crop path must remain inside output images')
        image.save(target, quality=92)
        photos[gid] = {'path': f'images/{gid}.jpg', 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                       'source_image': item['source_image'], 'source_sha256': item['source_sha256'],
                       'bbox': item['bbox'], 'width': image.width, 'height': image.height}
    cases, boundaries = freeze_cases(items, photos)
    bundle = {'schema_version': 1, 'kind': 'frozen_outfit_development_comparison',
              'prepared_on': '2026-10-05', 'inventory_sha256': hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
              'rule_version': rules.RULE_VERSION, 'rule_sha256': hashlib.sha256(Path(rules.__file__).read_bytes()).hexdigest(),
              'inventory_objects': len(document['items']), 'pilot_images': list(PILOT_IMAGES),
              'pilot_objects': len(items), 'pilot_category_counts': dict(Counter(i['category'] for i in items)),
              'assumptions': ASSUMPTIONS, 'photos': photos, 'cases': cases, 'boundary_cases': boundaries,
              'distinct_request_groups': len({case['request_group'] for case in cases}),
              'visual_exclusions': {'c005.jpg': '裁图仍含模特下颌及内搭领口，退出首轮单件视觉对照。',
                                    'c012.jpg': '对象框裁图角落仍含页面计数标记，退出首轮单件视觉对照。'},
              'visual_review': 'generated_bbox_crops_require_visual_verification'}
    (output / 'cases.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    _preview(items, photos, cases, output)
    return bundle
