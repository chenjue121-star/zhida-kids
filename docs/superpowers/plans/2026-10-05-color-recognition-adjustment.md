# Color Recognition Adjustment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 测出颜色分层及部位检查提示对Lite、Qwen两项严格标签一致指标的影响，最多32次新请求。

**Architecture:** 只扩展评测入口以显式选择自定义提示。评测适配器复用生产HTTP/JSON/归一化路径，保留分层原始候选并计算主色＋明显次色集合。原生产提示、旧缓存身份、确认标签及评分器保持不变。

**Tech Stack:** Python、httpx、pytest、现有 `eval.recognition_v2.runner` 与 `crop_pilot`。

---

### Task 1: 评测提示适配与缓存身份

**Files:**
- Create: `backend/eval/recognition_v2/color_prompt.py`
- Modify: `backend/eval/recognition_v2/runner.py`
- Test: `backend/tests/v2/test_eval_color_prompt.py`
- Regression: `backend/tests/v2/test_eval_v2_runner.py`, `backend/tests/v2/test_crop_pilot.py`

- [x] 先写MockTransport测试并验证失败：同一图使用原/新prompt必须隔离缓存；实际HTTP正文的prompt hash必须等于身份；默认行为兼容。
- [x] 新模块提供 `COLOR_ROLE_PROMPT` 及评测provider工厂。原JSON解析仍用于类别等字段；严格验证三个颜色数组，互斥、枚举合法，主色非空，unknown不得与已知主色混合；按原数组顺序去重拼接主色、明显次色。
- [x] provider结果的 `raw_candidates` 保留 `primary_colors`、`secondary_colors`、`accent_colors`；`colors` 是前两者的规范合集。失败使用现有 `RecognitionFailure`，不要将模型不合格角色静默修正为成功。
- [x] runner增加显式可选prompt参数，使实际发送的全文与身份哈希一致；自定义适配器hash参与新模式身份，默认模式身份结构和请求不变。自定义缓存回读也验证角色与 `colors` 一致；篡改或角色缺失视缓存无效。
- [x] 请求预算、离线不联网、预处理和评分不变；自定义结果中的usage只保留现有数值白名单。评测导入不得加载env或创建HTTP连接。
- [x] 覆盖类别字段不丢、角色非法/重叠/缺失失败、raw role保留、原始候选校验、paid response缓存前可写校验的测试。
- [x] 运行隔离纯测试：

```sh
.venv/bin/python -m pytest -c /dev/null --rootdir=. -p no:cacheprovider --confcutdir=tests/v2 tests/v2/test_eval_color_prompt.py tests/v2/test_eval_v2_runner.py tests/v2/test_crop_pilot.py
```

- [x] 先做规格符合性独立复核，之后做代码质量复核；无阻碍后才授权真实模型调用。不要读取密钥或调用真实API来做实现测试。

### Task 2: 同一冻结输入实测

**Files:**
- Read: `backend/eval/outfits_v2/dataset/desktop-2026-10-05/prepared/cases.json`, `garments.json`, `confirmation.json`
- Output: `backend/eval/outfits_v2/dataset/desktop-2026-10-05/runs/color-role-lite`, `color-role-qwen`

- [x] 用 `derive_crop_pilot(...)` 重建并校验16图及truth，与两模型基线逐项一致。
- [x] root仅在模型进程内读取指定环境字段；凭据值不打印、不写入报告。预检输出与缓存可写，输出目录不能覆盖旧跑次。
- [x] 记录完整 `COLOR_ROLE_PROMPT` 与源码hash。每模型 `CallBudget(16)`，第一图成功后继续，逐次保存记录；基础设施错误停止、不自动重试。
- [x] 调用显式prompt评测模式，读取同一组16JPEG并传入 `expected_sha256`；使用基线型号、URL、温度0、4096输出、JSON对象与关闭思考参数。
- [x] `score_pilot(pilot, records)` 对原truth重评分；请求失败/多报/漏报保留固定16分母，额外角色不算新真值。

### Task 3: 两指标与误差对照

**Files:**
- Output: `backend/eval/outfits_v2/dataset/desktop-2026-10-05/runs/color-role-comparison-2026-10-05/{comparison.json,report.md,verification.json}`
- Update: `docs/design/model-selection-2026-10-05.md`

- [x] 独立重算每模型原/新颜色集合一致、联合一致，枚举修复、保持错误、新增错误，记录角色与原truth差异。
- [x] 按实际usage折算费用：Lite/Qwen输入0.8元、输出2.7元每百万token；标准价不是实际账单。
- [x] 不修改原标签，不把改变评价标准的分数当作改进；报告本轮为开发集调优，尚无新的泛化证据。
- [x] 验证原输入、标签和生产文件hash未变化，源报告hash与模型一致，模型调用数≤32，`git diff --check`通过。
- [x] 打开结果报告，向用户报告两个指标实际变化与下一步取舍。若没有提升，明确保留基线方案。

本轮不提交Git、不部署；用户已批准上述颜色口径及“调整后实测”，直接在现有隔离worktree执行。

完成记录：2026-10-05。108项离线检查通过；Lite/Qwen各16次实测，共32次。原图、truth、评分器、生产hash不变。Qwen颜色10→12、联合10→11；Lite颜色12→10、联合12→9，含1次角色校验失败，保持原识别基线。报告及验证记录已保存，已请求在Codex打开报告（UI返回queued）。
