"""Coverage and legality reporting, without treating rule scores as taste truth."""
from collections import Counter
import json
import random


def summarize(cases, records, *, live_calls=0):
    groups = {}
    for case in cases:
        groups.setdefault(case.get('request_group', case['id']), case)
    representative_ids = {case['id'] for case in groups.values()}
    independent_records = [record for record in records if record['case_id'] in representative_ids]
    arms = {}
    available = {}
    for arm in ('attributes', 'photos'):
        values = [record for record in independent_records if record['arm'] == arm]
        available[arm] = {r['case_id'] for r in values if r['status'] not in ('offline_missing', 'invalid_input', 'budget_exhausted')}
        arms[arm] = {'statuses': dict(Counter(r['status'] for r in values)),
                     'valid_model_selections': sum(r['status'] == 'ok' and (r.get('selection') or {}).get('valid', False) for r in values),
                     'usable_with_fallback': sum(bool(r.get('usable_ids')) for r in values),
                     'fallbacks': sum(bool(r.get('fallback')) for r in values),
                     'pending': len(groups) - len(available[arm])}
    paired = len(available['attributes'] & available['photos'])
    models = sorted({r['model'] for r in independent_records if r['status'] == 'ok' and isinstance(r.get('model'), str)})
    consistent = len(models) <= 1
    return {'schema_version': 1, 'scenario_count': len(cases), 'independent_input_count': len(groups),
            'complete_pairs': paired, 'comparison_ready': paired == len(groups) and bool(groups) and consistent,
            'model_identifiers': models, 'model_version_consistent': consistent,
            'quality_result': None, 'human_blind_ratings': 0, 'live_calls': live_calls, 'arms': arms,
            'scope': '单来源development；相同模型输入只统计一次，尚无人工审美结果。',
            'records': records}


def markdown_report(report):
    lines = ['# 搭配照片对照：覆盖与合法性报告', '',
             f"输出模式：`{report.get('output_mode', 'prompt_only')}`。", '',
             f"模拟场景 {report['scenario_count']}，不同模型输入 {report['independent_input_count']}，"
             f"已覆盖成对输入 {report['complete_pairs']}，本轮真实调用 {report['live_calls']}。", '',
             '| 路径 | 原始模型合法选择 | 含兜底可用 | 待覆盖 | 状态 |',
             '| --- | ---: | ---: | ---: | --- |']
    for arm, label in (('attributes', '仅属性'), ('photos', '属性＋照片')):
        item = report['arms'][arm]
        lines.append(f"| {label} | {item['valid_model_selections']} | {item['usable_with_fallback']} | {item['pending']} | {json.dumps(item['statuses'], ensure_ascii=False)} |")
    lines += ['', '尚未收集人工盲评，因此没有搭配胜率、审美准确率或最优模型结论。', '', report['scope'], '']
    return '\n'.join(lines)


def blind_review_templates(cases, records, *, seed=20261005):
    """Keep source mappings in a separate file; missing responses remain placeholders."""
    rng = random.Random(seed)
    results = {(record['case_id'], record['arm']): record for record in records}
    groups, pairs, key = set(), [], []
    for case in cases:
        group = case.get('request_group', case['id'])
        if group in groups:
            continue
        groups.add(group)
        choices = {'rules': case['baseline_ids']}
        for arm in ('attributes', 'photos'):
            record = results.get((case['id'], arm), {})
            choices[arm] = record.get('chosen_ids') if record.get('status') == 'ok' else None
        for arms in (('rules', 'attributes'), ('rules', 'photos'), ('attributes', 'photos')):
            left, right = arms if rng.randrange(2) else arms[::-1]
            pair_id = f"{case['id']}-p{len(pairs) + 1:02d}"
            available = choices[left] is not None and choices[right] is not None
            identical = available and set(choices[left]) == set(choices[right])
            mismatch = (set(arms) == {'attributes', 'photos'} and available and
                        results[(case['id'], 'attributes')].get('model') != results[(case['id'], 'photos')].get('model'))
            pairs.append({'pair_id': pair_id, 'target_styles': case.get('styles', {}),
                          'left_ids': choices[left], 'right_ids': choices[right],
                          'status': 'actual_model_mismatch' if mismatch else 'identical_selection' if identical else 'ready' if available else 'awaiting_model_output',
                          'winner': None, 'color_coordination': None, 'style_coordination': None,
                          'preference_match': None, 'notes': None})
            key.append({'pair_id': pair_id, 'case_id': case['id'], 'left_source': left, 'right_source': right})
    return ({'schema_version': 1, 'display_seed': seed, 'reviewer': None,
             'allowed_choices': ['left', 'right', 'tie', 'neither'], 'pairs': pairs},
            {'schema_version': 1, 'display_seed': seed, 'pairs': key})
