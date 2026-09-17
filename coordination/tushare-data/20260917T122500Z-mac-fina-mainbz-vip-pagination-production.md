# fina_mainbz_vip 生产分页接入

- 时间：2026-09-17
- 数据所有者：Mac 本地归档；云端保持供应商停写，只同步代码与研究子集。
- 代码提交：`cba5f52c3b0ffe23e3a26cd75eabac4016bd3a2b`
- 问题：`fina_mainbz_vip` 继承普通 `fina_mainbz` 的 100 行上限，真实 10000 行响应被错误标记为不可拆分阻塞。
- 官方边界：doc 81 推荐 VIP 按季度/类型获取全市场主营业务数据，但输入表未公开分页参数或行数上限。
- 实际账户验证：20260630/P 的 `limit=10000` 在 offset 0、10000、20000 均成功返回 10000 行；offset 0 与 10000 无精确行重叠；offset 999999 返回供应商空结果码 50101。证据见 `docs/tushare-fina-mainbz-vip-pagination-probe-20260917.json`，不含 Token 或原始行。
- 实现：VIP 运行合同使用 10000 行页、offset/limit 分页；通用入口仅允许原 global 分页或带 `pagination_live_verified` 标记的合同自动补 limit，未放开其他未经验证接口。
- 测试：86 项相关测试通过，覆盖 VIP 满页续页、重复页保护、既有 global/fund_manager 分页、归档安装、固定版本读取和速率策略。`ExtendedPipeline.test_bounded_planning_resumes_across_connection_and_deduplicates` 在修改前后的 master 都是预期 17/实际 12，记录为无关既有失败。
- 副本验收：12 GB 一致性副本规划新增 438 个 VIP 根任务，旧 438 个任务保留；393367 条尝试与 390033 个有结果任务保持；`PRAGMA quick_check` 为 `ok`；上游调用 0。
- 生产规划：`history:fina_mainbz_vip` 因合同策略变化重置并完整规划 438 个分页根任务，耗时约 0.17 秒，`failed_stage=null`。
- 真实采集：首轮总 148 次请求，其中 VIP 3 个满页共 30000 行、2 个非满页共 731 行；次轮总 181 次请求后，VIP 累计 6 个满页共 60000 行、5 个非满页共 1811 行，生成 6 个 offset=10000 后续页。当前新合同任务为 11 done、427 pending 根任务、6 pending 后续页；旧合同 239 blocked、60 done、139 empty 保留作证据。
- 发布：本地运行副本与仓库关键文件 SHA-256 一致，LaunchAgent 正常运行；固定版本 `data-35c4a1cd0bb0394af2ba84347f419f03a8dd4cfbc4a10b1eb4e69bed68f7c84d` 发布成功；云端 handoff 通过并对齐同一代码提交。
- 服务影响：只自然排空并重载 `com.quantmind.tushare-archive`；QuantDB、研究缓存及其他服务未停止。
- 后续：保持普通逐股 `fina_mainbz` 任务，直到 VIP 各季度/类型分页完整、读取覆盖核对通过后再评估退休重叠任务。全量历史补采继续，不声明历史已经完成。
