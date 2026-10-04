from __future__ import annotations

import argparse
import asyncio
import importlib
from pathlib import Path
from statistics import mean

from eval.recognition.labels import load_labels
from eval.recognition.report import format_comparison
from eval.recognition.runner import OfflineCacheMiss, run_recognition
from eval.recognition.scorer import FIELD_WEIGHTS, composite, score_fields

HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset"
IMAGES = DATASET / "images"
LABELS = DATASET / "labels.yaml"
CACHE = HERE / ".cache"

_FIELDS = list(FIELD_WEIGHTS.keys())


def aggregate_scores(per_image: list[dict[str, float]]) -> dict[str, float]:
    """把多张图的 per-field 分数聚合为均值，并算 composite 均值。"""
    agg: dict[str, float] = {}
    for f in _FIELDS:
        agg[f] = round(mean(img[f] for img in per_image), 4) if per_image else 0.0
    agg["COMPOSITE"] = round(mean(composite(img) for img in per_image), 4) if per_image else 0.0
    return agg


def _load_prompt(name: str) -> str:
    mod = importlib.import_module(f"eval.recognition.prompts.{name}")
    return mod.build_prompt()


def scaffold_labels(*, overwrite: bool = False) -> None:
    names = sorted(p.name for p in IMAGES.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    lines = []
    for n in names:
        lines.append(f"- image: {n}")
        lines.append("  type: ")
        lines.append("  sub_type: \"\"")
        lines.append("  main_color: ")
        lines.append("  pattern: \"\"")
        lines.append("  season: []")
        lines.append("  thickness: ")
        lines.append("  style_tags: []")
    with LABELS.open('w' if overwrite else 'x', encoding='utf-8') as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"已生成标注骨架 {LABELS}（{len(names)} 张图），请手工填写后再跑对比。")


async def _score_prompt(prompt_text: str, labels: list[dict], repeat: int, use_cache: bool, *, offline: bool = False) -> dict:
    per_image: list[dict[str, float]] = []
    for entry in labels:
        run_scores: list[dict[str, float]] = []
        for r in range(repeat):
            predicted = await run_recognition(
                image_path=IMAGES / entry["image"],
                image_name=entry["image"],
                prompt_text=prompt_text,
                run_index=r,
                cache_dir=CACHE,
                use_cache=use_cache,
                offline=offline,
            )
            run_scores.append(score_fields(predicted, entry))
        avg = {f: round(mean(s[f] for s in run_scores), 4) for f in _FIELDS}
        per_image.append(avg)
    return aggregate_scores(per_image)


async def _run(args: argparse.Namespace) -> int:
    if args.repeat <= 0 or args.limit < 0:
        print('--repeat 必须为正整数，--limit 必须为非负整数。中止。')
        return 2
    labels = load_labels(LABELS)
    if args.limit:
        labels = labels[: args.limit]
    n_calls = len(labels) * 2 * args.repeat
    if args.dry_run:
        print(f"离线模式：读取 {n_calls} 份缓存，不发起模型调用。")
    else:
        print(f"最多进行 {n_calls} 次 ARK 调用（{len(labels)} 图 × 2 提示词 × {args.repeat} 次，缓存命中会减少调用）。")
    if not args.dry_run and not args.yes:
        print("需加 --yes 确认计费，或加 --dry-run 仅用缓存。中止。")
        return 1
    use_cache = True
    base_prompt = _load_prompt(args.baseline)
    var_prompt = _load_prompt(args.variant)
    try:
        base_scores = await _score_prompt(base_prompt, labels, args.repeat, use_cache, offline=args.dry_run)
        var_scores = await _score_prompt(var_prompt, labels, args.repeat, use_cache, offline=args.dry_run)
    except OfflineCacheMiss as exc:
        print(f'离线缓存不足，未生成评分报告：{exc}')
        return 2
    report = format_comparison(args.baseline, args.variant, base_scores, var_scores, len(labels))
    print("\n" + report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"\n已写入 {args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="识别提示词 A/B 对比")
    parser.add_argument("--baseline", default="baseline")
    parser.add_argument("--variant", default="variant_example")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default="")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scaffold", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="允许 --scaffold 覆盖已有人工标签")
    args = parser.parse_args()
    if args.scaffold:
        try:
            scaffold_labels(overwrite=args.overwrite)
        except FileExistsError:
            print(f'标签文件已存在，未覆盖：{LABELS}。确需重建时使用 --scaffold --overwrite。')
            return 1
        return 0
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
