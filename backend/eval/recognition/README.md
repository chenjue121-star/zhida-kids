# 识别 A/B 评估

离线评估衣物识别准确度的工具。纯函数（scorer/labels/report）有 CI 测试守护；
runner/ab_compare 会调用真实 ARK，不进 CI。

约定：用项目虚拟环境解释器运行，下文记作
`PY=/Users/ll/Documents/智搭（儿童）/backend/.venv/bin/python`，命令均从 `backend/` 执行。

## 一次完整流程

1. 生成标注骨架：`$PY -m eval.recognition.ab_compare --scaffold`
2. 人工编辑 `dataset/labels.yaml`，按肉眼填 `type` / `main_color` / `thickness` 等
   （合法枚举值见 `app/domain/vocab.py`；格式可参考 `dataset/labels.example.yaml`）。
3. 校验标注合法：
   `$PY -c "from eval.recognition.labels import load_labels; print(len(load_labels('eval/recognition/dataset/labels.yaml')), 'ok')"`
4. 跑基线 vs 变体（真实计费，需 `ARK_API_KEY`）：
   `ARK_API_KEY=... $PY -m eval.recognition.ab_compare --baseline baseline --variant variant_example --repeat 2 --yes --out report.md`
5. 看 `report.md` 的 `COMPOSITE` 与各字段 Δ。变体更优则把其提示词文本提升进
   `app/services/recognition/prompt.py` 的 `_recognition_prompt()`，并记录评估数字。
6. 仅用已有缓存、不计费（管线冒烟）：用 `--dry-run` 替代 `--yes`
   （注意：dry-run 下若某 (图,提示词,run) 缺缓存，仍会触发该次联网）。

## 新增提示词变体

在 `prompts/` 下新建 `variant_<name>.py`，导出 `build_prompt() -> str`
（可在 baseline 基础上改写，或独立编写完整文本），再用 `--variant <name>` 对比。
`baseline` 始终引用生产实现，无需维护。

## 成本守护

`ab_compare` 启动时打印预计调用次数（图片数 × 2 提示词 × repeat），
非 `--dry-run` 时必须显式加 `--yes` 才会真正发起调用。结果按
(图片, 提示词哈希, run-index) 缓存到 `.cache/`（已 gitignore），重复跑报告不重复计费。
