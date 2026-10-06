# Lite 衣物填充实施计划

依据：[设计](../specs/2026-10-06-lite-intake-design.md)。复用 `codex/phase-a`，不提交、合并或部署。

- [x] 默认配置与离线契约：`app/v2/core/config.py`、`.env.v2.example`、`tests/v2/test_lite_recognition.py`；先证明旧默认不满足 Lite，再验证 ARK 原提示词、JSON、禁用 thinking、安全 trace、缺 key 手填及显式 Qwen。
- [x] 已确认库存导入：新增 `scripts/seed_confirmed_inventory.py` 与 `tests/v2/test_confirmed_inventory_seed.py`。先测试源哈希/权限/未知值/幂等和保留人工修改，再实现验证、私有媒体处理、稳定批次与候选填充。
- [x] 本机接通：私下复用既有 ARK key，补充 `.env.v2`；保存原配置备份（0600），重启已知本地 API，开启识别 worker，核对健康状态和已有排队项的真实结果。不向输出暴露密钥。原队列 6 请求成功、9 候选。
- [x] 数据填充：校验并导入确认清单，保留 47 原图与 75 个待核对候选；再次执行检查幂等，核对 Clothing 数量不变与未知字段数量。批次 4，重复新增为 0，识别调用为 0。
- [x] 合身未知提示：沿用现有页面样式，按单品显示本批待确认数，保存弹窗按当前已选数；不改原普通默认和确认行为。6 个新前端测试通过。
- [x] 回归、独立审查与文档：V2 后端 650、小程序 344 通过，独立审查无阻塞问题；更新本地运行文档与 [验收记录](../../runbooks/zhida-lite-intake-20261006.md)。
- [ ] 导入后原生草稿视觉核验：Lite 的既有 9 候选入口已在开发者工具看见，75 件导入后最后检查遇 Mac 锁定，等待用户手动解锁。双真机不在本轮范围。
