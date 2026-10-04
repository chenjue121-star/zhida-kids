# 智搭 A 阶段：家庭与孩子档案 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在独立新版环境跑通微信登录、创建／加入家庭、成员权限、多宝档案及初始偏好，交付一个可以被两个账号共同使用的微信小程序阶段版本。

**执行状态（2026-09-20）：** 核心实现已落地，后端 59 项、前端 48 项测试通过。真实微信 AppSecret 和双账号真机验收未完成，不能将本阶段标记为全量验收通过。逐项证据及遗留验证见 `docs/runbooks/zhida-phase-a-acceptance.md`；下方清单保留原计划，不批量勾选未经原生验证的事项。

**Architecture:** 模块化 FastAPI 单体，`/v2` 接口，新数据库通过 Alembic 迁移。身份、家庭、孩子和初始偏好分模块，事务在用例服务结束；微信小程序独立目录，以家庭和孩子稳定 ID 保存上下文。

**Tech Stack:** 沿用项目 FastAPI、SQLAlchemy、PyMySQL、Pydantic、httpx、PyJWT 与原生小程序；新增 Alembic 用于迁移。使用现有 pytest 测试方式，数据库并发验收必须在独立 MySQL 测试库执行。

---

## 1. 执行边界与交付

依据已确认产品稿 `docs/superpowers/specs/2026-09-13-zhida-rebuild-product-design.md` 和架构总纲 `docs/superpowers/plans/2026-09-13-zhida-rebuild-roadmap.md`。

本阶段交付：开发者工具中可打开新版小程序；用户可以登录、建立家庭与孩子；第二个账号接受邀请后按权限共同使用；不同账号与家庭的数据不串；无照片、身体信息未知也可建档。

A 阶段页面以家庭/孩子管理为可用入口，不显示尚未实现的推荐或衣橱假数据。B 接入图片上传后开放可选照片编辑；A 不要求照片，亦不伪装图片已保存。四 Tab 的完整产品导航在 C 整合，A 所有已注册页面均需真实存在。

执行时通过隔离分支/工作目录开展。旧库和原 `project.config.json` 不变。`backend/requirements.txt` 的既有未提交修改以及评估样本不纳入本阶段提交。

## 2. 已收敛的实施默认规则

这些是实现所需的默认值，可通过后续产品反馈调整：

- 一个用户可以属于多个家庭，界面有当前家庭；一个家庭有多名成员和多个孩子。
- 首位创建者为 admin；角色枚举 `admin/editor/viewer`，只有 admin 可邀请与管理成员。
- 邀请一次性、7 天有效，默认 editor，也可 viewer；不能通过邀请直接授予 admin。
- 已在该家庭的账号接受尚未用掉的邀请时返回自己的成员关系，不消耗邀请、不升级角色；原接受者重复提交成功返回原结果。
- 至少保留一名 admin。成员退出不删除家庭；本阶段不提供整家庭删除接口。
- 非成员访问家庭资源统一 404；成员权限不足 403；过期/已被别人使用的邀请返回 410，非法凭据返回 404。
- 家庭时区默认 `Asia/Shanghai`；地点使用用户填写的城市文本，A 不强制定位权限。
- 生日不可晚于家庭当地今日；0–6 岁是产品覆盖范围，不因生日跨过年龄界限删除或锁住既有档案。
- `height_cm/weight_kg` 可空，已填写则须为有限正数；测量日期与数据一起保存，不能是未来日期。
- 肤色和舒适偏好可空；身体字段的“未知”存 null，不能存 0。
- 风格可多选或明确“暂无偏好”，后者保存空列表。首批键：`clean_daily/sporty/soft_natural/playful_print`，中文分别为简洁日常、运动活力、自然柔和、童趣印花。
- 肤色首版键为 `light/medium/deep`，均为中性描述；舒适字段 `thermal_preference=unknown/neutral/runs_warm/runs_cold`、`fit_preference=unknown/regular/loose`、`avoid_high_neck` 可空布尔。
- 推荐依据 `family/designated_member/current_member`，仅指定成员模式填写 `designated_member_id`；目标必须是同家庭有效成员。
- admin/editor 可编辑共同偏好和推荐依据，可编辑自己的成员偏好；查看他人的配置可以，修改他人私人偏好不可以。viewer 不修改任何档案或偏好。
- 指定成员退出/移除时，在同一事务把受影响孩子恢复为 family 模式，并增加偏好配置版本；家庭统一偏好保留。

## 3. 文件地图

新增以下文件，已有旧版文件不导入作为运行依赖：

```text
backend/requirements-v2.txt
backend/.env.v2.example
backend/alembic-v2.ini
backend/migrations-v2/env.py
backend/migrations-v2/script.py.mako
backend/migrations-v2/versions/0001_family_children.py
backend/app/v2/__init__.py
backend/app/v2/main.py
backend/app/v2/core/{__init__,config,database,errors,clock}.py
backend/app/v2/identity/{__init__,models,schemas,router,service,tokens}.py
backend/app/v2/integrations/{__init__,wechat}.py
backend/app/v2/families/{__init__,models,schemas,router,service,access}.py
backend/app/v2/children/{__init__,models,schemas,router,service}.py
backend/app/v2/preferences/{__init__,models,schemas,router,service}.py
backend/tests/v2/{__init__,conftest}.py
backend/tests/v2/test_{bootstrap,identity,family_access,invitations,member_races,children,preferences,migrations}.py
miniprogram-v2/project.config.json
miniprogram-v2/app.{js,json,wxss}
miniprogram-v2/config.js
miniprogram-v2/services/{api,session}.js
miniprogram-v2/stores/context.js
miniprogram-v2/pages/login/login.{js,json,wxml,wxss}
miniprogram-v2/pages/families/families.{js,json,wxml,wxss}
miniprogram-v2/pages/family-detail/family-detail.{js,json,wxml,wxss}
miniprogram-v2/pages/invitation/invitation.{js,json,wxml,wxss}
miniprogram-v2/pages/children/children.{js,json,wxml,wxss}
miniprogram-v2/pages/child-edit/child-edit.{js,json,wxml,wxss}
miniprogram-v2/pages/preferences/preferences.{js,json,wxml,wxss}
miniprogram-v2/tests/context.test.js
miniprogram-v2/tests/session.test.js
docs/runbooks/zhida-v2-local.md
docs/runbooks/zhida-phase-a-acceptance.md
```

`requirements-v2.txt` 仅列 A 使用的依赖，不引用旧 requirements 中的图片 SDK；沿用已验证依赖版本。Alembic 与测试依赖执行安装前核对官方说明、Python 兼容性和解析结果后固定精确版本。

## 4. 数据表与约束

统一使用 BIGINT ID，外部 JSON ID 序列化为字符串，避免小程序数字精度问题；日期 ISO，时间 UTC。变更对象使用整数 version，初值 1。

| 表 | 字段及约束 |
| --- | --- |
| users | id, openid, nickname, created_at；openid 唯一，不保存本阶段用不到的 session_key |
| families | id, name, timezone, city, version, created_by, timestamps |
| memberships | id, family_id, user_id, role, status(active/removed), joined_at；family_id/user_id 唯一 |
| invitations | id, family_id, token_hash, role, expires_at, revoked_at, accepted_by, accepted_at, created_by；token_hash 唯一 |
| children | id, family_id, nickname, birthday, skin_tone nullable, archived_at, version, timestamps |
| child_measurements | id, child_id, height_cm nullable, weight_kg nullable, measured_on；至少一个测量值非空；同日允许纠正后另存一次，以 id 决定最新记录 |
| child_preference_settings | child_id 主键, mode, designated_member_id nullable, thermal_preference, fit_preference, avoid_high_neck nullable, version |
| preference_profiles | id, child_id, owner_key, membership_id nullable, styles JSON, version；child_id/owner_key 唯一；owner_key 为 family 或 member:<membership_id> |
| mutation_receipts | id, actor_id, operation, idempotency_key, request_hash, response_body, status_code；actor_id/operation/idempotency_key 唯一 |

所有家庭资源经父级关系验证归属。不要仅验证一个 membership_id 存在就允许指定跨家庭成员。孩子归档而非级联删除，保留后续衣橱和方案引用基础。

`mutation_receipts` 本阶段覆盖创建家庭、创建孩子及新增测量记录。重复键同载荷返回原结果，不同载荷返回 409；回放前仍校验当前权限。创建请求与 receipt 写入同一事务，失败不能留下成功回执。

## 5. API 契约

统一错误：`{"error":{"code":"FORBIDDEN","message":"当前成员无此操作权限","request_id":"..."}}`。401 清登录态；403 不清 token；404/410 邀请错误不能清空其他家庭数据。Pydantic 校验错误映射到相同结构并带字段路径。

所有创建接口返回 201（邀请接受 200），查询/修改 200，撤销/移除/归档 204；幂等回放返回原状态。写请求如需版本通过 body `expected_version`；幂等通过 `Idempotency-Key`。

| 接口 | 入参/出参与权限 |
| --- | --- |
| POST /v2/auth/wechat-login | code → token, expires_at, user；不开启真实接口时用可注入测试 exchanger |
| GET /v2/me | user, families, memberships；family 不为空也不等于已建孩子 |
| POST /v2/families | name, city；创建家庭并原子创建 admin 与幂等回执 |
| GET /v2/families | 当前用户有效成员家庭列表 |
| GET/PATCH /v2/families/{fid} | name/city/timezone/version；只有 admin 更新 |
| GET /v2/families/{fid}/members | 所有有效成员可查，不能返回 openid 或 token |
| POST /v2/families/{fid}/invitations | role → invitation_id, token, expires_at；仅 admin，token 只创建时返回 |
| DELETE /v2/families/{fid}/invitations/{iid} | admin 撤销未接受邀请 |
| POST /v2/invitations/preview | token → family_name, inviter_name, role, expires_at；需登录，只给最小加入信息 |
| POST /v2/invitations/accept | token → family_id, membership；需登录，锁定家庭与邀请完成接受 |
| PATCH /v2/families/{fid}/members/{mid} | role, expected_family_version；admin 管理，不得移除最后 admin |
| DELETE /v2/families/{fid}/members/{mid} | admin 移除成员；自身退出使用 leave 接口 |
| POST /v2/families/{fid}/leave | 当前成员退出，最后 admin 返回 409 |
| GET /v2/families/{fid}/children | 有效孩子列表，含 latest_measurement 与 preference_summary |
| POST /v2/families/{fid}/children | nickname,birthday,skin_tone?,measurement?,preferences；editor/admin；孩子及默认配置原子创建 |
| GET/PATCH /v2/families/{fid}/children/{cid} | 档案/version；PATCH 不覆盖测量历史，必须带 expected_version |
| DELETE /v2/families/{fid}/children/{cid} | editor/admin 归档；查询明确排除归档记录 |
| POST /v2/families/{fid}/children/{cid}/measurements | height_cm?,weight_kg?,measured_on；独立追加，用幂等键防重 |
| GET/PATCH /v2/families/{fid}/children/{cid}/preference-settings | 依据与舒适字段，PATCH expected_version；editor/admin |
| GET/PUT /v2/families/{fid}/children/{cid}/profiles/family | 共同 styles/version；editor/admin 写，首次随建档创建 |
| GET/PUT /v2/families/{fid}/children/{cid}/profiles/me | 本成员 styles/version；editor/admin 写，首次创建 expected_version=0 |

具体请求示例：

```json
{
  "nickname": "小豆子",
  "birthday": "2024-04-12",
  "skin_tone": null,
  "measurement": null,
  "preferences": {
    "styles": ["clean_daily", "sporty"],
    "mode": "family",
    "designated_member_id": null,
    "thermal_preference": "unknown",
    "fit_preference": "unknown",
    "avoid_high_neck": null
  }
}
```

并发变更必须使用统一锁顺序：family → invitation/membership → child/settings；所有成员管理和指定成员更新都锁 family 行，避免两位 admin 同时退出后无人管理，或退出与指定偏好发生竞态。

## 6. 任务与验证步骤

任务按下列顺序执行，每个实现检查点只提交本任务文件。测试文件中的公共 fixture 在任务 1 建立：`client` 为 create_app 的 TestClient；`db` 为迁移后的独立测试库 Session；`login(identity)` 调用已注入的假微信 exchanger；`family_factory` 创建指定角色的测试家庭；`auth(user)` 返回 Bearer header。不得用生产微信或模型作为测试依赖。

### Task 1：隔离应用、配置和迁移骨架

Files: core 四个模块、main.py、requirements-v2、env 示例、alembic 配置、tests/v2/conftest.py、test_bootstrap.py、test_migrations.py。

- [ ] 先增加测试：无模型/天气/COS key 时工厂可以创建；配置缺少 V2_DATABASE_URL 或 V2_JWT_SECRET 时清晰失败；import 不建表、不连旧库。
- [ ] 用应用工厂参数注入设置、数据库和微信 exchanger；配置使用 `V2_` 前缀与 `.env.v2`，禁止回退到旧 DATABASE_URL。
- [ ] 增加 `/health` 仅检查进程、`/ready` 检查新库与迁移版本；未迁移 ready=503，不静默创建表。
- [ ] 建立迁移 env，只导入 v2 Base metadata。迁移测试必须校验数据库名以 `_test` 结尾并拒绝旧库连接信息。
- [ ] 执行 `cd backend` 后 `.venv/bin/python -m pytest tests/v2/test_bootstrap.py tests/v2/test_migrations.py -q`，预期全部通过；空库迁移 up/down/up 后 schema 相同。降级只在空测试库演练。

核心配置约束示例：

```python
class V2Settings(BaseSettings):
    database_url: str
    jwt_secret: SecretStr
    env: Literal["development", "test", "production"] = "development"
    dev_wechat_mock: bool = False
    wechat_appid: str = ""
    wechat_secret: SecretStr = SecretStr("")
    model_config = SettingsConfigDict(env_prefix="V2_", env_file=".env.v2")
```

### Task 2：新版身份认证

Files: identity 全部文件、integrations/wechat.py、migration 0001 用户表、test_identity.py。

- [ ] 编写并运行失败测试：相同 openid 两次登录同一 user；并发首次登录只一条记录；错误 code 400、微信超时 503；过期、篡改、旧版 token 均 401。
- [ ] exchanger 使用 httpx 可替换 transport；只返回身份字段，不记录 code、密钥、session_key 或完整响应。
- [ ] JWT 固定 HS256、必需 sub/iat/exp/iss/aud，issuer=`zhida-v2`，audience=`zhida-miniprogram-v2`，有效期建议 7 天；身份只标识用户，角色不塞 token。
- [ ] mock 在 test/dev 显式打开，production+mock 启动失败。唯一 openid 冲突处理时 rollback 后重查，不能把所有 IntegrityError 吞掉。
- [ ] 运行 `.venv/bin/python -m pytest tests/v2/test_identity.py -q`；记录真实微信验证所需的实时 code，不能凭空生成，留到真机验收。

### Task 3：家庭创建与访问矩阵

Files: families/models.py、schemas.py、access.py、service.py、router.py；mutation_receipts 放 families/models.py 与 service.py 的内部辅助函数，首版仅提供实际三处调用所需逻辑；test_family_access.py。

- [ ] 先测试 admin/editor/viewer/非成员/未登录矩阵，每种读写接口都要经过公共 access 守卫。
- [ ] 家庭创建事务同时写 family、admin、receipt；名字去首尾空格后 1–80 字，城市 1–120 字，timezone 用标准 ZoneInfo 校验。
- [ ] membership 查询限定 active。禁止用旧 user.children 关系决定访问权。
- [ ] 家庭 PATCH 使用 expected_version 条件更新；冲突 409，失败不部分提交。
- [ ] 测试幂等同键同载荷只一家庭、异载荷 409，回放时已失去权限返回 404。
- [ ] 运行 `.venv/bin/python -m pytest tests/v2/test_family_access.py -q`。

代表性接口测试（数据通过 family_factory 生成，角色值为本计划定义枚举）：

```python
def test_viewer_cannot_change_family(client, family_factory, auth):
    family, members = family_factory(roles=["admin", "viewer"])
    response = client.patch(
        f"/v2/families/{family.id}", headers=auth(members[1]),
        json={"name": "新名字", "expected_version": family.version},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
```

### Task 4：邀请与成员并发事务

Files: families 邀请及成员处理、test_invitations.py、test_member_races.py。

- [ ] 先测接受、撤销、过期、错误凭据、已使用、同人重试、已有成员不消耗、不提权。
- [ ] `secrets.token_urlsafe(32)` 生成凭据；数据库仅存 sha256。预览和接受用 POST，分享路径携带的 token 禁止进入日志；只在预览返回家庭最小信息。
- [ ] 接受锁 family 后锁 invitation，校验有效期和成员，再写 membership、accepted_by；并发不同用户只一人消费成功。
- [ ] 成员降级、移除、退出使用相同 family 锁，更新 family.version；两位 admin 同时退出时一成功一 409，剩余至少一 admin。
- [ ] `.venv/bin/python -m pytest tests/v2/test_invitations.py tests/v2/test_member_races.py -q`；race 测试使用独立 MySQL 连接和 barrier，不能以 SQLite 通过代替 MySQL 行锁验证。

### Task 5：孩子档案和测量

Files: children 全部、migration 孩子测量表、test_children.py。

- [ ] 先测最小建档、不填身体/照片、未来生日、无穷/负数测量、跨家庭伪造 child_id、viewer 写入、同日两次测量、归档。
- [ ] 按第 5 节接口原子创建孩子和默认偏好；只允许文档列出的可写字段，客户端不能指定 family_id/created_by 覆盖路由归属。
- [ ] PATCH 支持 null 清肤色等可空信息，未传字段保持原值；改身高体重走 measurements 接口追加，不回写覆盖旧历史。
- [ ] 生日按照家庭时区验证，时钟由 core/clock.py 注入；归档前版本校验通过 query expected_version，DELETE 查询明确校验。
- [ ] 运行 `.venv/bin/python -m pytest tests/v2/test_children.py -q`，验证被归档孩子不出现在有效列表，单独查询返回 404。

### Task 6：初始偏好与成员退出衔接

Files: preferences 全部、test_preferences.py、families/service.py 的退出事务。

- [ ] 先测四种风格合法值、未知枚举 422、模式和指定成员互斥规则、同家庭成员约束、viewer 写入失败。
- [ ] 家庭 profile 与成员 profile 以 owner_key 唯一；profile 创建及更新遵守 expected_version，首次个人 profile 0→1；重复并发创建返回 409。
- [ ] 实现 settings 和 profile 的读写，A 仅保存显式偏好，不生成“学习完成”或假推断标签。
- [ ] 指定成员退出后同事务恢复 family 并 bump settings.version；测试并发指定/退出不能留下失效成员引用。
- [ ] 运行 `.venv/bin/python -m pytest tests/v2/test_preferences.py tests/v2/test_member_races.py -q`。

### Task 7：小程序启动与家庭协作页面

Files: project.config、app、config、services、stores、login/families/family-detail/invitation 页面、context/session 测试。

- [ ] 创建新版目录内 project.config：miniprogramRoot=`./`，appid 沿用已核实的项目 appid；导入的是 `miniprogram-v2` 目录，不修改旧项目配置。
- [ ] API 根地址从 config.js 单点读取，开发默认 `http://127.0.0.1:8001/v2`。app 模块顶层不调用 getApp；请求依赖 session 模块，避免启动循环。
- [ ] 本地 key 以 v2:user_id:family_id 分区；只保存必要用户状态，token 独立，退出清除当前身份缓存和待处理邀请。
- [ ] 异步读取用上下文 epoch，旧请求返回时丢弃；401 清理并登录，网络失败保留明确标注的缓存，不能把缓存存在当鉴权成功。
- [ ] 邀请页面登录前暂存 pending token、登录后 POST preview；用户点击加入才 accept；接受成功切家庭。返回已有家庭不升级角色。
- [ ] 家庭页面提供成员列表、按角色显示操作、退出/移除/降级冲突错误。界面禁用只用于减少误操作，后端仍强制授权。
- [ ] 运行 `node --test miniprogram-v2/tests/context.test.js miniprogram-v2/tests/session.test.js`，覆盖切账号清理、迟到响应、401与网络失败差异、邀请登录恢复。

上下文更新条件示例（实现在 context.js 并导出工厂以便测试）：

```javascript
function createContextStore() {
  let epoch = 0
  let current = null
  return {
    select(value) { current = value; epoch += 1; return epoch },
    capture() { return { epoch, current } },
    isCurrent(ticket) { return ticket.epoch === epoch },
    clear() { current = null; epoch += 1 }
  }
}
```

### Task 8：多宝档案与偏好页面

Files: children/child-edit/preferences 页面；app.json 注册全部七页。

- [ ] 家庭无孩子时显示添加入口；viewer 显示等待可编辑成员添加的状态，不能出现可提交表单。
- [ ] 昵称/生日、四种风格、可跳过肤色、身高体重未知/测量日期、舒适选项；保留失败前填写内容，提交中防连点并固定幂等键。
- [ ] 风格配合示例图片展示；执行时制作/选取有权使用的服装示例资源，不将整张参考设计稿当背景、不加载儿童真实私人照片作为演示资源。
- [ ] 编辑提交 expected_version；409 展示重新加载选择，不自动覆盖其他成员修改。
- [ ] 依据选择指定成员时仅列同家庭有效成员；viewer 只读；个人偏好与共同偏好标题明确。
- [ ] 当前孩子用 id 保存；归档/移除后重新读取列表，原 id 不存在则选择有效首项。所有页面注册、路径、按钮事件静态核对通过。
- [ ] 在微信开发者工具验证至少两种窄宽屏、较长昵称与全部可空字段，无横向溢出或遮挡；不要以浏览器 HTML 预览替代小程序运行验证。

### Task 9：阶段验收与运行说明

Files: docs/runbooks/zhida-v2-local.md、zhida-phase-a-acceptance.md。

- [ ] 在独立 `zhida_kids_v2_test` 库迁移并运行 `.venv/bin/python -m pytest tests/v2 -q`，MySQL race 用例必须实际执行，缺库属于未完成而非 skip 后称通过。
- [ ] 执行 `.venv/bin/python -m compileall app/v2` 与 Node 测试；逐页 JS 语法检查。
- [ ] 独立开发库 `zhida_kids_v2_dev` 迁移后，运行 `.venv/bin/uvicorn app.v2.main:create_app --factory --host 127.0.0.1 --port 8001`。端口占用选空闲端口并同步 config，不结束未知进程。
- [ ] HTTP 闭环：三个测试身份 A/B/C；A 创建家庭、孩子，B 接受 viewer 邀请可读不可改，C 非成员 404；A 将 B 改 editor 后能更新；A 移除 B 后原 token 下一次访问 404。
- [ ] 开发者工具导入新版目录，完整运行登录/家庭/邀请/多宝/偏好；真实微信登录验证使用开发者工具或真机实时 code。测试身份通过不等于真实微信登录已验证。
- [ ] 真机微信分享邀请需要有效小程序开发或体验版本，记录实际是否完成；未具备分享条件时明确列为外部验收项，不用模拟请求代替宣称成功。
- [ ] 文档写明启动目录、迁移命令、配置示例、测试身份模式、实际验证结果、尚未完成的真实外部验证；不写密钥或用户照片。
- [ ] 只提交本阶段新增与必要修改的文件，提供运行 URL 与新版开发者工具导入路径。旧版回归运行与数据库均保持可恢复。

## 7. 最终通过条件

- [ ] 数据库迁移可以重建新库，不修改旧库；应用启动无建表副作用。
- [ ] 角色矩阵与并发邀请/管理员退出测试通过；移除权限立即生效。
- [ ] 无照片与身体信息未知能建档；多宝切换和多成员更新不串数据、不静默覆盖。
- [ ] 初始风格、舒适信息和推荐依据持久化，退出重进可恢复。
- [ ] 小程序已注册页面均存在并实际可进入；已完成流程可由用户复现。
- [ ] 模拟验证和真实微信验收结果分别记录；A 不声称已经完成推荐、上传或偏好学习。

## 8. 自检与依赖

表/路由/任务映射：identity→2；family/membership/receipt→3；invitation→4；child/measurement→5；settings/profile→6；小程序→7/8；集成→9。

任务 5 与 6 属于同一数据库迁移版本，创建孩子默认偏好由 preferences service 提供，先实现该最小函数再开放 POST child。完整测量、成员并发、偏好测试在迁移全部表后运行。

本文将端到端行为和契约细化到文件与测试级别；代码片段是关键约束示例，实际实现仍需按任务编写完整模块，不能将片段当作已完成代码。B/C/D 不在本阶段实现范围。
