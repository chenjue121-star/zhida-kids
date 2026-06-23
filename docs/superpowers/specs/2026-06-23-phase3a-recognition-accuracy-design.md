# Phase 3a — 识别准确度评估与优化

**日期:** 2026-06-23
**范围:** 仅衣物识别（recognition）的准确度评估与提示词优化。搭配质量留作 Phase 3b 独立 spec。
**性质:** 离线评估工具 + 数据驱动的提示词迭代。改变 AI 行为，但以可量化指标守护。

## 背景与目标

识别管线已在 Phase 1 重构为独立模块（`app/services/recognition/`）：
单次调用 ARK/doubao，按严格枚举返回画面中最显眼的一件衣物，再经 `_normalize_recognition`
做别名/模糊归一。

问题：当前没有任何方式**度量**识别准确度，因此每次改提示词都是无法验证的猜测。

**核心目标：** 先建立可量化的 A/B 评估基建，再在其守护下迭代提示词 —
就像 Phase 1 先建特征测试再重构一样，本阶段先建评估集再调优。

**Phase 3a 完成定义（DoD）：**
1. A/B 评估基建建成，纯逻辑部分有 CI 测试；
2. 评估集完成人工标注；
3. 跑出 baseline 基线分数；
4. 至少有一个在 composite 指标上超过 baseline 的提示词变体被提升进
   `app/services/recognition/prompt.py`，并记录评估数字。

DoD 之后的持续提示词调优是开放式的，由使用者自行驱动。

## 架构与组件

全部位于新目录 `backend/eval/`（离线工具，独立于 `app/` 与 `tests/`，因为它会发起真实 API
调用，且不进 CI）：

```
backend/eval/
  recognition/
    dataset/
      images/                 # 评估图片（从 uploads/ 复制 + 后续自行新增）
      labels.yaml             # 人工标注的 ground truth，每图一条
      labels.example.yaml     # 2-3 条填好的样例模板
    prompts/
      baseline.py             # 当前 _recognition_prompt() 的快照
      variant_*.py            # 待测提示词变体
    scorer.py                 # 逐字段评分逻辑（纯函数，CI 测试）
    labels.py                 # labels.yaml 加载 + 枚举校验（CI 测试）
    runner.py                 # 对每个 (image, prompt) 调 ARK，收集原始输出（不进 CI）
    ab_compare.py             # CLI 入口：两个提示词跑全集、对比分数、出报告
    report.py                 # 格式化对比报告
    .cache/                   # 原始响应缓存（gitignore），按 (image, prompt-hash, run) 键
```

**关键设计点：**
- **提示词变体是一等公民。** 每个变体是一个模块，导出 `build_prompt() -> str`。
  `baseline.py` 是冻结的当前提示词。A/B runner 可 import 任意两个对比。变体胜出后，
  把其文本提升进真实的 `app/services/recognition/prompt.py`。
- **runner 复用真实识别路径** —— 调用 app 同款 ARK client + `_normalize_recognition`，
  只替换提示词字符串，使评估结果反映真实生产行为，而非平行重写。
- **`scorer.py` 是纯函数且 CI 可测** —— 输入（预测 dict, 期望 dict）→ 各字段分数。
  这是唯一可确定性单测的部分，进 `backend/tests/`。
- **网络调用仅限 `runner.py`，永不进 CI。**

## 评估集与标注格式

**图片：** 把现有 `uploads/` 的 ~20 张图复制进 `dataset/images/`，重命名为稳定 slug
（如 `img001.jpg`），使标注不依赖上传哈希。后续放新文件并补标注即可。

**`labels.yaml`** —— 每图一条，人工按肉眼填写 ground truth：

```yaml
- image: img001.jpg
  type: top              # 必填字段
  sub_type: hoodie       # 不适用/不确定填 ""
  main_color: pink       # 必填
  pattern: stripe
  season: [autumn, spring]
  thickness: normal      # 必填
  style_tags: [cute, casual]
  # brand/size 故意省略 —— 不参与评分
```

**规则（写入设计）：**
- 字段值必须是 `domain/vocab.py` 的合法枚举键。harness **加载时校验**，遇未知枚举值
  大声报错（捕捉手工标注的拼写错误）。
- 每条 label 必须有 `type`、`main_color`、`thickness`。`sub_type`/`pattern` 可为 `""`；
  `season`/`style_tags` 可为 `[]`。
- `season` 与 `style_tags` 在评分时按无序集合处理。
- 随附 `labels.example.yaml`（2-3 条填好）作模板，标注前格式无歧义。
- harness 提供 `--scaffold`：预生成所有图片、字段留空的 `labels.yaml` 骨架，
  使用者只填值、绝不手敲文件名。

## 评分指标

每个字段产出 [0,1] 分，再加权平均成 composite。

| 字段 | 评分方式 | 权重 |
|------|----------|------|
| type | 精确匹配 1.0 否则 0.0 | 0.25 |
| main_color | 精确匹配 | 0.20 |
| thickness | 精确匹配 | 0.15 |
| sub_type | 精确匹配；若 label 与预测都为 "" 记 1.0（正确弃权） | 0.15 |
| pattern | 同 sub_type 规则 | 0.10 |
| season | Jaccard 相似度（交集/并集；都为空集记 1.0） | 0.10 |
| style_tags | Jaccard 相似度 | 0.05 |

权重之和为 1.0；三个必填字段（type/main_color/thickness）合计 0.60，体现其重要性。
composite = Σ(字段分 × 权重)。数据集分数 = 所有图 composite 的平均。

## A/B 工作流、输出与成本守护

**CLI：**
```bash
python -m eval.recognition.ab_compare \
    --baseline baseline --variant variant_clearer_color \
    [--repeat 2] [--limit N] [--out report.md] [--yes] [--dry-run]
```

**流程：** 对每张图，用提示词 A 和 B 各调 ARK → 各自归一 → 各自对 label 评分 → 聚合。
因 ARK 非确定性，`--repeat N` 对每个提示词每图跑 N 次取平均，抚平 run 间抖动。
原始响应缓存到 `.cache/`，按 (image, prompt-hash, run-index) 键，重出报告不重复计费。

**报告（markdown 表）：**
```
Field         Baseline   variant_clearer_color   Δ
type            0.95           0.95              0.00
main_color      0.80           0.90             +0.10
thickness       0.60           0.75             +0.15
...
COMPOSITE       0.78           0.85             +0.07
```
外加逐图明细，便于检查某变体在哪些图上回退。

**成本守护：** 开跑前打印调用次数（`images × prompts × repeat`），需 `--yes`
（或交互确认）才继续，避免误触发上百次 API 调用。

## 测试

- `scorer.py` → CI 单测（确定性）：精确匹配、空字段弃权、Jaccard 部分匹配、加权数学。
- `labels.py` 加载/校验 → CI 单测：拒绝未知枚举值、强制三个必填字段存在。
- `runner.py` / `ab_compare.py` → **不进 CI**（网络）。`--dry-run`（用缓存或桩响应）
  对管线接线做无 API 冒烟测试。

## 明确不做（YAGNI / 留作后续）

- 搭配推荐质量 —— Phase 3b 独立 spec。
- 归一化逻辑（`_normalize_recognition`）的重写 —— 仅在评估显示其为瓶颈时再纳入，本阶段先动提示词。
- 自动化标注 / 用 AI 生成 ground truth —— 标注由人工保证可信。
- 把评估纳入 CI 或定时跑 —— 评估是离线、按需、需 API key 的手动动作。
- 多模型对比（换识别模型）—— 本阶段固定 ARK/doubao，只比提示词。
