# 新版识别评测基础实施计划

> **For agentic workers:** Use subagent-driven-development to execute the independent tasks below, followed by integration and independent review. Preserve all existing uncommitted A/B/C work.

**Goal:** 建立可复核、默认离线、连接新版多件识别接口的评测入口，为真实模型选型准备证据。

**Architecture:** 新建 `backend/eval/recognition_v2/`，将数据审计、人工标签、候选匹配评分、版本化缓存与命令行分开。复用生产 Qwen/ARK adapter 和图片处理，不导入旧应用、不加载数据库、不自动读取真实配置。旧 A/B 命令的 dry-run 同时修复为严格离线。

**Tech Stack:** Python 3.13、Pillow、pytest、标准库 JSON；生产 adapter 使用已有 httpx。

用户「下一步」接受上一轮的评测优先建议。本轮交付评测工具、样本清单与操作说明；已有四幅独立图仅用于诊断，人工标签不自动猜测。真实模型结果、模型胜负和实际成本只有后续审核样本与明确启用在线运行后才能产生。

## 共享契约

审核标签 JSON：`{"schema_version":1,"entries":[...]}`。每项含 `image`、原文件 `sha256`、`group_id`（同实物/家庭拍摄组）、`split`（development/calibration/test）、`scene`、`reviewed`、`objects`。骨架的审核字段为空，`reviewed=false, objects=null`。正式评测只接受人工审核且字段完整的标签；负例必须明确 `objects=[]`。

对象含稳定 `id`、归一化 `bbox=[x0,y0,x1,y1]`、`category/colors/pattern/thickness` 和 `observable` 字段列表。观察得到的字段必须是新版合法枚举且非 unknown；不可观察字段为空并不加入属性分母。鞋袜按一双、两件套拆件、连体衣为一件。相同原文件内容不得重复入评测；相同 group_id 不得跨 split。

评分函数 `score_image(predictions, truths, *, status='ok', iou_threshold=0.5)` 使用几何位置一对一匹配，最大化匹配数量再最大化 IoU，不能用类别匹配掩盖类别错误。缺框预测保留并计未匹配，多报/漏件/请求失败单列。每字段统计正确、作答、应评分数；联合正确率以全部真值对象为分母；零分母返回 null，不输出虚假 100%。不可观察字段被模型赋值作为无依据建议单列。

运行记录包含 source（live/cache/offline_missing）、status、candidates、模型/供应商/提示词/参数/预处理/字典/归一化版本、图片内容哈希、耗时、usage。缓存身份包含上述输入版本与重复编号；失败不缓存。默认 offline，缺缓存不能联网或出准确率结论；在线运行须显式 live 与最大调用数，密钥仅按明确环境变量加载。

## Task 1：图片审计与人工标签

Files: create `backend/eval/recognition_v2/{__init__,dataset}.py`; create `backend/tests/v2/test_eval_v2_dataset.py`.

- [x] 先写回归用例：坏图不可解码、同内容重复、文件名穿越、未经审核拒绝、内容变更拒绝、重复图片拒绝、同组跨集合拒绝、可观察字段非法值拒绝。
- [x] 运行 `.venv/bin/python -m pytest -c pytest-v2.ini tests/v2/test_eval_v2_dataset.py`，确认新增行为尚未实现。
- [x] 实现 `audit_images(image_dir)`，返回 total/valid/unique_valid/invalid/duplicates 与逐文件 entries；不移动或删除原文件。
- [x] 实现 `scaffold_manifest(audit)` 与 `load_manifest(path, image_dir, *, split=None)`，输出/验证上述标签契约；独立测试转绿。

## Task 2：多候选评分与报告

Files: create `backend/eval/recognition_v2/{scorer,report}.py`; create `backend/tests/v2/test_eval_v2_scoring.py`.

- [x] 先写断言：两对象框相同类别相反仍匹配位置且类别判错；重复预测为多报；缺框为未定位；失败造成全部真值未完成；空负例不会得到属性满分；unknown 降低完成覆盖；不可观察厚薄赋值单列。
- [x] 运行新增用例确认红灯，再实现 IoU、最大基数一对一匹配、`score_image`、`aggregate_scores(results)`。
- [x] 实现 `format_report(records, *, title)`，给出样本数、状态、precision/recall、数量、联合字段与字段覆盖、分场景/类别、逐图错误、P50/P95 与 usage；结果含离线缺缓存时明确不产出准确率结论。
- [x] 报告明确独立组数、人工标签条件、缓存/桩数据边界；不将项目目标写成实测成绩。

## Task 3：旧入口严格离线

Files: modify `backend/eval/recognition/{runner,ab_compare}.py` and README; create `backend/tests/v2/test_eval_legacy_offline.py`.

- [x] 先写 asyncio.run 用例，注入会记录调用的 recognizer；offline 且缺缓存必须异常且调用数为零。
- [x] 添加 `OfflineCacheMiss` 和 `offline=False`；将旧 recognizer 导入延迟到获准真实调用时。
- [x] `--dry-run` 将 offline 参数逐层传递；缺缓存返回清楚的非零退出，无部分成功报告；offline 与 yes 的冲突不能开启联网。
- [x] 更新旧 README，标明仍为旧版单件评测，不能测新版多件；验证历史缓存命中行为。

## Task 4：新版运行器与命令行

Files: create `backend/eval/recognition_v2/{runner,compare,__main__}.py`; create `backend/tests/v2/test_eval_v2_runner.py`, `test_eval_v2_cli.py`; create new README.

- [x] 先验证缓存键对图片内容、模型、参数、版本与 repeat 敏感；offline 缺缓存不实例化 provider；live 调用上限按未命中计数；生产 normalize 不丢候选；失败保留在分母；缓存响应与 live 响应清晰区分。
- [x] 使用生产图片预处理与 QwenProvider/ArkProvider，无数据库/应用导入；只有 live 才创建 provider。复用生产 PROMPT 与 normalize_result。
- [x] CLI 提供 audit/scaffold/compare 三入口；JSON/Markdown 输出不覆盖已有文件，除非显式 overwrite；scaffold 不自动创建真值。compare 默认离线，live 必须提供 max-calls。
- [x] 记录每模型完整配置与实际 usage；费用仅提供 token 统计，不用未核实单价自动估算；在线结果写版本化缓存。

## Task 5：整合、审核与交付

- [x] 运行全量 V2 测试与新增评分/CLI 回归；人工执行真实图片 audit、骨架生成和缺缓存离线运行，证明无模型请求。
- [x] 独立评审先检查与上述契约一致，再检查评分/缓存/路径/错误处理质量；修复重要问题并重跑针对性验证。
- [x] 保存审计结果、未审核标签骨架、样本采集与标注说明、验证记录。完成后只报告工具成果，不宣称识别准确率已提高。

复用现有 `codex/phase-a` 隔离工作树；本轮不替用户提交、合并既有未提交内容。
