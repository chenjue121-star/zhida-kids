# 后端重构 Phase 1 — 特征测试 + 结构分层

**日期:** 2026-06-19
**范围:** 仅后端（FastAPI）。前端（小程序）重构留待独立阶段。
**性质:** 行为保持（behavior-preserving）的结构重构，零对外 API 变更。

## 背景与目标

`智搭儿童` 后端有两个"上帝文件"路由，职责严重混杂：

- `backend/app/routers/clothing.py`（968 行）
- `backend/app/routers/outfits.py`（945 行）

二者把 HTTP 路由、AI 调用、响应解析、图片处理、业务评分、缓存逻辑揉在一起，且
`ensure_child_owned` / `get_owned_clothing` 在两个文件中重复。项目目前**没有任何测试**。

整体优化分三个阶段（Approach A，已选定）：

1. **Phase 1（本 spec）**— 建立特征测试安全网 + 把两个巨型路由拆为服务/领域分层。
2. **Phase 2** — 性能优化（缓存、AI 调用并发/流式、查询）。独立 spec。
3. **Phase 3** — AI 质量（识别准确度、搭配方案质量，提示词与评分算法调优）。独立 spec。

之所以先重构再改进：识别准确度与搭配质量是**改变行为**的工作，而重构是**保持行为**的。
先在干净、有测试的基座上分离各部分，后续调优才能区分"破坏 vs 改进"，且每块可独立测试。

**本 spec 的成功标准：** 两个路由变薄（仅编排），逻辑迁入聚焦模块，对外接口完全不变，
高风险路径有特征测试覆盖，每一步迁移后测试全绿。

## 目标架构

```
backend/app/
  routers/
    clothing.py        # 薄：仅 HTTP 路由，委托 services
    outfits.py         # 薄：仅 HTTP 路由
  services/
    images/
      storage.py       # _cos_upload, _local_persist, _persist_image, _build_filename
      urls.py          # _is_local_url, _public_image_url, _local_upload_path,
                       #   _image_data_url, _ark_image_url_or_data_url
    recognition/
      ark_client.py    # ARK HTTP 调用 + _compact_ark_request
      parsing.py       # _extract_json, _extract_ark_text, _pick_recognition_object
      normalize.py     # _normalize_recognition
      prompt.py        # _recognition_prompt
    outfits/
      profile.py       # choose_style_profile + _profile_scores_from_* 家族
      scoring.py       # score_item, pick_best, enrich_reason, recent_clothing_counts
      fallback.py      # build_fallback_outfit
      ai_client.py     # call_ai_recommend + compact_gptsapi_request
      ai_build.py      # build_ai_outfit, extract_json, compact_clothing, clothing_fingerprint
      cache.py         # build_cache_signature, upsert_recommendation_cache,
                       #   outfit_to_cache, cache_to_outfit
  domain/
    vocab.py           # CLOTHING_TYPES, CLOTHING_SUB_TYPES, COLORS, PATTERNS, SEASONS,
                       #   THICKNESS, STYLE_TAGS, RECOGNITION_FIELD_SCORE_META
  deps.py              # ensure_child_owned, get_owned_clothing（去重 — 当前两个路由各有一份）
```

### 设计原则

- **路由变薄** — 每个端点只编排服务调用并映射 schema；不内联解析/AI/图片逻辑。
- **`ensure_child_owned` 去重** — 收敛到 `deps.py`（当前在两个路由中复制粘贴）。
- **纯函数保持纯** — 解析、规范化、评分等"数据进、数据出"的函数不依赖 `db`/HTTP，
  可直接单测。当前已依赖 `db`/`current_user` 的函数（如 `build_ai_outfit`、
  `recent_clothing_counts`）保留这些参数，仅迁移到服务模块。
- **不改对外接口** — 路径、请求/响应 schema、状态码全部不变。纯内部结构调整。

## 特征测试策略

测试**先行**，在任何代码迁移前锁定当前行为。

### 基础设施

- 新增 `backend/requirements-dev.txt`：`pytest`、`pytest-asyncio`、`respx`（stub httpx 的 AI 调用）。
- 新增 `backend/tests/`，`conftest.py` 提供：
  - FastAPI `TestClient`
  - 内存 SQLite（覆盖 `get_db` 依赖）
  - 已认证测试用户（覆盖 `get_current_user`）
  - 预置 children / clothing fixtures
- 所有外部 AI/云调用 stub：ARK、gptsapi、阿里云（`segment_cloth` / `classify_clothing`）、
  腾讯云 COS。捕获**真实请求载荷**、喂入**预设响应**，从而断言"我们构造请求"和
  "我们解析响应"的逻辑 — 正是被重构的部分。

### 覆盖范围（聚焦高风险路径）

1. **CRUD 路由** — clothing 的 list/create/get/update/wear/delete；归属 404。
   快速、高价值的回归网。
2. **识别管线** — `/clothing/recognize` 与 `/clothing/upload-and-recognize`：
   断言 ARK 请求体结构，并验证代表性 AI 响应能规范化到正确枚举字段。
   外加对纯解析器（`_extract_json`、`_pick_recognition_object`、`_normalize_recognition`）
   的单测，覆盖刁钻输入（markdown 包裹的 JSON、数组、缺字段）。
3. **搭配推荐** — `/outfits/recommend`：缓存命中路径、AI 成功路径、兜底路径
   （mock AI 失败 → 断言 fallback 触发）；外加对 `score_item`、`choose_style_profile`、
   `build_cache_signature` 的单测（固定输入 → 固定输出）。

### Golden-master 手法

对棘手的纯函数：捕获当前一组输入的输出，冻结为期望值。若重构改变了输出，测试失败 —
这正是安全网在起作用。

**门槛：** 当前代码上跑出全绿后才动结构；每次模块抽取后保持全绿。

## 执行顺序与验证

小步推进，每步单独验证。每步以**全绿测试**结束后才进入下一步：

1. **测试先行** — 搭建测试基础设施，针对**当前**代码写高风险特征测试，确认全绿。基线。
2. **抽取 `domain/vocab.py` + `deps.py`** — 迁常量、去重 `ensure_child_owned` /
   `get_owned_clothing`。风险最低，验证 import 接线。跑测试。
3. **抽取图片服务**（`storage.py`、`urls.py`）— 纯迁移，更新 `clothing.py` 的 import。跑测试。
4. **抽取识别服务**（`ark_client`、`parsing`、`normalize`、`prompt`）—
   `clothing.py` 路由改为委托。跑测试。
5. **抽取搭配服务**（`profile`、`scoring`、`fallback`、`ai_client`、`ai_build`、`cache`）—
   `outfits.py` 路由改为委托。改动最大；逐子模块进行，每个之间保持全绿。跑测试。
6. **收尾** — 路由此时应已变薄；核对行数下降、无逻辑残留。

### 行为保持规则

- 每步都是**迁移 + 重新 import**，绝不重写。函数体逐字复制，只改位置与调用点。
- 不改签名、不改 schema、不改路由、不改日志文案。（用于 AI 调试的 `logger.warning`
  原样保留 — 清理它们是 Phase 2/3 的决定，不属本次重构。）
- 若某函数确需微调签名以适配新家，须显式标注、有测试覆盖、作为独立一步完成 —
  不静默打包进其他改动。

### 每步验证

- `pytest backend/tests` 全绿
- 应用可 import / 启动（`uvicorn` import 检查）
- 无需手工戳 API，因为测试已覆盖高风险路径。

## 明确不做（YAGNI / 留待后续阶段）

- 前端/小程序重构 — 独立阶段。
- 任何性能优化（并发、流式、查询调优）— Phase 2。
- 任何 AI 质量改进（提示词、评分算法、识别准确度）— Phase 3。
- 清理 AI 调试日志、改 schema、改对外接口 — 不在本次范围。
- 为未被重构的路由（auth/children/diaries/weather 等）补全测试 — 不在本次范围。
