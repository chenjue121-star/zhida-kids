"""Audit, prepare reviewed labels, and compare production adapters. Offline by default."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from .dataset import SPLITS, audit_images, load_manifest, scaffold_manifest
from .report import format_report
from .runner import CallBudget, ModelSpec, create_provider, run_one
from .scorer import score_image

HERE = Path(__file__).resolve().parent
DEFAULT_IMAGES = HERE.parent / 'recognition' / 'dataset' / 'images'


def load_model_specs(path):
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(document, dict) or type(document.get('schema_version')) is not int or document['schema_version'] != 1:
        raise ValueError('model configuration schema_version must be 1')
    models = document.get('models')
    if not isinstance(models, list) or not models:
        raise ValueError('models must be a non-empty list')
    expected = {'name', 'provider', 'model', 'base_url', 'api_key_env'}
    result, names = [], set()
    for model in models:
        if not isinstance(model, dict) or set(model) != expected:
            raise ValueError('each model must contain only name/provider/model/base_url/api_key_env; keep secrets in the environment')
        spec = ModelSpec(**model)
        if spec.name in names:
            raise ValueError('model names must be unique')
        names.add(spec.name)
        result.append(spec)
    return result


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def _outputs(paths, overwrite, protected=(), image_dir=None):
    resolved = [Path(path).resolve() for path in paths if path]
    if len(set(resolved)) != len(resolved):
        raise ValueError('output paths must be distinct')
    protected = {Path(path).resolve() for path in protected}
    image_root = Path(image_dir).resolve() if image_dir is not None else None
    for path in resolved:
        if path in protected or (image_root is not None and path.is_relative_to(image_root)):
            raise ValueError('output cannot replace a source image, manifest, or model configuration')
        if path.exists() and (not overwrite or not path.is_file()):
            raise FileExistsError(f'output already exists: {path}; choose a new path or use --overwrite')


def _write(path, text, overwrite=False):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w' if overwrite else 'x', encoding='utf-8') as handle:
        handle.write(text)


def _compare(args):
    if args.repeat <= 0:
        raise ValueError('--repeat must be positive')
    if args.live and (args.max_calls is None or args.max_calls <= 0):
        raise ValueError('--live requires --max-calls with a positive call limit')
    entries = load_manifest(args.manifest, args.images, split=args.split)
    if not entries:
        raise ValueError('selected split has no reviewed independent samples')
    specs = load_model_specs(args.models)
    protected = [args.manifest, args.models, *(Path(args.images) / entry['image'] for entry in entries)]
    _outputs([args.out, args.json_out], args.overwrite, protected, args.images)

    # Preflight the whole experiment. Missing cache is never permission to call.
    prepared, needed = [], 0
    for spec in specs:
        records = []
        for entry in entries:
            for run_index in range(args.repeat):
                record = run_one(Path(args.images) / entry['image'], spec, args.cache_dir, run_index=run_index,
                                 expected_sha256=entry['sha256'])
                if record['status'] == 'offline_missing':
                    needed += 1
                records.append((entry, run_index, record))
        prepared.append((spec, records))
    print(f'{len(entries)} 个已审核图片，{len({entry["group_id"] for entry in entries})} 个独立分组；'
          f'{len(specs)} 模型 × {args.repeat} 次；缺少 {needed} 次有效缓存。')
    if args.live:
        if needed > args.max_calls:
            raise ValueError(f'需要 {needed} 次新调用，超过 --max-calls={args.max_calls}；尚未调用模型')
        for spec, records in prepared:
            if any(record['status'] == 'offline_missing' for _, _, record in records) and not os.environ.get(spec.api_key_env, '').strip():
                raise ValueError(f'缺少环境变量 {spec.api_key_env}；尚未调用模型')
    budget = CallBudget(args.max_calls) if args.live else None
    models, missing, failures = [], False, False
    for spec, prepared_records in prepared:
        records = []
        for entry, run_index, record in prepared_records:
            if args.live and record['status'] == 'offline_missing':
                record = run_one(Path(args.images) / entry['image'], spec, args.cache_dir,
                                 run_index=run_index, offline=False, budget=budget,
                                 provider_factory=create_provider, expected_sha256=entry['sha256'])
            missing |= record['status'] == 'offline_missing'
            failures |= record['status'] not in ('ok', 'offline_missing')
            record.update(image=entry['image'], group_id=entry['group_id'], scene=entry['scene'],
                          split=entry['split'], run_index=run_index, truths=entry['objects'])
            record['score'] = score_image(record['candidates'], entry['objects'], status=record['status'])
            records.append(record)
        models.append({'spec': asdict(spec), 'records': records})
    lines = ['# 智搭新版识别模型对测', '',
             f'运行模式：{"显式启用在线" if args.live else "严格离线"}；'
             f'本次新模型调用：{budget.used if budget else 0}。', '',
             '重复运行不是新增独立样本。仅审核标签构成真值；缓存只代表历史响应。'
             '本报告不自动宣布模型胜出或达到上线门槛。', '']
    if missing:
        lines.append('**离线缓存不完整，不能形成准确率结论；全部模型均暂停成绩汇总。**\n')
        for model in models:
            sources = model['records']
            lines.append(f'- {model["spec"]["name"]}：{sum(record["status"] == "offline_missing" for record in sources)} 条缺缓存。')
    else:
        for model in models:
            spec = model['spec']
            lines.append(format_report(model['records'], title=f'{spec["name"]} · {spec["provider"]}/{spec["model"]}'))
    document = {'schema_version': 1, 'mode': 'live_enabled' if args.live else 'offline',
                'new_calls': budget.used if budget else 0, 'complete': not missing, 'models': models}
    _write(args.json_out, _json(document), args.overwrite)
    _write(args.out, '\n'.join(lines) + '\n', args.overwrite)
    print(f'已保存 {args.out} 与 {args.json_out}；本次新调用 {document["new_calls"]}。')
    return 3 if missing else 4 if failures else 0


def build_parser():
    parser = argparse.ArgumentParser(description='新版多件衣物识别评测：默认严格离线')
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('audit', 'scaffold'):
        sub = commands.add_parser(command, help='审计图片' if command == 'audit' else '生成未审核标签骨架')
        sub.add_argument('--images', default=str(DEFAULT_IMAGES))
        sub.add_argument('--out', required=command == 'scaffold')
        sub.add_argument('--overwrite', action='store_true')
    compare = commands.add_parser('compare', help='比较 Qwen/ARK；缺缓存保持离线')
    compare.add_argument('--images', default=str(DEFAULT_IMAGES))
    compare.add_argument('--manifest', required=True)
    compare.add_argument('--models', required=True)
    compare.add_argument('--split', choices=sorted(SPLITS), default='test')
    compare.add_argument('--repeat', type=int, default=1)
    compare.add_argument('--cache-dir', default=str(HERE / '.cache'))
    compare.add_argument('--out', required=True)
    compare.add_argument('--json-out', required=True)
    compare.add_argument('--live', action='store_true')
    compare.add_argument('--max-calls', type=int)
    compare.add_argument('--overwrite', action='store_true')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == 'compare':
            return _compare(args)
        protected = [path for path in Path(args.images).iterdir() if path.is_file()]
        _outputs([args.out], args.overwrite, protected, args.images)
        audit = audit_images(args.images)
        if args.command == 'audit':
            if args.out:
                _write(args.out, _json(audit), args.overwrite)
            else:
                print(_json(audit), end='')
        else:
            _write(args.out, _json(scaffold_manifest(audit)), args.overwrite)
        print(f'图片 {audit["total"]}，可解码 {audit["valid"]}，独立有效 {audit["unique_valid"]}，'
              f'坏图 {audit["invalid"]}，重复 {audit["duplicates"]}。')
        return 0
    except (OSError, ValueError) as error:
        print(f'评测未完成：{error}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
