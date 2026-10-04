# 智搭 V2 本地运行

新版在 `codex/phase-a` 分支的 `.worktrees/phase-a` 工作区中，旧版目录和数据库保留。

## 后端

进入新版工作区的 `backend` 目录。运行环境使用 Python 3.13 的独立 `.venv`：

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-v2.txt
```

配置文件为本目录 `.env.v2`，模板 `.env.v2.example`。本地已提供此文件时不要覆盖。使用独立数据库 `zhida_kids_v2_dev`，不可填写旧版 `zhida_kids`。

首次在有 MySQL 管理权限的本机配置时，可以使用 provisioner 从已有本地配置私下读取连接信息，建立仅有新版三个数据库权限的账号：

```sh
.venv/bin/python scripts/setup_v2_local.py --source-env /absolute/path/to/old/backend/.env
```

它不会替换已有 `.env.v2` 或已有数据库账号密码，不输出密钥。首次执行后 `.env.v2` 权限为 0600。真实微信登录需要其中 `V2_WECHAT_APPID` 和 `V2_WECHAT_SECRET` 有效，默认 mock 关闭。

执行迁移并启动：

```sh
.venv/bin/python -m alembic -c alembic-v2.ini upgrade head
.venv/bin/uvicorn app.v2.main:create_app --factory --host 127.0.0.1 --port 8001
```

- `http://127.0.0.1:8001/health` 检查进程。
- `http://127.0.0.1:8001/ready` 检查数据库和迁移版本。
- `http://127.0.0.1:8001/docs` 查看 `/v2` 接口。

2026-10-03 本轮后台进程 PID 为 `36392`；当前 PID 记录在工作区 `.cache/v2-server.pid`，日志在 `.cache/v2-server.log`。这是本轮启动的本地进程，不是开机自动启动服务；电脑重启后按上述命令重新启动。

### 目标日天气

首页才请求定位。定位被拒绝时，可进入“选择城市”输入城市名称；未配置天气服务或上游失败时不会显示模拟温度。C 阶段首页通过搭配 context 获取今天或明天的实际日期及对应预报，不用当前实况代替明日天气。在 `.env.v2` 中填写和风天气控制台提供的专属 API Host 和 API Key：

```sh
V2_QWEATHER_API_HOST=https://your-api-host.qweatherapi.com
V2_QWEATHER_API_KEY=YOUR_API_KEY
```

保存后重启 FastAPI。API Host 不是旧版共享 `devapi.qweather.com` 地址；密钥只留在本机配置文件，不提交到仓库。C 阶段使用城市定位与逐日预报接口，并核对返回的目标日期。预报不可用时提示天气未知，选定前需要家长明确核对。

启动不自动建表。缺迁移时 `/ready` 返回 503；运行迁移后恢复。结束当前服务可在启动终端按 Ctrl+C。端口占用时选择空闲端口，并同步小程序 `config.js`。

## 微信小程序

在微信开发者工具导入新版工作区中的 **`miniprogram-v2` 目录**。该目录有自己的 `project.config.json`，不要把旧项目根目录当新版导入。

本地接口地址默认 `http://127.0.0.1:8001/v2`。开发者工具本地调试使用项目设置中的“不校验合法域名”。这仅适用于本地调试；真机中的 127.0.0.1 指向手机自身，真机联调需要手机可访问的后端地址，体验/正式版本需要配置合法 HTTPS 域名。

A 阶段验证顺序：选择孩子年龄 → 首次保存时登录 → 自动建立个人空间与孩子档案 → 首页自动定位／手选城市 → “我的”按需进入孩子和家庭管理 → 第二账号接受邀请并验证只读或编辑权限。真实邀请分享需要具有权限的开发/体验版本与两个账号；模拟 HTTP 测试不替代此项。

B 阶段新增衣橱及真实衣物录入：衣橱 → 选择本批默认宝贝 → 连续拍照／相册多选／手填 → 集中核对候选 → 明确确认入库。多件图不自动选择；识别失败仍可在同图手填多件；合身按孩子分别记录，待洗／找不到按实物共享。导航为搭配／衣橱／我的。

### C 每日搭配

本地启用 C 前，按上面的迁移命令升级至 `0004_daily_outfits`。实施验证最初只迁移了隔离测试库。用户反馈网络连接失败后，2026-10-03 已备份 `zhida_kids_v2_dev` 并升级到 `0004_daily_outfits`，启动本地 API；`/health` 和 `/ready` 均返回 200，小程序孩子档案页已重新连接成功。基础规则建议不需要搭配 worker。

搭配首页 → 今天穿／准备明天 → 场景和偏好依据 → 推荐实物 → 替换、固定、本次不穿及备用 → 选定前核对 → 新增或保存修改。只读成员可查看已有共享建议和已选方案。衣物详情也可发起独立草稿并返回原建议。天气未知、衣物资料变化、备用待核、共用冲突须明确处理，草稿和候选不会占用实物。

同日可选多套，每套保留编号；修改原方案保留身份并增加版本。主搭配和已确认备用才产生计划占用。分时共用需要填写所有相关孩子的非重叠时段与原因，不能改动其他已确认安排。保存响应丢失时查询原操作，查不到仍为未知；明确核实未执行后才可重新开始。其他独立草稿可准备，同家庭同日的再次保存须等原结果明确。

搭配模型默认关闭。需要启用时在本机配置 `V2_OUTFIT_PROVIDER=qwen` 或 `ark`、对应 `V2_OUTFIT_MODEL` 及同供应商的既有 API Key，并重启 API。不要把不同供应商的 model ID 混用。模型只排序服务器已校验的真实组合，不接收孩子姓名或照片；供应商失败回退基础规则。启用模型会产生外部调用费用，本次没有调用收费模型。具体实现与验收范围见 [C 阶段验收记录](zhida-phase-c-acceptance.md)。日历、试穿与偏好学习仍在后续阶段。

### B 图片与识别 worker

先运行迁移到 `0003_wardrobe_intake`。API 和 worker 使用同一 `.env.v2` 与 `V2_PRIVATE_STORAGE_DIR`，该目录须为持久、私有的绝对路径；默认在 `backend/var/private-media`。备份数据库时同时备份该目录。本期采用服务端私有文件存储，不将它挂到静态资源服务器；多实例部署须共享持久目录。上传限 12 MB、24 MP，核验图片内容、纠正 EXIF 方向并移除照片元信息，再生成服务器核验 hash。相同 hash 只复用图片资产，不自动合并实物。

在另一个终端进入同一 `backend`，启动独立任务进程：

```sh
.venv/bin/python -m app.v2.jobs.worker
```

仅处理一个领取周期可用 `--once`。任务保存在数据库，API 重启不丢队列；worker 用租约和领取身份防迟到结果写入。未知上游调用结果不会自动再次付费请求；可继续手填。照片上传不会等待识别，批次默认孩子始终以创建时的服务端结果为准。

当前本机没有识别供应商密钥，上传后会诚实显示“识别尚未配置，可继续手填”，不会生成模拟候选。需要启用时按模板在本机配置，勿覆盖已有微信、数据库与天气配置：

```sh
V2_RECOGNITION_PROVIDER=qwen
V2_RECOGNITION_MODEL=qwen3.7-plus-2026-05-26
V2_QWEN_API_KEY=YOUR_API_KEY
```

ARK 可设 `V2_RECOGNITION_PROVIDER=ark`、`V2_RECOGNITION_MODEL=doubao-seed-2-0-mini-260428` 和 `V2_ARK_API_KEY`；不要把 Qwen 的 model ID 用于 ARK。模型试点选择与项目测评边界见 `../design/phase-b-review/recognition-model-comparison.md`。保存配置后重启 API 和 worker。默认自动重试上限为 3，输出限制 4096 tokens；原始候选 JSON、模型、用量、提示词 hash 和归一结果保存在私有 attempt trace 中，不向家庭其他成员开放。

### B 恢复、权限与真机验收

云端图片与候选草稿仅由录入人且当前具备编辑权限者继续。仅查看成员可读已入库衣物、移除历史和对应原图；不能读草稿、上传或写衣物。照片保存失败会提示退出可能丢失；本机保存仅保证同设备续传；服务器确认持久保存后才显示云端可恢复。降级停止草稿读取并撤下可见草稿；离开家庭清该家庭缓存及本机照片，不退出账号或清其他家庭。

确认、批量操作、移出／恢复都保留稳定操作身份。响应丢失时先查询原操作；查不到仍是 unknown，禁止以此认定失败。用户可明确“核实未执行”，服务器在同一家庭锁内保存原操作终态，阻止迟到原提交；只有明确失败项才能以新操作重试。版本冲突保留本人填写并展示最新内容，重新核对后才保存。

真机检查须覆盖连续拍摄期间继续添加、相册多选、保存失败／断网续传、杀进程重开、原图鉴权、第二账号 viewer、上传／原图期间撤权、候选与已有衣物的冲突、共用转交、最新移除记录恢复以及窄屏／长名称。首次实现的原生 UI 自动控制两次超时；2026-10-04 已能读取微信开发者工具，确认修改前的重复导航等差异，但最终设计对齐后的视觉复查因 Mac 锁屏暂停，仍无最终原生截图或双真机验收。范围与最新回归见 [B 设计核验记录](../design/phase-b-review/design-alignment-verification.md)；前端 mock 和 HTTP 测试不代表真机检查通过。真实儿童衣物识别准确率仍须用标注集调用已配置供应商对测，本次未调用收费模型。

## 自动化测试

在新版 `backend` 中运行：

```sh
.venv/bin/python -m pytest -c pytest-v2.ini -q
.venv/bin/python -m compileall app/v2
```

必须使用 `pytest-v2.ini`，它阻止旧测试 conftest 加载旧应用。`.env.v2` 中 `V2_TEST_DATABASE_URL` 必须指向 `zhida_kids_v2_test`。MySQL 迁移回退单独在 `zhida_kids_v2_migration_test` 中执行；测试会清空这两个专用测试库，禁止放业务数据。SQLite 快速测试不能代替 MySQL 并发验证。

在新版工作区根目录运行：

```sh
node --test miniprogram-v2/tests/*.test.js
```

测试中的微信响应使用注入的测试接口，与运行服务的真实微信配置隔离。B/C 契约测试会启动临时 SQLite、私有图片目录和本机 HTTP 服务，通过实际小程序 JavaScript 服务调用真实接口；没有向微信或模型供应商发请求。C 契约还会故意丢弃服务器已提交的保存响应，验证查询恢复与原回执重放。`node` 须在 PATH 中。MySQL 竞态覆盖换操作确认、confirm／resolve 两种锁顺序、回滚后核实、共享关系重查、双 worker 单次领取，以及 C 的重复选定、竞争修改、迟到提交围栏、推荐单次领取和撤权后的历史查询。请分别记录自动化、开发者工具和双真机结果，不将未执行项目标为通过。

迁移环境按 [Alembic 官方迁移教程](https://alembic.sqlalchemy.org/en/latest/tutorial.html) 独立配置，并增加新版数据库名保护。
