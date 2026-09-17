# Tushare 沪市董秘问答终端饱和拆分生产验收

- 时间：2026-09-17T14:53:56Z
- 代码：`a7000e7e59d8d0941bcd37e3cfa3b78bd266c191`（`master`、`origin/master`、云端 Git 已对齐）
- 数据权威：Mac `~/Library/Application Support/QuantMind/tushare`
- 运行时：Mac `~/Library/Application Support/QuantMind/tushare-client`

## 问题与合同依据

生产库保留了 21 个 `irm_qa_sh` 历史父任务。每个任务的 `pub_start=pub_end` 已经细分到一秒，但供应商仍返回整 3000 行并明确给出 `has_more=true`。抽查显示每个父响应中的 `pub_time` 都精确匹配请求秒，且单秒涉及约 672 至 822 个股票代码，因此这些是实际截断义务，不是本地阈值误报。

Tushare 官方 `irm_qa_sh` 文档（`https://tushare.pro/document/2?doc_id=366`）说明单次最多 3000 行，并明确允许按 `ts_code`、日期等参数循环提取。生产合同据此为沪深董秘问答增加 `ts_code` 股票扇出；供应商没有独立的历史股票全集或总数，拆分证据继续标记 `universe_complete=false`。

## 实现与保护

- 新捕获在时间窗口达到上限后先持久化原始对象、观察记录和 Parquet，再把父任务标记为延迟拆分；不会在同一请求中重复调用父窗口。
- 旧的 21 个阻塞父任务复用已落盘响应，零上游调用生成按股票子任务，并保留原始 attempt、tries 和文件引用。
- 仅合同显式标记的 `irm_qa_sh`、`irm_qa_sz` 可以走旧阻塞恢复；已由区间迁移替代的 `dc_member`、`moneyflow_dc` 等任务不会被重新激活。
- 子任务使用本地保留股票身份与父响应实际观察代码的并集。观察到但不在当前股票主表中的代码继续保留。
- 父拆分始终保持 `coverage_proven=0`；没有供应商全集证明时不会进入完整状态。

## 测试

- 99 项相关离线测试通过，覆盖延迟拆分、旧阻塞恢复、排除未审查旧任务、文本合同、观察值扇出、分区闭包、合同重评、董秘问答精确批次、限速和队列索引。
- Ruff、`py_compile` 和 `git diff --check` 通过。
- `scripts/test_tushare_extended_pipeline.py` 的日期推进断言在修改前的 `master` 和本分支均为同一结果（7 通过、1 个旧失败），不是本次回归。

## 生产部署与真实验收

- 在自然完成周期边界卸载并重装唯一 Mac 归档 worker；QuantDB、云端应用和云端研究缓存未停止。
- 仓库与已安装 `tushare_pipeline.py` SHA-256 均为 `9c39043f535863cb1511734d446d391a4261095042f9956191b65fee10c65d90`。
- 部署后的前三个真实周期分别恢复父任务并生成 5914、5915、5915 个子任务；请求数为 314、224、300，`failed_stage=null`。
- 灰度快车道随后加入 `irm_qa_sh`，仍按 `throughput_fast_lane_every=2` 运行，一半调度机会继续服务全局公平队列。配置 SHA-256 从 `aaf4f630c10b3f0a8df6741620414dab0f8b38045e822926739a8793662c23c8` 变为 `c478606e534538db58ebb918f1af926c017b9c305b2d09d83e473b2348b7ba2d`。
- 私有回执：`fast-lane-config-v3.json`，SHA-256 `cc810b7a42ae638e2dbb205912b434ba2ed2c4a9cdad38c09d699c6b05224743`，包含回滚到原四接口列表所需的非敏感配置；未包含 Token。
- 配置变化触发一次真实生产队列重算：21.339 秒、0 次上游调用、`failed_stage=null`，随后按 5 秒快速恢复采集。
- 两个灰度采集周期分别完成 316 和 270 次真实请求，均为 `failed_stage=null`。`irm_qa_sh` 子任务终态数从 47 增至 80，均为供应商空结果；没有 429，也没有产生 `quota:irm_qa_sh` 限流能力记录。
- 截至第二个灰度周期，21 个旧父任务已恢复 6 个，剩余 15 个；最近一次状态为 `done=206178`、`empty=189339`、`pending=2719939`、`blocked=1302`、`split_pending=5625`。

## 双节点结果

- `bash scripts/dual-node.sh handoff --align-git mac` 通过；两端文件数 6752、内容摘要 `d8099d5e85509c2a6b4d97eb6e2a8a2a666a59aa9713205d96e29fb451727c05`，无 Syncthing 漂移。
- 云端 `dual_node_check.py --node cloud` 通过，Git 为同一提交。云端只有 `tushare-research-cache.timer` 处于 active/enabled，用于从 Mac 拉研究子集；没有云端完整 Tushare writer。

完整同步仍在运行。当前拆分提高实际覆盖并关闭可执行的截断路径，但不会消除历史股票全集、旧修订、删除记录和首次可知时间的来源级不确定性。
