"""Compare a frozen outfit bundle. No network unless --live is explicit."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from app.v2.outfits import rules
from eval.recognition_v2.compare import load_model_specs
from eval.recognition_v2.runner import CallBudget, CallLimitExceeded
from .prepare import fingerprint
from .protocol import safe_payload, validate_case
from .report import summarize, markdown_report, blind_review_templates
from .runner import run_one, _photos, OUTPUT_MODES


def _output_guard(output, cases, models, images, cache):
    if cache.exists() and not cache.is_dir():
        raise ValueError('cache directory cannot be a file')
    if cache == images or cache.is_relative_to(images) or any(p.is_relative_to(cache) for p in (cases, models)):
        raise ValueError('cache must be outside input directories/files')
    for protected in (cases, models, images, cache):
        if output == protected or protected.is_relative_to(output):
            raise ValueError('output must not contain or replace inputs/cache')
    if output.is_relative_to(images) or output.is_relative_to(cache):
        raise ValueError('output must be outside input images and cache')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('output directory must be absent or empty')


def _probe_directory(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, prefix='.write-probe-') as target:
        target.write(b'outfit-eval')
        target.flush()


def _load_bundle(path, images, *, live=False):
    bundle = json.loads(path.read_text(encoding='utf-8'))
    if bundle.get('schema_version') != 1 or bundle.get('kind') != 'frozen_outfit_development_comparison':
        raise ValueError('a frozen outfit bundle is required')
    if bundle.get('rule_sha256') != hashlib.sha256(Path(rules.__file__).read_bytes()).hexdigest():
        raise ValueError('rules changed; prepare a new frozen bundle')
    if live and bundle.get('visual_review') != 'codex_checked':
        raise ValueError('verify the derived visual inputs before live evaluation')
    cases = bundle.get('cases')
    if not isinstance(cases, list) or not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('cases must have distinct IDs')
    for case in cases + bundle.get('boundary_cases', []):
        validate_case(case)
        # Validate every alias as well as representatives before spending an API call.
        _photos(case, images)
        group = fingerprint({'text': safe_payload(case),
                             'photos': {gid: p['sha256'] for gid, p in case['photos'].items()}})
        if case.get('request_group') != group:
            raise ValueError('frozen request equivalence group changed')
    return bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', required=True)
    parser.add_argument('--images', required=True)
    parser.add_argument('--models', required=True)
    parser.add_argument('--model-name')
    parser.add_argument('--cache-dir', default='eval/outfits_v2/.cache')
    parser.add_argument('--output', required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--max-calls', type=int)
    parser.add_argument('--run-index', type=int, default=0)
    parser.add_argument('--output-mode', choices=OUTPUT_MODES, default='prompt_only')
    args = parser.parse_args(argv)
    try:
        if args.live and (args.max_calls is None or args.max_calls <= 0):
            raise ValueError('--live requires a positive --max-calls')
        if args.run_index < 0:
            raise ValueError('--run-index must be nonnegative')
        cases_path, models_path, images, cache, output = [Path(p).resolve() for p in
            (args.cases, args.models, args.images, args.cache_dir, args.output)]
        _output_guard(output, cases_path, models_path, images, cache)
        bundle = _load_bundle(cases_path, images, live=args.live)
        specs = load_model_specs(models_path)
        if args.model_name:
            specs = [spec for spec in specs if spec.name == args.model_name]
        if len(specs) != 1:
            raise ValueError('select exactly one configured model with --model-name for both arms')
        spec = specs[0]
        budget = CallBudget(args.max_calls) if args.live else None
        if args.live:
            # Fail before requests on a malformed/unwritable destination.
            _probe_directory(cache)
            _probe_directory(output)
        records, representatives = [], {}
        for case in bundle['cases']:
            for arm in ('attributes', 'photos'):
                key = (case['request_group'], arm)
                if key in representatives:
                    original = representatives[key]
                    record = {**original, 'case_id': case['id'], 'source': 'equivalent_reuse',
                              'reused_from': original['case_id']}
                    if record.get('fallback'):
                        record['usable_ids'] = case['baseline_ids']
                else:
                    try:
                        record = run_one(case, spec, images, cache, arm=arm, run_index=args.run_index,
                                         offline=not args.live, budget=budget, output_mode=args.output_mode)
                    except CallLimitExceeded:
                        record = {'case_id': case['id'], 'arm': arm, 'status': 'budget_exhausted',
                                  'source': 'validation', 'selection': None, 'chosen_ids': [], 'usable_ids': [],
                                  'fallback': False, 'usage': {}, 'error': {'code': 'CALL_BUDGET_EXHAUSTED'}}
                    representatives[key] = record
                records.append(record)
        report = summarize(bundle['cases'], records, live_calls=budget.used if budget else 0)
        report.update(requested_model=asdict(spec), run_index=args.run_index, output_mode=args.output_mode,
                      pilot_objects=bundle['pilot_objects'], visual_exclusions=bundle.get('visual_exclusions', {}),
                      boundary_results=[{'id': c['id'], 'candidate_count': len(c['combinations']),
                                         'missing_codes': sorted({e['code'] for e in c['baseline_missing']})}
                                        for c in bundle.get('boundary_cases', [])])
        template, blind_key = blind_review_templates(bundle['cases'], records)
        output.mkdir(parents=True, exist_ok=True)
        for name, document in (('report.json', report), ('manual-review.template.json', template), ('blind-key.json', blind_key)):
            (output / name).write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        (output / 'report.md').write_text(markdown_report(report), encoding='utf-8')
        print(json.dumps({key: report[key] for key in ('scenario_count', 'independent_input_count', 'complete_pairs', 'live_calls')}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f'evaluation stopped: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
