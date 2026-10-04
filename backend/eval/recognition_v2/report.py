"""Chinese Markdown reports with explicit sample, failure and cache provenance."""
from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
from numbers import Real

from .scorer import FIELDS, aggregate_scores

_FIELD_NAMES = {'category': '类别', 'colors': '颜色集合', 'pattern': '图案', 'thickness': '厚薄'}
_ERROR_NAMES = {'request_failed': '请求失败', 'missed': '漏件', 'extra': '多报',
                'unlocalized': '缺框/非法框', 'field_wrong': '字段错误',
                'unanswered': '字段未作答', 'unsupported': '不可观察字段赋值'}


def _text(value) -> str:
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def _percent(value: float | None) -> str:
    return f'{value:.1%}' if value is not None else '—（无分母）'


def _distribution(values) -> str:
    return '、'.join(f'{_text(key)}: {count}' for key, count in sorted(Counter(values).items())) or '无'


def _numeric(value) -> bool:
    try:
        return isinstance(value, Real) and not isinstance(value, bool) and isfinite(value) and value >= 0
    except OverflowError:
        return False


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * probability
    lower = int(position)
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[min(lower + 1, len(values) - 1)] * fraction


def _time_line(label: str, values: list[float]) -> str:
    p50, p95 = _quantile(values, .5), _quantile(values, .95)
    if p50 is None:
        return f'- {label}：无可用记录。'
    return f'- {label}：n={len(values)}，P50 {p50:.1f} ms，P95 {p95:.1f} ms。'


def _usage(records: list[dict]) -> dict:
    totals = defaultdict(float)

    def collect(value, prefix=''):
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            path = f'{prefix}.{key}' if prefix else str(key)
            if isinstance(item, dict):
                collect(item, path)
            elif _numeric(item):
                totals[path] += item

    for record in records:
        collect(record.get('usage'))
    return dict(totals)


def format_report(records: list[dict], *, title: str) -> str:
    groups = {record.get('group_id') for record in records if record.get('group_id') is not None}
    lines = [f'# {_text(title)}', '',
             f'样本数：{len(records)}；独立 group 数：{len(groups)}。', '',
             f'- source 分布：{_distribution(record.get("source", "unknown") for record in records)}。',
             f'- status 分布：{_distribution(record.get("status", "unknown") for record in records)}。',
             f'- split 分布：{_distribution(record.get("split", "unknown") for record in records)}。', '']
    missing = [record for record in records if record.get('status') == 'offline_missing']
    if missing:
        lines.extend(['离线缓存不完整，不能形成准确率结论。以下仅列缓存缺失情况，不汇总已有缓存的部分成绩。', '',
                      '| 图片 | group | 场景 | 状态 |', '| --- | --- | --- | --- |'])
        lines.extend(f'| {_text(record.get("image", ""))} | {_text(record.get("group_id", ""))} | '
                     f'{_text(record.get("scene", ""))} | offline_missing |' for record in missing)
        return '\n'.join(lines) + '\n'

    aggregate = aggregate_scores([record['score'] for record in records])
    counts = aggregate['counts']
    thresholds = sorted({record['score'].get('iou_threshold', .5) for record in records}) or [.5]
    threshold_description = '、'.join(f'IoU ≥ {threshold:g}' for threshold in thresholds)
    lines.extend(['## 评分口径与汇总', '',
                  f'使用归一化边界框 {threshold_description}（各图按其评分阈值）做一对一几何匹配，'
                  '先最大化匹配数，再最大化总 IoU；属性不参与匹配。'
                  '失败请求、漏件和未作答均保留在应识别真值分母中。颜色按精确集合比较。', '',
                  f'- 定位 precision：{_percent(aggregate["precision"])}（{counts["tp"]}/{counts["predicted"]}）；'
                  f'recall：{_percent(aggregate["recall"])}（{counts["tp"]}/{counts["truth"]}）。',
                  f'- 联合正确率：{_percent(aggregate["joint_accuracy"])}'
                  f'（{counts["joint_correct"]}/{counts["joint_total"]}，所有可观察字段同时正确）。',
                  f'- 检测数量全对率：{_percent(aggregate["count_accuracy"])}'
                  f'（{counts["count_correct"]}/{len(records)}，全部真值与预测均匹配）。',
                  f'- 原始数量相等率：{_percent(aggregate["raw_count_accuracy"])}'
                  f'（{counts["raw_count_correct"]}/{len(records)}；框错不算检测数量全对）。',
                  f'- 多报：{counts["fp"]}；漏件：{counts["fn"]}；缺框/非法框：{counts["unlocalized"]}。',
                  f'- 不可观察字段赋值：{counts["unsupported"]}/{counts["unobservable_total"]}'
                  '（只统计已匹配对象的不可观察字段机会）。', '',
                  '## 字段覆盖与正确率', '',
                  '| 字段 | 正确/应识别 | 正确率 | 已作答/应识别 | 字段覆盖 |',
                  '| --- | --- | --- | --- | --- |'])
    for field in FIELDS:
        values = aggregate['fields'][field]
        lines.append(f'| {_FIELD_NAMES[field]} | {values["correct"]}/{values["total"]} | '
                     f'{_percent(values["accuracy"])} | {values["answered"]}/{values["total"]} | '
                     f'{_percent(values["coverage"])} |')
    lines.extend(['', '合法且非 unknown 的错误答案仍计已作答；unknown/非法值降低覆盖率。'
                  '无可观察字段的对象不能凭空计为联合正确；成功空负例计数量全对，但属性指标无分母。', '',
                  '## 场景分层', '', '| 场景 | 图片数 | 真值件数 | precision | recall | 联合正确率 |',
                  '| --- | --- | --- | --- | --- | --- |'])
    scenes = defaultdict(list)
    for record in records:
        scenes[str(record.get('scene', 'unknown'))].append(record['score'])
    for scene, scores in sorted(scenes.items()):
        values = aggregate_scores(scores)
        lines.append(f'| {_text(scene)} | {values["images"]} | {values["counts"]["truth"]} | '
                     f'{_percent(values["precision"])} | {_percent(values["recall"])} | '
                     f'{_percent(values["joint_accuracy"])} |')

    lines.extend(['', '## 真值类别分层', '', '| 真值类别 | 真值件数 | 匹配件数 | recall | 联合正确率 |',
                  '| --- | --- | --- | --- | --- |'])
    categories = defaultdict(lambda: {'total': 0, 'matched': 0, 'joint': 0})
    for record in records:
        by_truth = {match['truth_index']: match for match in record['score']['matches']}
        for index, truth in enumerate(record.get('truths', [])):
            values = categories[str(truth.get('category') or 'unobservable')]
            values['total'] += 1
            match = by_truth.get(index)
            if match is not None:
                values['matched'] += 1
                values['joint'] += int(match['joint_correct'])
    for category, values in sorted(categories.items()):
        lines.append(f'| {_text(category)} | {values["total"]} | {values["matched"]} | '
                     f'{_percent(values["matched"] / values["total"])} | '
                     f'{_percent(values["joint"] / values["total"])} |')

    lines.extend(['', '## 耗时与 usage', ''])
    live = [record['elapsed_ms'] for record in records if record.get('source') == 'live' and
            _numeric(record.get('elapsed_ms'))]
    cached = [record['elapsed_ms'] for record in records if record.get('source') in ('cache', 'cached') and
              _numeric(record.get('elapsed_ms'))]
    returns = [record['return_ms'] for record in records if _numeric(record.get('return_ms'))]
    lines.extend([_time_line('本次 live 模型调用耗时（含失败请求）', live),
                  _time_line('cached 历史模型调用耗时', cached),
                  _time_line('本次返回耗时（含缓存读取）', returns)])
    usage = _usage(records)
    lines.append('- usage 累计（cached 为历史调用 usage）：' +
                 ('、'.join(f'{_text(key)}={value:g}' for key, value in sorted(usage.items())) or '无可用记录') + '。')
    lines.extend(['', 'cached 记录不代表本次 live 调用。P50/P95 为记录耗时的线性插值分位数。'
                  '本报告不推断费用、95% 区间或上线门槛通过情况。', '', '## 逐图错误', '',
                  '| 图片 | group | 场景 | source/status | 错误 |', '| --- | --- | --- | --- | --- |'])
    for record in records:
        errors = record['score']['errors']
        descriptions = []
        for error in errors:
            description = _ERROR_NAMES.get(error['type'], error['type'])
            if 'truth_index' in error:
                description += f' 真值#{error["truth_index"]}'
            if 'prediction_index' in error:
                description += f' 预测#{error["prediction_index"]}'
            if 'field' in error:
                description += f' {_FIELD_NAMES.get(error["field"], error["field"])}'
            if 'expected' in error:
                description += f' 期望={error["expected"]} 实际={error.get("actual")}'
            descriptions.append(_text(description))
        lines.append(f'| {_text(record.get("image", ""))} | {_text(record.get("group_id", ""))} | '
                     f'{_text(record.get("scene", ""))} | {_text(record.get("source", ""))}/'
                     f'{_text(record.get("status", ""))} | {"；".join(descriptions) or "无错误"} |')
    return '\n'.join(lines) + '\n'
