# 主题：R01-P0.3 日增量绑定哈希真实化（p03_execution J5E1）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-J5E1（wave J5 attempt 1）
- 状态：**done**（J3R2 第 6 项）
- 提交：`herdr/r01-p0` @ `9ef9b9ee225e2d0e0a2ca3a0f770cfce3294d2fa`（仅 owns 4 文件）
- 证据：`<run>/artifacts/p03/h2/fixes-j5/README.md`

## 要点

1. 绑定哈希真实化：重建记录 `daily_increment_manifest_sha256s`（逐增量真实 manifest sha256）；None/空哈希（增量或基线）恢复**显式拒绝**不跳过。
2. 重建期强校验：绑定哈希作 expect——篡改增量 manifest/注册表换包在 rebuild 即拒绝。
3. 测试重写（真实哈希）：J4 绑定改造+空哈希拒绝；新增 J5 五用例（捕获真实哈希/篡改拒绝/换包拒绝/空哈希恢复拒绝/逐包发布逐段恢复==连续，含折算日 nav ≤1e-9，走真实注册表不手动换包）。
4. 注记：补齐并行 runner 侧在我 owns 的 r01_ledger.py 留下的未定义 `round_output` 调用（默认 True 行为不变，其 recovery.py 全精度调用可用；该文件归 p02r 未纳入本提交）。
5. 回归 326 passed、v2 十窗口 ALL_PASS、33/33 分红对账。

## 追加（J6E2，J3R3 第 6 项）

- daily_binding 热缓存：命中时仍执行期望绑定校验（`_verify_bound_increments`，方案 B——绑定哈希入键防不了同键内容篡改）；篡改/换包不因缓存绕过。测试 3 用例；回归 329 passed、v2 ALL_PASS。提交 `96bf1d3dc60d4b81ab0ee59bb5072cdbdcbcbce7`，证据 artifacts/p03/h2/fixes-j6/。
