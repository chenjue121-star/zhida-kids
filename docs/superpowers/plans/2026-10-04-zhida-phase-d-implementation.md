# 智搭 D 阶段实施计划

> **For agentic workers:** Use subagent-driven-development and test-driven-development. 用户于 2026-10-04 要求“执行 D 阶段任务”；本计划细化已确认产品规格与路线图，直接在现有隔离工作区执行。

**Goal:** 完成可解释、可修正的个性化与已选方案日历，并用隔离数据完成迁移、备份和回退验证。

**Architecture:** 复用 A–C 家庭授权、实物、方案快照、操作回执和版本冲突。偏好事件保留原始证据，推断仅调整审美排序；日历读取方案，撤销追加版本并释放占用，复用创建重新核对的草稿。迁移演练与实际使用库隔离。

**Tech Stack:** 现有 FastAPI、SQLAlchemy、Alembic、MySQL/SQLite；微信原生 JS/WXML/WXSS；pytest、node:test、微信开发者工具编译器。

## 依据、工作区和执行边界

- 产品依据：`docs/superpowers/specs/2026-09-13-zhida-rebuild-product-design.md` §8–10，路线图 D 与 §5.4。
- 工作区：`.worktrees/phase-a`，分支 `codex/phase-a`。保留所有 A–C 和主工作区未提交内容，不做混合提交。
- 新功能基线：后端 362 passed；小程序 306 passed。模型授权：用户允许现有衣物评估图片小批真实烟测，最多两张；不上传孩子资料。
- 当前入口不发布或切换；真机、双账号、真实天气及生产发布以实际证据记录。离线演练只使用固定样本；旧库历史的正式迁移需先确定数据范围。

## 统一契约

ID 输出字符串，版本整数，日期 `YYYY-MM-DD` 使用家庭时区，所有写入验证当前成员与角色。

### 个性化

原有 profiles GET 保留 `styles`（显式）和 `version`，扩展 `inferred_tags`、`learning_version`、`effective_weights`。推断标签包含 style、direction、weight、evidence_count、原始事件依据和 rule_version。至少三个不同方案的同向证据才可展示；同方案重复事件不增加方案数。

`POST /families/{fid}/children/{cid}/feedback`：

```json
{"event_id":"stable-attempt","plan_id":"1","plan_version":1,"signal":"like","reason":"aesthetic","styles":["clean_daily"]}
```

响应 `{event,profile,target}`。服务端验证冻结方案版本，保存操作者、孩子、原方案依据、归属、原因和证据。家庭依据归家庭；成员依据归操作者自己的个人偏好，不能因使用其他成员的依据学习那人的口味。comfort、washing、missing、too_small、skip 保留事件而不作为审美证据。未补记无事件；最终选定产生弱正向事件，不等同穿过。

`POST /children/{cid}/profiles/{family|me}/tags/{style}`：

```json
{"expected_version":2,"action":"dismiss"}
```

accept 转为显式标签，dismiss 删除推断并记录证据截止位置。原 PUT 修改显式风格；删除风格同样抑制旧证据。显式权重大于推断，推断有上限和版本化规则；舒适和合身过滤继续独立。权重是初版可回归规则，不宣称已验证个性化效果。

### 日历

- `GET /outfits/calendar?start_date&end_date&child_id&include_cancelled=true`：返回 `{today,timezone,role,start_date,end_date,plans}`，范围最多62天，按日期/序号排序，不为历史列表调用天气。
- `GET /outfits/plans/{pid}`：最新冻结快照，增加 `status=selected|cancelled`；回看不改变事实或调用模型。
- `POST /outfits/plans/{pid}/cancel`：`{expected_version,operation_id}`，返回完成回执；当前版本条件更新，追加撤销快照、操作者和时间，释放 Reservation，保留原版本。
- `GET /outfits/operations/{operation_id}` 查询原保存/撤销结果；`POST /plans/{pid}/cancel/resolve` 携原撤销参数，核实未执行并围栏迟到请求。未知结果不能乐观当撤销成功或重新生成尝试。
- `POST /outfits/plans/{pid}/reuse`：`{expected_source_version,child_id,target_date,scene,draft_id,preference_mode,designated_member_id?}`，返回 `{source_plan_id,source_version,draft,review,context}`。仅产生草稿，按目标日期天气和当前合身、可用、占用重核；清历史共享授权、推荐/目标方案身份、锁定排除，创建新动作。当前资料变化由用户核对后接纳。最后仍通过 C review/save 显式选定。
- 已撤销方案不能直接修改；同日新增继续稳定递增序号。选择、修改、撤销、日期经过都不产生穿着次数。

## 任务1：后端偏好与日历（后端代理）

**Files:** `backend/app/v2/preferences/{models,schemas,service,router,learning}.py`；`outfits/{models,schemas,service,router,calendar}.py`；`core/database.py`；`main.py`；`migrations-v2/versions/0005_personalization_calendar.py`；`tests/v2/test_d_preferences.py`、`test_d_calendar.py`、`test_d_mysql_races.py` 及既有迁移/head契约。

- [ ] 先写 HTTP 行为失败测试：事件幂等、主体隔离、临时原因不学习、三套阈值、删除截止、新证据、显式优先、签名变化、快照不变；范围多条、viewer/撤权、撤销幂等/回滚/版本竞争/释放占用、复用无写入及目标条件。
- [ ] 运行 `.venv/bin/python -m pytest -c pytest-v2.ini tests/v2/test_d_preferences.py tests/v2/test_d_calendar.py -q`，确认缺失功能失败。
- [ ] 实现原始事件、学习结果及版本；把选择事件与方案/回执写入同一事务；扩展有效偏好排序。
- [ ] 实现日历范围/详情、撤销与复用；所有天气 IO 在事务锁外，回来重验权限和来源版本。
- [ ] 新增0005迁移，更新 readiness，注册演练来源记录模型；验证 SQLite/MySQL schema 与元数据一致。
- [ ] 运行行为测试和真实 MySQL 竞争测试；由根代理进行规格审查，再由另一代理代码质量复核。

## 任务2：原生界面与状态（前端代理）

**Files:** `miniprogram-v2/services/{calendar,preferences,runtime}.js`；`stores/outfit-context.js`；新 `pages/calendar/*`、`pages/plan-detail/*`；`pages/preferences/*`；`app.json`；搭配/衣橱/我的四入口导航；`tests/phase-d-*.test.js`；`PRODUCT.md`。

- [ ] 先写页面动作和服务行为测试：切账号/家庭/孩子/月份/标签后的迟到结果拒收；仅查看禁止写；撤销未知结果冻结查询；反馈重试同键；日历多条/撤销状态；复用新身份和目标实际日期；资料变更不静默采用。
- [ ] `node --test tests/phase-d-*.test.js` 确认失败，再实现服务与页面。
- [ ] 日历使用月份/日期原生选择，详情展示选择时主件/备用及操作人，编辑与新草稿进入现有 C 页面。
- [ ] 偏好分开呈现显式和推断、依据、接受/编辑/删除、归属说明及版本冲突；反馈原因可跳过，暂时理由不变为审美。
- [ ] 保留白绿样式、固定字号、44px操作、权限照片、空/加载/失败状态；四入口为搭配/衣橱/日历/我的。
- [ ] `npm test`、所有JS语法、wcc/wcsc编译和窄屏源模板视觉检查；规格与质量分别复核。

## 任务3：迁移、备份、回退演练（发布代理）

**Files:** `backend/app/v2/release/{models,legacy,rehearsal}.py`；`backend/scripts/phase_d_rehearsal.py`；`tests/v2/test_d_release.py`；固定legacy与0–6衣橱样本；`docs/runbooks/zhida-phase-d-release.md`。

- [ ] 先测旧用户→个人家庭、孩子、实物/适配、可空身体资料；唯一来源映射保证重跑不复制，变更来源拒绝并回滚。
- [ ] 旧日记只保留带来源的历史记录；旧图片URL不冒充新版已验证私有资产；旧 wear_count/last_worn_at 不进入新版事实或学习。
- [ ] CLI只接受显式JSON导出并创建新隔离目录/SQLite库，禁止触碰实际旧库。备份数据库和媒体、记录哈希和0600权限，恢复至另一路径逐项比对。
- [ ] 隔离演练升级→ready→备份→回退恢复→一致性，报告其SQLite限制；真实MySQL由迁移/并发测试证明。
- [ ] 检查已配置模型能力；在授权且有密钥时最多两张真实衣物烟测，结果与人工审阅需求单独记录。

## 任务4：整体验收与交付（根代理）

**Files:** `backend/tests/v2/test_d_acceptance.py`、`test_frontend_d_contract.py`；`miniprogram-v2/tests/phase-d-contract-smoke.js`；`docs/runbooks/zhida-phase-d-acceptance.md`。

- [ ] 固定0/6/12/24/36/60/83月龄、连体/上下装/裙/鞋/外套、共用实物、未知合身/待洗；天气未知/高温/低温，双孩子及第三账号权限回归。
- [ ] 真实临时HTTP服务运行发布目录客户端，确认日历/反馈/撤销/复用与后端一致，不将mock作为联通证据。
- [ ] 全套 `.venv/bin/python -m pytest -c pytest-v2.ini -q`、`npm test`、`node --check`、compileall、wcc/wcsc、迁移元数据与回环、`git diff --check`。
- [ ] 记录真实执行数量和范围；真机、收费模型、天气、实际历史迁移和生产切换分别给状态。可自动完成的工作全部执行后交付，保留现有分支供审阅。
