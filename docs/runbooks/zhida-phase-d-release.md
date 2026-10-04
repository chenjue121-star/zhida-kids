# 智搭 D：离线迁移、发布切换与回退演练

日期：2026-10-04。工作区：`.worktrees/phase-a`。D 数据库版本为 `0005_personalization_calendar`。

本手册的自动演练只接受明确标记为 synthetic 的 JSON，并创建全新的 SQLite 输出目录。它不连接旧数据库、不下载旧 URL、不启用模型、不覆盖 `.env.v2`、不切换真实使用入口。真实历史是否迁移、身份如何关联及旧图片资产归属仍需单独决定。MySQL 迁移回环与 SQLite 数据恢复证据分别记录，不能互相代替。

## 执行与产物

在新版工作区的 `backend` 中执行。每次使用一个新输出目录；已存在目录会被拒绝，失败产物保留用于定位，不自动清空。

```sh
.venv/bin/python scripts/phase_d_rehearsal.py \
  --source tests/v2/fixtures/phase_d_legacy_wardrobe.json \
  --output ../.cache/phase-d-release-rehearsal-20261004

.venv/bin/python -m pytest -c pytest-v2.ini -q tests/v2/test_d_release.py
```

本次实际运行得到 **19 passed**，仅有既有 Starlette/anyio 弃用警告。初次测试先观察到工具不存在；另以失败测试定位并修正 SQLite 第一层 SAVEPOINT 脱离调用者事务的问题、索引变化未进入恢复指纹的问题，以及恢复目录嵌入备份目录导致原清单变化的问题。

本次 CLI 的 [report.json](../../.cache/phase-d-release-rehearsal-20261004/report.json) 记录：

| 检查 | 结果 |
| --- | --- |
| A/B/C 旧 schema 下 D `/ready` | 503 |
| 迁移到 D 后 `/ready` | 200 |
| 来源记录首次导入 | 31 条 |
| 同来源再次导入 | 31 条复用、0 条新增 |
| 来源日记 | 2 条，0 条转成方案或穿着事实 |
| 远程图片下载 | 0 次 |
| 模拟切换后的备份恢复 | 数据、schema、索引及媒体字节一致 |
| 恢复 D 备份后的 `/ready` | 200 |
| 恢复旧 schema 后仍用 D 应用 | 503，需配套旧应用版本 |
| 真实发布／生产数据库写入 | 未执行 |
| MySQL 带数据联合恢复 | 本工具未验证 |

输出包含：`before-migration/`（0004 schema）、`validated-release/`（D schema 与导入记录）、`rollback-restored/`（恢复 D 备份）、`before-migration-restored/`（恢复 0004 备份）、`active-simulation.json`（仅本地模拟入口指针）、`report.json`。备份目录为 0700，数据库、媒体和清单文件为 0600。备份媒体为明确的合成字节夹具，没有冒充旧照片或可访问的 COS 资产。

## 导入语义

[固定来源夹具](../../backend/tests/v2/fixtures/phase_d_legacy_wardrobe.json) 对应旧版 `app/models.py` 的四张表：`users`、`children`、`clothing`、`outfit_diaries`。顶层必须有 `schema_version: 1`、`synthetic: true`、ISO `recorded_on` 及这四个数组。来源 ID 为正整数；生日、日记日期使用 ISO 日期。真实导出时不得包含会话密钥、接口密钥或 token；真实导出目前不由此 CLI 接受。

- 一个旧用户映射到一个隔离的个人家庭及管理员，旧孩子映射到对应家庭。演练 openid 为来源命名空间与旧 openid 的散列，带 `legacy:` 前缀，避免不同来源和真实微信身份发生碰撞；它不完成真实账号登录关联。
- 身高和体重都未知时不生成测量记录；有效测量以来源记录日期保存。旧性别、照片 URL、品牌、旧计数等未映射字段保留在私有来源记录，不能成为新推断事实。
- 衣物按来源 ID 映射实物，不按照片、hash 或同款名称合并。旧 `active` 明确映射 `ready`，`washing` 和 `missing` 保持对应状态，`removed`/`archived` 保持移出。类别支持当前英文枚举及夹具中的明确中文别名；未支持的类别、状态或无效日期拒绝整个导入，等待人工核对。未知颜色、图案、厚薄按 `unknown` 保存。
- 合身始终从 `unknown` 开始，由家长核对后修改；旧状态不证明当前合身。来源 URL 只保留出处，不生成 `media_assets`，不声明图片可访问。
- `legacy_source_records` 用 `(source_namespace, entity, source_id)` 唯一映射并保存原始 payload 与 hash。重复相同 payload 复用目标；相同身份的 payload 变化拒绝执行，没有部分新增。应用会话不能修改或删除来源记录。
- 旧日记的 `target_table` 和 `target_id` 均为空。评分、心情、wear_count、last_worn_at 只属于旧来源；不会生成 `OutfitPlan`、反馈事件、日历安排、已穿事实或推断偏好。

固定衣橱含 0、6、12、24、48、72、83 月龄七个孩子、21 件实物及待洗、找不到、移出状态。真实 HTTP 回归先验证未知合身不能推荐，再通过 owners API 明确核对合身，验证孩子间实物隔离、低温外套需求、热天排除厚外套、无效预报变为未知、明天实际日期和只读成员拒绝生成建议。测试注入微信与天气响应，不请求外部供应商。

## 备份与恢复边界

备份使用 SQLite 在线备份获得一致数据库，再复制私有媒体。清单保存逐文件 SHA-256、大小及逻辑数据库指纹；指纹包含所有表行以及表、索引、视图和触发器定义。源文件、媒体树和输出父目录中的符号链接被拒绝。恢复前核对文件清单、路径、hash、SQLite integrity 和数据库指纹；损坏备份不会创建恢复目录。恢复目录不能置于原备份内，避免改变原备份的文件清单。恢复后重复核对数据库和媒体；额外文件、索引／行变化或媒体变化判为 drift。

演练在暂停写入的合成环境中执行。实际 MySQL 发布还需在隔离的 MySQL 恢复库验证完整 dump、外键、表行、迁移版本、私有资产引用及媒体 hash；必须同时备份数据库和 `V2_PRIVATE_STORAGE_DIR`。若继续处理新写入，回退到旧备份会丢失备份之后的变更，不能把备份恢复当作无损降级。schema 降级会删除 D 反馈、来源映射等数据，不能在业务库直接运行 downgrade 代替完整回退方案。

真实切换前：保存应用版本与配置快照；停止或暂停 API/worker 写入；备份数据库和私有媒体；在隔离环境确认恢复；按明确目标 schema 执行迁移；启动匹配应用和 worker；核对 `/health`、`/ready`、私有图片权限及完整业务流程；最后才切换小程序可访问的合法 HTTPS 入口。异常时保持暂停写入，恢复数据库、媒体、匹配应用与配置，然后复查 readiness 和权限。此顺序是尚待执行的发布检查，不代表已部署。

## 已授权的真实模型烟测

本次用户授权使用旧版 `backend/eval/recognition/dataset/images` 里的少量素材。私下读取已有旧版 ARK 配置，不复制密钥到 `.env.v2`，通过现有 V2 `ArkProvider` 和总调用上限 `CallBudget(2)` 发起 **2 次实际调用**，无重试或额外供应商调用，未写任何家庭或候选批次。配置和返回 model 均为 `doubao-seed-2-0-mini-260215`。

| 已发送图片 | 结果 | 归一化候选 | 耗时 | token 用量（输入／输出／总量） |
| --- | --- | --- | --- | --- |
| img003.jpg | ok | 1：top | 2034.718 ms | 1630／62／1692 |
| img004.jpg | ok | 3：outerwear、top、bottom | 3297.593 ms | 1605／147／1752 |

最初备选 `img001.png` 无法解码，在生产预处理阶段拒绝，未发给模型、未消耗 API 调用。可读取的替代输入 `img004.jpg` 用完剩余一次调用额度。脱敏烟测指标保存在 [summary.json](../../.cache/phase-d-model-smoke-20261004/summary.json)，文件权限 0600。原始候选私有缓存不作为公开验收日志展示。

此项证明配置、接口、生产预处理及结果归一化可完成；两图没有人工审核真值，不能计算准确率，也不证明搭配审美或 0–6 岁所有场景质量。完整识别评测仍需人工审核标注及样本授权，见 [识别评测手册](recognition-evaluation.md)。

## 仍需外部验收

开发者工具编译与源码回归不替代双账号／双真机。真实微信登录、分享与一次性邀请；viewer/editor 的读写、降权、移除及在途响应；相机连续拍摄、相册多选、临时文件配额、断网续传、杀进程恢复、原图鉴权；窄屏／长名称；实际天气今天／明天的对应预报；真实衣橱的识别和搭配质量；手机可访问的后端、合法 HTTPS 域名及体验／正式发布入口都需逐项记录结果。未经实际执行的项目保持待验。
