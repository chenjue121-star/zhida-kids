# 智搭 C 阶段实施计划

> For agent workers: use subagent-driven-development and test-driven-development. 用户已逐组审阅并于 2026-10-03 回复“实施”，本计划直接执行。

**Goal:** 将五组已确认的每日搭配流程落实到 V2 后端和原生小程序，覆盖推荐、调整、备用、同日多套、共用和异常恢复。

**Architecture:** 后端新增 outfits 领域，复用 A/B 鉴权、实物、私有媒体和 operation 回执；推荐与不可变已选快照分离。家庭锁内只进行校验和原子写入，天气及模型调用在锁外。前端新增独立草稿状态和 API 服务，首页呈现推荐/共享方案，编辑和核对页处理细节。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、MySQL/SQLite；原生微信小程序 JS/WXML/WXSS；pytest、node:test。

## 统一契约

所有 ID 输出为字符串，输入允许无损数字字符串；日期 YYYY-MM-DD，时段 HH:mm 为目标日家庭时区的计划。场景 daily/outdoor/school/formal/sport。偏好 family/current_member/designated_member，指定成员使用 membership_id。

通用输入：child_id、target_date、scene、preference_mode、designated_member_id（可空）、city 或 lat/lon（可省略采用家庭城市）。GET context 可用 date_mode=today/tomorrow，由服务端解析实际日期。

草稿输入：draft_id、main_items[{garment_id,expected_version}]、backup{mode:none/partial/full,items[{garment_id,expected_version,replaces_garment_id?}]}、locked_ids、excluded_ids、target_plan_id（新增为空）、expected_version（编辑）、recommendation_id（可空）、sharing_grants[]、weather_acknowledged。

- GET /families/{fid}/outfits/context?child_id&date_mode 或 target_date，另可带场景/偏好/地点。返回 today/timezone/target_date/role/child/weather/input_version/garments/occupancy/plans/suggestion。天气 known/unknown、有效条件，不冒充实况；garments 含真实信息/fit/可用资格，occupancy 含具体来源，plans 使用冻结快照，suggestion 是已有授权共享建议或 null。
- POST /families/{fid}/outfits/recommend：通用输入 + draft_id/request_id/locked_ids/excluded_ids/exclude_combination。返回 recommendation_id/request_id/input_version/items/reason/warnings/missing/source/cached/weather/preference_subject；失败不删除草稿，无其他合理组合明确返回。
- POST /families/{fid}/outfits/candidates：草稿输入 + replace_id/usage（main 或 backup），返回 items（同类且替换后合理/没有其他孩子占用）。
- POST /families/{fid}/outfits/backup：草稿输入 + mode，返回 items（兼容建议，前端必须暂存和确认）。
- POST /families/{fid}/outfits/review：草稿输入，返回 valid/input_version/conflicts/warnings/missing/packing_items；保留天气未知提示。冲突包括 garment_id 和全部 source child_id/nickname/plan_id/sequence/version/usage/selected_by/target_date。
- POST /families/{fid}/outfits/sharing：草稿输入 + garment_id/reason/periods[{child_id,start,end}]，返回 grant。服务器绑定当前 draft、日期、实物、用途、目标方案和全部来源身份/版本；非重叠和去空白理由必填。
- POST /families/{fid}/outfits/plans：草稿输入 + input_version + operation_id；目标方案非空时为 expected_version 条件更新，否则新增。返回 {operation_id,status:completed,plan}。保存和回执原子提交。
- GET /families/{fid}/outfits/operations/{operation_id}：仍有家庭访问权的原操作者可查；返回历史完成回执或 status:unknown。查不到不重交。
- POST /families/{fid}/outfits/operations/{operation_id}/resolve：编辑成员携完整原 payload 明确核实未执行；同家庭锁下重放已有成功或写 NOT_EXECUTED 围栏，禁止晚到旧提交执行。

## 任务与文件归属

### 1. 规格与基线（根代理）
- 写完整规格 docs/superpowers/specs/2026-10-03-zhida-phase-c-design.md；更新 docs/design/phase-c-review/README.md 的人类确认记录。
- 保留已有未提交 A/B；复用 .worktrees/phase-a，避免重复 worktree 和混合提交。
- 基线 node 100 测试通过；后端使用 backend/.venv/bin/python，禁止系统 Python 混用。

### 2. 后端领域、天气、事务与测试（后端代理）
- 新增 backend/app/v2/outfits/{models,schemas,rules,service,router}.py，可按职责再拆 signature/reservations。
- 新增目标日天气适配 backend/app/v2/weather/forecast.py；推荐适配 backend/app/v2/integrations/outfits.py。供应商结果只在同一过滤和协调规则内选择；异常回退基础建议。
- 修改 core/database.py、main.py、core/config.py、migrations-v2/env.py；新增 0004_daily_outfits.py；修改 head/metadata 测试与 .env.v2.example。
- 先写 test_c_outfits.py/test_c_rules.py/test_c_weather.py/test_c_transactions.py 的失败测试，再实现。覆盖锁/排除、fit unknown、dress/onesie、年龄/场景、天气、偏好/测量签名、缓存、同日多套、快照、主备去重、占用/分时、版本、幂等/resolve、权限在途与回滚。增加真实 MySQL 并发用例，沿用隔离库安全约束。
- 使用 pytest-v2.ini；迁移只在测试库执行，不触碰业务库。

### 3. 前端服务与纯状态（前端代理，和后端无共享文件）
- 新增 services/outfits.js、stores/outfit-context.js、services/c-page.js；修改 services/runtime.js 注册。
- 先写 tests/phase-c-services.test.js、phase-c-state.test.js。API/存储操作双重校验身份/权限/导航/输入/请求身份；所有未知保存冻结 payload 只查询，重启恢复。
- 草稿按账号/家庭/孩子/实际日期/依据分区，日期模式按孩子记忆；固定排除和来源草稿独立。主搭配变更明确使备用失效；候选/备用/分时暂存确认/取消。编辑变新增取得新 draft/action 身份，不能继承 sharing grant。
- 降权仅查看已有内容，撤权清该家庭全部状态，恢复授权查询旧操作使用新的当前 epoch。

### 4. 原生页面与集成（根代理）
- 修改 home/home.*；新增 outfit-edit/*、outfit-review/*；修改 app.json、garment-detail.* 添加从实物发起；新增 c.wxss。
- UI 单品原图沿用受授权 media 服务，固定底部操作，至少44px，圆形选择，白绿基线。
- 先增 tests/phase-c-pages.test.js 验证核心页面动作，不写重复实现的静态断言。保留 A/B 页面入口及原生微信兼容（PUT 而非 PATCH）。
- home 目标日和天气由 context 响应决定，加载保留草稿/快照；只读仅看授权内容。dirty 离开显式继续/放弃；共享刷新保留草稿；冲突可看最新或明确新增；未知结果只显示查询/核实入口。

### 5. 审查、验证和交付
- 每项由另一代理先做规格符合性，再做代码质量复核，修复关键问题后合并集成。
- backend/.venv/bin/python -m pytest -c pytest-v2.ini -q；npm test；node tests/phase-b-contract-smoke.js；compileall app/v2；迁移 metadata 比较和回环；git diff --check。
- 写 docs/runbooks/zhida-phase-c-acceptance.md：真实运行数量与范围、供应商/真机/部署待验收范围；不把 HTML 原型、mock 或 SQLite 当实际质量/真实并发结论。
- 不自动部署、不付费调用、不创建横跨未提交 A/B 的扫荡提交。

## 审查补充

推荐输入同时携当前主件、已确认备用和草稿修订，用同一规则校验兼容；主搭配变化后备用待明确重新确认。分时已确认后修改时段/原因的暂存必须拦截保存，取消恢复已确认摘要。原成功操作恢复其提交快照，当前衣物变化与家人后续版本另行提示，不倒灌覆盖最新共享记录。

## 执行结果（2026-10-03）

全部实施任务已落实。后端最终361测试、前端176测试通过；C6项真实MySQL并发/权限回归、真实HTTP契约和隔离迁移回环包含在验证中。独立后端与前端审查发现的阻断问题已修复并补回归；原生WXML/WXSS编译通过。详情及尚未执行的真机/供应商质量验收见 [验收记录](../../runbooks/zhida-phase-c-acceptance.md)。未迁移开发业务库、未部署、未调用收费模型；继续保留现有隔离工作区和A/B未提交内容。
