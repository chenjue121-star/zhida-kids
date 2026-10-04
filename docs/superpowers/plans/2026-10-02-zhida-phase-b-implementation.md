# 智搭 B 阶段实现计划

> For agentic workers: use subagent-driven-development；后端实现与前端实现按本文接口契约协作，分阶段做规格和质量复核。

日期：2026-10-02。用户最新指令「B 阶段实现」授权以最新五组画稿、箭头及选中态校准和已讨论规则进入实现。此前评审记录保留历史状态，不再次请求流程确认。

**Goal:** 交付真实照片录入、可恢复的本人草稿、可选的模型识别、候选明确确认入库，以及家庭实物衣橱的浏览、共用、转交、移出恢复与批量状态管理。

**Architecture:** 在独立 v2 模块与专用 MySQL 数据库中扩展；家庭实物与孩子合身关系分离。私有媒体以鉴权下载访问。识别任务持久化，由独立 worker 领取，外部调用期间不持有数据库锁。模型未配置时显示可手填，不制造识别成功。候选确认才建立实物，稳定操作身份、候选唯一映射和事务内单项隔离保障恢复与部分成功。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、MySQL、httpx、Pillow、微信原生小程序、Node test runner。开发私有文件存储；生产存储接口可配置，不以公开静态目录暴露原图。默认模型试点为 Qwen3.7 Plus，ARK 可配置，实际儿童衣物准确率尚待项目对测。

基线：后端 65 tests passed；前端 77 tests passed。复用 `.worktrees/phase-a` / `codex/phase-a`，保留已有 A 改动及主目录用户变更。

## 冻结的行为

- 批次固定录入人、家庭、开始时默认孩子；仅本人且当前 admin/editor 能访问草稿。viewer 可查看家庭实物、历史和已确认原图。
- 照片数与候选数独立；一图可多件。只有无人工介入的首次可靠单件实拍可预选，多件与迟到新增均不选。未选仍保留，放弃需明确操作。
- 颜色、图案、厚薄可 unknown，类别确认必填。合身默认 fit，可穿默认 ready，最终按钮前明确说明；新孩子关系与恢复要求显式 fit，允许 unknown。
- 资产 hash 仅复用存储，不合并实物。同图已有实物须明确使用已有或创建另一件；使用已有不覆盖属性、照片、状态和已有 fit，新关系/恢复先逐件核对。
- 迟到结果不覆盖人工草稿、不自动勾选、不提前建物。失败可逐照片重试或在同图继续手填其他实物。
- 操作未知先查原 operation；unknown 不等于失败，禁止重新提交。成功项不重交，明确失败可用新操作重试。
- 状态属于实物，fit 属于孩子关系。共享不复制；转交再次验证版本及唯一有效使用者。归档孩子仅保留历史，不成为新归属，也不在恢复时复活。
- 移出影响全部使用者但保留历史；恢复同一 ID、原状态不变，每个有效使用者重新确认 fit。别人已恢复返回当前结果。
- 批选限当前已加载且筛选匹配的 ID；分页新增不自动选择，换筛选、孩子或退出清空。批量目标状态初始未选。
- 403 停止草稿与写操作并刷新能力；撤权失效旧响应、清该家庭文件缓存，保留账号和其他家庭。409 保留本人填写并展示最新内容，显式核对后保存。
- 沿用白底、品牌绿 #267a42、44px 触控、右侧独立居中箭头及圆形浅绿选中态。导航为搭配／衣橱／我的；C/D 不在本期。

## 前后端接口契约

前缀 `/v2/families/{fid}`，ID 字符串，更新使用 PUT。公共字段如下：

```text
Garment: id, version, name, category, colors[], pattern, thickness,
 state, asset_id|null, archived_at|null,
 owners[{child_id,nickname,fit,archived:boolean}], last_owners[], history_owners[]
category: top/bottom/outerwear/dress/onesie/shoes/accessory
pattern: solid/stripe/plaid/print/dots/unknown
thickness: thin/medium/thick/unknown; state: ready/washing/missing
fit: small/fit/large/unknown; color: black/white/gray/red/orange/yellow/green/blue/purple/pink/brown/beige/multicolor/unknown
Candidate: garment fields, id, version, item_id, selected, discarded,
 ownership_exception:boolean, confirmed_garment_id|null,
 duplicate_garments[], bbox|null, dirty_fields[]
Item: id, client_id, source:camera/album/manual, asset_id|null,
 status:queued/running/succeeded/failed/uncertain/manual, error|null, candidates[]
Batch: id, version, default_child_id, created_by, items[], candidates[],
 pending_candidates_count, unresolved_items_count, has_pending
Operation: operation_id, status:completed/unknown,
 results[{candidate_id|id,status:success/failed,kind:new/existing,
 garment|null,error:{code,message}|null}], counts{new,existing,failed}
```

| Method/path | Payload / response |
| --- | --- |
| GET `/garments` | query child_id/category/state/fit/shared/archived/history_child_id/cursor/limit; `{items,total,family_total,next_cursor}` |
| GET `/garments/{id}` | Garment；有效成员可读移出详情 |
| PUT `/garments/{id}` | expected_version + name/category/colors/pattern/thickness/state；不可静默改关系 |
| PUT `/garments/{id}/owners` | expected_version + owners[{child_id,fit}]；至少一位有效孩子 |
| POST `/garments/{id}/transfer` | expected_version + child_id + fit |
| POST `/garments/{id}/archive` | expected_version + Idempotency-Key |
| POST `/garments/{id}/restore` | expected_version + owners[] + Idempotency-Key |
| POST `/garments/bulk` | operation_id,action:state/archive,state?,items[{id,expected_version}]；逐项 results |
| GET `/wardrobe-operations/{operation_id}` | Operation；无已提交记录返回 status unknown |
| GET `/intake/batches` | 本人草稿数组，含 default_child_id/items_count/candidates_count |
| POST `/intake/batches` | default_child_id + Idempotency-Key；Batch |
| GET `/intake/batches/{bid}` | Batch，items 与 candidates 均返回 |
| POST `/intake/batches/{bid}/items` | client_id,source；Item（manual 可无图片） |
| PUT `/intake/batches/{bid}/items/{iid}/upload` | raw image bytes；Content-Type:image/jpeg/png/webp；Item，上传完成自动排入识别 |
| POST `/intake/batches/{bid}/items/{iid}/recognition` | 明确重试；Item，有限次数，权限失败不可普通重试 |
| POST `/intake/batches/{bid}/candidates` | item_id + name/category/colors/pattern/thickness/owners/state/selected；手填 draft |
| PUT `/intake/batches/{bid}/candidates/{cid}` | expected_version + 被改字段；标记 dirty_fields，confirmed 不可改 |
| POST `/intake/batches/{bid}/confirm` | operation_id,entries[{candidate_id,expected_version,action:new/existing,existing_garment_id?,expected_garment_version?}]；Operation |
| GET `/intake/batches/{bid}/operations/{operation_id}` | 原操作；无记录返回 unknown |
| GET `/assets/{asset_id}/content` | 鉴权二进制下载，仅本人草稿或本家庭已确认实物引用可读 |

对已有实物，若待确认孩子没有有效关系，返回 OWNER_REVIEW_REQUIRED；前端进入共用核对后再确认。已移出返回 RESTORE_REQUIRED。明确使用已有仅关联候选确认结果，不修改该实物。不可由猜测 bbox 创建新照片，原图始终可查看。

## 执行与验证

- [x] 1. 后端新增 `wardrobe/{models,schemas,router,service}.py`、`recognition/{models,schemas,router,service,normalize}.py`、`media/{service,storage,router}.py`、`jobs/worker.py`、供应商适配器；先写权限、关系、幂等和 worker 测试并确认失败，再实现。
- [x] 2. 新迁移 0003，同步 metadata、ready、隔离和迁移测试；仅专用 v2 库执行；回滚/升级与真实 MySQL 竞态验证。
- [x] 3. 前端新增 `services/{wardrobe,media,intake,garment-forms}.js` 与权限 epoch，先写乱序/恢复/未知结果/局部失败测试再实现。
- [x] 4. 原生页面 wardrobe、intake、intake-confirm、garment-detail、garment-edit、garment-owners、wardrobe-removed，首页真实衣物计数与三入口导航。编辑与候选保存语义分开。
- [x] 5. 规格复核，然后质量复核；修复后运行全量后端和前端测试、compileall、原生页面静态契约。
- [x] 6. 更新 `.env.v2.example` 与 `docs/runbooks/zhida-v2-local.md`：私有存储、worker、模型开关、迁移、真实模型及真机待验收边界。核实可用 DevTools 并做可执行原生检查。

```sh
cd backend
.venv/bin/python -m pytest -c pytest-v2.ini -q
.venv/bin/python -m compileall -q app/v2
.venv/bin/python -m alembic -c alembic-v2.ini upgrade head
cd ../miniprogram-v2
npm test
```

供应商调用单元测试使用注入 fake，不调用收费 API；未配置密钥时人工录入链路必须完整可用。没有项目真实对测或原生真机结果，不能把公开分数或页面静态检查写成验收成功。


## 实施时复核的补充契约（已落地）

- Item 增加 version/discarded；PUT item 明确放弃只停止未确认部分，已入库衣物保留。
- 手填 CandidateCreate 必填稳定 client_id，PUT 支持 ownership_exception；创建时自动识别非默认归属/fit例外，批量归属可显式保持 false并撤回已保存变更。
- POST batch operations/{op}/resolve 接受原完整 Confirmation；POST wardrobe-operations/{op}/resolve 接受原 Bulk，家庭锁内保存 NOT_EXECUTED 墓碑。查询缺记录仍 unknown。
- 单件 archive/restore 接受 operation_id，与 Idempotency-Key一致；有各自 /resolve 和通用 wardrobe 操作查询。前端 queryAction 仅查询，缺 pending 也不能转新 POST。
- last_owners 仅为最近移出快照，恢复预选与历史孩子筛选用它；history_owners保留全历史。
- 草稿列表仅返回 has_pending，数量排除已确认/放弃；GET 原 batch仍可核对历史。
- 识别成功零候选有效，保留有界私有 trace；首次可靠单件 camera可预选，其余和迟到追加不预选。

实施检查完成；原生 UI 控制两次超时，真机视觉与模型项目对测保留为待验收，不将任务6中的检查尝试当作真机通过。证据见 docs/design/phase-b-review/implementation-verification.md。
