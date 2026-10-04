"""Geometry-first object scoring; failed requests and missing objects stay in denominators."""
from __future__ import annotations

from collections import Counter
from math import isfinite
from typing import Any, get_args

from app.v2.wardrobe.schemas import Category, Color, Pattern, Thickness

FIELDS = ('category', 'colors', 'pattern', 'thickness')
_VALUES = {field: set(get_args(kind)) - {'unknown'} for field, kind in
           zip(FIELDS, (Category, Color, Pattern, Thickness))}
_COUNT_KEYS = ('truth', 'predicted', 'tp', 'fp', 'fn', 'unlocalized', 'count_correct',
               'raw_count_correct', 'joint_correct', 'joint_total', 'unsupported', 'unobservable_total')


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _box(value: Any) -> tuple[float, ...] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           not 0 <= v <= 1 or not isfinite(v) for v in value):
        return None
    if value[0] >= value[2] or value[1] >= value[3]:
        return None
    return tuple(float(v) for v in value)


def _iou(first: tuple, second: tuple) -> float:
    overlap = max(0, min(first[2], second[2]) - max(first[0], second[0])) * \
        max(0, min(first[3], second[3]) - max(first[1], second[1]))
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return overlap / (first_area + second_area - overlap)


def _match(truth_boxes: list, prediction_boxes: list, threshold: float) -> list[tuple[int, int, float]]:
    """Min-cost maximum flow: cardinality first, then the greatest total IoU.

    Residual edges let an augmenting path replace a previous match. No category
    or other semantic value enters this assignment. Suitable for small batches.
    """
    count_truth, count_prediction = len(truth_boxes), len(prediction_boxes)
    sink = count_truth + count_prediction + 1
    graph: list[list[list]] = [[] for _ in range(sink + 1)]

    def edge(start: int, end: int, cost: float) -> list:
        forward = [end, len(graph[end]), 1, cost]
        backward = [start, len(graph[start]), 0, -cost]
        graph[start].append(forward)
        graph[end].append(backward)
        return forward

    for truth_index in range(count_truth):
        edge(0, truth_index + 1, 0)
    for prediction_index in range(count_prediction):
        edge(count_truth + prediction_index + 1, sink, 0)
    eligible = []
    for truth_index, truth_box in enumerate(truth_boxes):
        for prediction_index, prediction_box in enumerate(prediction_boxes):
            if truth_box is None or prediction_box is None:
                continue
            overlap = _iou(truth_box, prediction_box)
            if overlap >= threshold:
                link = edge(truth_index + 1, count_truth + prediction_index + 1, -overlap)
                eligible.append((truth_index, prediction_index, overlap, link))

    while True:
        distance = [float('inf')] * len(graph)
        previous: list[tuple[int, int] | None] = [None] * len(graph)
        distance[0] = 0
        # Bellman-Ford also handles reverse edges with positive costs.
        for _ in range(len(graph) - 1):
            changed = False
            for start, links in enumerate(graph):
                if not isfinite(distance[start]):
                    continue
                for link_index, link in enumerate(links):
                    end, _, capacity, cost = link
                    if capacity and distance[start] + cost < distance[end] - 1e-12:
                        distance[end] = distance[start] + cost
                        previous[end] = (start, link_index)
                        changed = True
            if not changed:
                break
        if previous[sink] is None:
            break
        end = sink
        while end:
            start, link_index = previous[end]
            link = graph[start][link_index]
            link[2] -= 1
            graph[end][link[1]][2] += 1
            end = start
    return [(truth_index, prediction_index, overlap)
            for truth_index, prediction_index, overlap, link in eligible if link[2] == 0]


def _answered(field: str, value: Any) -> bool:
    if field == 'colors':
        return isinstance(value, (list, tuple)) and bool(value) and all(
            isinstance(color, str) and color in _VALUES[field] for color in value)
    return isinstance(value, str) and value in _VALUES[field]


def _assigned(field: str, value: Any) -> bool:
    if field == 'colors' and isinstance(value, (list, tuple)):
        return any(color not in (None, '', 'unknown') for color in value)
    return value not in (None, '', 'unknown', [])


def _field_rates(fields: dict) -> dict:
    return {field: {**counts, 'accuracy': _ratio(counts['correct'], counts['total']),
                    'coverage': _ratio(counts['answered'], counts['total'])}
            for field, counts in fields.items()}


def score_image(predictions: list[dict], truths: list[dict], *, status: str = 'ok',
                iou_threshold: float = 0.5) -> dict:
    """Score candidates against every ground-truth object, without semantic matching.

    Field accuracy is correct / all observable truth fields; coverage is answered
    / that same denominator. Unsupported assignments count only matched objects,
    as does their unobservable opportunity denominator. No denominator means None.
    """
    if isinstance(iou_threshold, bool) or not isinstance(iou_threshold, (int, float)) or \
            not 0 < iou_threshold <= 1 or not isfinite(iou_threshold):
        raise ValueError('iou_threshold must be greater than 0 and at most 1')
    prediction_boxes = [_box(candidate.get('bbox')) for candidate in predictions]
    truth_boxes = [_box(truth.get('bbox')) for truth in truths]
    if any(box is None for box in truth_boxes):
        raise ValueError('truth bbox must be a valid normalized box')
    assignments = _match(truth_boxes, prediction_boxes, iou_threshold) if status == 'ok' else []
    fields = {field: {'correct': 0, 'answered': 0, 'total': 0} for field in FIELDS}
    for truth in truths:
        for field in set(truth.get('observable') or []) & set(FIELDS):
            fields[field]['total'] += 1
    matches, errors = [], []
    counts = {'truth': len(truths), 'predicted': len(predictions), 'tp': len(assignments),
              'fp': len(predictions) - len(assignments), 'fn': len(truths) - len(assignments),
              'unlocalized': sum(box is None for box in prediction_boxes),
              'count_correct': status == 'ok' and len(assignments) == len(truths) == len(predictions),
              'raw_count_correct': status == 'ok' and len(truths) == len(predictions),
              'joint_correct': 0, 'joint_total': len(truths), 'unsupported': 0, 'unobservable_total': 0}
    if status != 'ok':
        errors.append({'type': 'request_failed', 'status': status})
    for truth_index, prediction_index, overlap in assignments:
        truth, candidate = truths[truth_index], predictions[prediction_index]
        observable = set(truth.get('observable') or []) & set(FIELDS)
        field_results = {}
        for field in FIELDS:
            actual = candidate.get(field)
            answered = _answered(field, actual)
            observed = field in observable
            correct = observed and answered and (
                set(actual) == set(truth.get(field) or []) if field == 'colors' else actual == truth.get(field))
            field_results[field] = {'observable': observed, 'answered': answered, 'correct': bool(correct)}
            if observed:
                fields[field]['answered'] += int(answered)
                fields[field]['correct'] += int(correct)
                if not correct:
                    errors.append({'type': 'field_wrong' if answered else 'unanswered',
                                   'truth_index': truth_index, 'prediction_index': prediction_index,
                                   'field': field, 'expected': truth.get(field), 'actual': actual})
            else:
                counts['unobservable_total'] += 1
                if _assigned(field, actual):
                    counts['unsupported'] += 1
                    errors.append({'type': 'unsupported', 'truth_index': truth_index,
                                   'prediction_index': prediction_index, 'field': field, 'actual': actual})
        joint_correct = bool(observable) and all(field_results[field]['correct'] for field in observable)
        counts['joint_correct'] += int(joint_correct)
        matches.append({'truth_index': truth_index, 'prediction_index': prediction_index,
                        'truth_id': truth.get('id'), 'iou': overlap, 'fields': field_results,
                        'joint_correct': joint_correct})
    matched_truths = {match['truth_index'] for match in matches}
    matched_predictions = {match['prediction_index'] for match in matches}
    errors.extend({'type': 'missed', 'truth_index': index, 'truth_id': truth.get('id')}
                  for index, truth in enumerate(truths) if index not in matched_truths)
    errors.extend({'type': 'extra', 'prediction_index': index}
                  for index in range(len(predictions)) if index not in matched_predictions)
    errors.extend({'type': 'unlocalized', 'prediction_index': index}
                  for index, box in enumerate(prediction_boxes) if box is None)
    return {'status': status, 'iou_threshold': iou_threshold, 'counts': counts, 'fields': _field_rates(fields),
            'precision': _ratio(counts['tp'], counts['predicted']),
            'recall': _ratio(counts['tp'], counts['truth']),
            'joint_accuracy': _ratio(counts['joint_correct'], counts['joint_total']),
            'matches': matches, 'errors': errors}


def aggregate_scores(results: list[dict]) -> dict:
    """Sum integer numerators/denominators first; never average image accuracies."""
    counts = {key: sum(int(result['counts'][key]) for result in results) for key in _COUNT_KEYS}
    fields = {field: {key: sum(result['fields'][field][key] for result in results)
                      for key in ('correct', 'answered', 'total')} for field in FIELDS}
    return {'images': len(results), 'counts': counts, 'fields': _field_rates(fields),
            'precision': _ratio(counts['tp'], counts['predicted']),
            'recall': _ratio(counts['tp'], counts['truth']),
            'joint_accuracy': _ratio(counts['joint_correct'], counts['joint_total']),
            'count_accuracy': _ratio(counts['count_correct'], len(results)),
            'raw_count_accuracy': _ratio(counts['raw_count_correct'], len(results)),
            'status_counts': dict(Counter(result['status'] for result in results))}
