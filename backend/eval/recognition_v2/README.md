# 新版多件衣物识别评测

本工具连接生产 v2 的 Qwen／ARK adapter、图片预处理和候选归一化。审核标签与原模型建议分开；默认严格离线，缓存缺失不会联网，也不会用部分成绩制造模型排名。

截至 2026-10-03，工具和桩数据回归已完成，尚未开展真实模型对测。原有 20 个文件中只有 4 种独立有效文件内容；现已按用户指示另整理 [桌面 47 图诊断集](dataset/desktop-2026-10-03/README.md)，47 张商品截图均有效、无文件重复，逐图 AI 草稿仍待人工审核。正式项目准确率仍未知。采集与审核步骤见 [样本采集说明](../../../docs/runbooks/recognition-evaluation.md)。

## 入口

从当前工作树的 `backend/` 执行，使用现有 Python 3.13 虚拟环境：

```sh
.venv/bin/python -m eval.recognition_v2 --help
```

### 1. 审计原始图片

```sh
.venv/bin/python -m eval.recognition_v2 audit \
  --images eval/recognition/dataset/images \
  --out eval/recognition_v2/dataset/audit.json
```

审计目录第一层 JPEG／PNG／WebP 文件：真实解码、EXIF 转正后的尺寸、原文件 SHA256、重复关系和错误。保留所有原文件，审计只写指定报告。`audit-2026-10-03.json` 已保存本轮真实审计；重复按原字节识别，不代表自动识别同一实物的不同角度。

### 2. 生成人工审核骨架

```sh
.venv/bin/python -m eval.recognition_v2 scaffold \
  --images eval/recognition/dataset/images \
  --out eval/recognition_v2/dataset/labels.new-draft.json
```

只为独立、可解码照片生成条目。`reviewed=false`、`objects=null`，不猜衣物真值。本轮已有 `dataset/labels.draft.json`；人工核对完成的条目应另存 `labels.reviewed.json`，未完成条目留在草稿中。

所有输出默认拒绝覆盖。需要替换旧报告时显式使用 `--overwrite`，但该选项也不能覆盖图片目录内的任何路径、输入标签或模型配置。

### 3. 检查审核标签

```sh
.venv/bin/python -c "from eval.recognition_v2.dataset import load_manifest; print(len(load_manifest('eval/recognition_v2/dataset/labels.reviewed.json', 'eval/recognition/dataset/images')), 'reviewed samples')"
```

标签结构见采集说明。审核、内容 hash、枚举、边界框、重复、group 与 split 泄漏会被检查。先验证全清单，再选择 split；只有已审核条目进入正式清单。

### 4. 严格离线重放

```sh
.venv/bin/python -m eval.recognition_v2 compare \
  --images eval/recognition/dataset/images \
  --manifest eval/recognition_v2/dataset/labels.reviewed.json \
  --models eval/recognition_v2/models.example.json \
  --split test \
  --out eval/recognition_v2/results/comparison.md \
  --json-out eval/recognition_v2/results/comparison.json
```

不会读取 `.env`、创建 provider 或发送模型请求。任一模型缺缓存时，返回码 3，报告只列缺失情况，全部模型暂停成绩汇总。未审核标签直接返回码 2，不生成准确率报告。

缓存身份包含原图片内容、provider、请求模型、端点、提示词、参数、预处理、归一化、字典、三种生产 adapter 源码和 repeat 编号。换模型、图片或链路版本均不能借用旧响应。旧 `eval/recognition/.cache` 不能作为新版缓存。

### 5. 有审核样本后开展在线对测

在允许的测试账号中开通模型，并通过模型配置的 `api_key_env` 指定进程环境变量；工具不会读取本地密钥文件，也不接受配置 JSON 内写入密钥。端点应按账号所在区域确认，示例沿用当前项目默认地址。

```sh
.venv/bin/python -m eval.recognition_v2 compare \
  --images eval/recognition/dataset/images \
  --manifest eval/recognition_v2/dataset/labels.reviewed.json \
  --models eval/recognition_v2/models.example.json \
  --split development \
  --repeat 1 \
  --live --max-calls 300 \
  --out eval/recognition_v2/results/diagnostic.md \
  --json-out eval/recognition_v2/results/diagnostic.json
```

300 是“100 图 × 3 模型 × 1 次”的调用次数上限示例，不是金额预算，也不意味着这轮已经有 100 张图。实际新调用数按缺缓存统计，超出上限或缺密钥时整轮先停止，尚不调用模型。缓存命中不计新调用。单次请求沿用生产 60 秒超时；本工具不自动复核、不盲重试，失败也保留在分母。

`models.example.json` 是 Qwen Plus、Seed Lite、Seed Pro 的候选配置，不是准确率冠军列表。模型 ID、区域权限和可用性以账号实际服务为准。每次记录供应商返回的实际模型名，避免只看配置别名。

## 指标与边界

- **原图端到端检测：** IoU≥0.5 一对一匹配，先最大化匹配数，再最大化 IoU。属性不参与匹配，避免把分类错误藏在匹配中。缺框、错框、重复和漏件均计入。
- **字段：** 类别、颜色集合、图案、厚薄；合法非 unknown 答案计作答，错误答案也计作答。正确/全部真值可观察字段是完成正确率，作答/同分母是覆盖率；不可观察字段不进入属性分母。
- **联合正确：** 同一真值对象的可观察字段全部正确且正确定位。漏件、失败、未知均不能被均值掩盖。无可观察字段不能凭空算联合正确。
- **数量：** 原始件数相同与全部候选正确匹配分开报告。成功空负例可计数量正确，但没有属性准确率分母。
- **未知：** 已匹配对象的不可观察字段被模型赋值，单列无依据建议。它不与字段正确率混为一个分数。
- **延迟：** live 调用、缓存中的历史调用和本次返回耗时分别给 P50/P95。缓存结果不是本次真实 API 烟测。
- **费用：** 保存真实可获得的 usage，已收到 usage 的无效结果也保留；供应商失败时没有 usage 不代表费用为零。不套用未核实单价计算人民币费用。
- **分层：** 场景、真值类别、逐图错误、图片数和独立 group 数。重复运行不是新增独立样本；本工具不生成置信区间或自动判定上线门槛。

当前是原图端到端评测。无框预测即使描述看似正确，也不算定位完成；“已定位对象的属性能力”与“人工裁剪后的属性能力”需要另设实验，不能把它们当成同一种准确率。

工具复用当前七大类别词表，尚不评分袖长、裤长、材质、适龄、是否拥有、归属、合身或待洗状态。鞋袜计数规范进入人工标签后，应观察生产提示词是否遵守，而不是后处理悄悄合并候选。

人工确认负担（修改次数、补漏、确认耗时）需在真实试用中收集；离线模型输出无法测出这部分。本轮没有伪造用户体验数据。

## 返回码

| 码 | 含义 |
| --- | --- |
| 0 | 审计／骨架生成完成，或所有评测请求有有效结果 |
| 2 | 配置、标签、输出路径或调用预算条件不满足 |
| 3 | 严格离线缓存不完整，没有可比较成绩 |
| 4 | 评测完成但含模型／输入失败；失败已进入报告分母 |

## 验证

```sh
.venv/bin/python -m pytest -c pytest-v2.ini
```

新测试使用人工构造图片、缓存和 fake provider，不调用真实模型。全量回归包括已有家庭权限、批次确认、恢复、迁移与真实本地 HTTP 契约。
