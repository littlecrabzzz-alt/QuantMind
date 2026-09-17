# Tushare 指数目录饱和拆分生产验收

- 时间：2026-09-17T15:21:09Z
- 代码：`d48ff7be07881c190a3264e683fdb57968576385`（`master`、`origin/master`、云端 Git 已对齐）
- 数据权威：Mac `~/Library/Application Support/QuantMind/tushare`
- 运行时：Mac `~/Library/Application Support/QuantMind/tushare-client`

## 问题与合同依据

生产库保留了 8 个 `index_basic(market=CSI)` 历史父任务。每个任务均返回 8000 行并被标记为 `possibly_truncated`。Tushare 官方 `index_basic` 文档（`https://tushare.pro/document/2?doc_id=94`）明确说明单次返回 8000 行，并公开 `publisher`、`category`、`symbol`、`ts_code` 等过滤参数。

实现先从父任务已保存的原始响应读取真实 `publisher` 值，再生成 `market + publisher` 子任务。供应商没有公布闭合的发布商枚举，因此拆分始终保留 `coverage_proven=0`、`universe_complete=false`，不会把观察到的发布商集合当成完整历史全集。发布商子任务若仍触顶，现有合法 `ts_code` 扇出继续作为后备路径。

## 实现与保护

- 支持受控的供应商文本分区值；拒绝空值、首尾空白、控制字符和超过 128 字符的值。原有大写代码分区校验保持不变。
- 只有合同显式标记的 `index_basic` 旧阻塞任务可以走恢复；每个父任务复用原始对象，恢复阶段上游调用为 0，不改写原始 attempt、tries 或文件引用。
- 本地观察值拆分不再浪费本轮剩余采集预算；昂贵的全库身份扫描仍保留原有独立边界。
- 生产快车道加入 `index_basic`，`throughput_fast_lane_every=2` 不变，隔轮继续服务全局公平队列。
- 私有回执 `fast-lane-config-v4.json` 的 SHA-256 为 `adc5836a80eb790cc1e4aa486317c545ab2990eef3a26e60a405868e750dc03f`，包含回滚到原五接口列表的非敏感配置，不含 Token。

## 测试

- 114 项相关离线测试通过，覆盖当前修复、延迟拆分、旧阻塞恢复、观察值扇出、分区闭包、合同重评、董秘问答精确批次、限速和队列索引。
- Ruff、`py_compile` 和 `git diff --check` 通过。
- 新测试证明中文发布商值按原值保留、恢复阶段不访问上游，并在本地拆分后继续使用同轮采集预算。

## 生产部署与真实验收

- 两次运行时升级均等待 Mac worker 自然完成当前周期后进行，只卸载并重装 `com.quantmind.tushare-archive`；QuantDB、云端应用和云端研究缓存未停止。
- 仓库与已安装 `tushare_pipeline.py` SHA-256 均为 `4cc74e4c048603297d665d25702cc76d659981cb6348e3323b28620c3d23d0fc`；`tushare_structured_contracts.py` 均为 `8ac0342ea7c0743d980ab8d6d155dc56cb0a53fa16abed91a58671bcc82e284a`。
- 配置变化触发一次生产队列重算：90.25 秒、0 次上游调用、`failed_stage=null`。这是队列扩展周期，不是演练；随后按 5 秒快速恢复采集。
- 8 个旧父任务均以 0 上游调用完成恢复。不同父响应观察到 9 或 10 个发布商；跨父任务去重后生成 64 个发布商子任务。
- 64 个子任务全部真实调用完成，全部为 `sample_ok`、`supplier_has_more=false`；最大返回 7525 行，未再次触达 8000 行上限。
- 修复后的连续生产周期完成 337、297、312、290、271 次真实请求，均为 `failed_stage=null`。`index_basic` 没有 429、权限错误、传输错误或 `quota:index_basic` 记录。
- 最终 `index_basic` 状态为 `done=88`、`empty=25`、`split_pending=8`、`pending=0`、`blocked=0`。8 个父任务继续以 `split_pending + universe_unverified` 保留来源级全集缺口。
- 最近完成的全局周期为 `done=207584`、`empty=190805`、`pending=2757293`、`blocked=1289`；队列会随规划和拆分增长，不能用 pending 单项变化推断采集倒退。
- 磁盘仍有约 2.30 TiB 可用，未触发 500 GiB NAS 提醒或 300 GiB 停写线。

## 双节点结果

- `bash scripts/dual-node.sh handoff --align-git mac` 通过；两端文件数 6754、内容摘要 `b637d95f65080f66af1d2a6f872e16eee5406836ff9f024ab01295a5f09eff00`。
- 云端 `dual_node_check.py --node cloud` 通过，Git 为同一提交。云端仅 `tushare-research-cache.timer` 为 active/enabled，没有云端完整 Tushare writer。

完整本地同步仍在继续。该验收关闭了可执行的 CSI 8000 行截断路径，但发布商历史全集、已删除指数、旧修订和首次可知时间仍受供应商来源限制，继续作为显式数据缺口保留。
