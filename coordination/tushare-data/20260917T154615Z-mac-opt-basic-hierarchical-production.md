# Tushare 期权目录三级拆分生产验收

- 时间：2026-09-17T15:46:15Z
- 代码：6839e18b2afc690c760541bbbc10ed7c03e2945d，已在 master、origin/master 和云端 master 对齐
- 数据权威：Mac ~/Library/Application Support/QuantMind/tushare
- 运行时：Mac ~/Library/Application Support/QuantMind/tushare-client
- 官方合同：https://tushare.pro/document/2?doc_id=158

## 问题与真实数据依据

生产队列有 50 个 opt_basic 历史父任务处于 possibly_truncated：7 个无过滤父任务和 43 个交易所父任务。保留响应覆盖 20260909、20260910、20260911、20260912、20260913、20260914、20260917，单响应 8034 至 12000 行。

只读审计全部 50 个原始对象后，实际交易所为 CFFEX、CZCE、DCE、GFEX、INE、SHFE、SSE、SZSE；旧配置漏了 INE。call_put 仅观察到 C/P，所有 opt_code 均为非空、无首尾空白、无控制字符且不超过 128 字符。官方 opt_basic 文档明确公开 exchange、list_date、opt_code、call_put 四个过滤参数，但不公布闭合的交易所或标准合约全集。

## 实现与边界

- opt_basic 饱和响应依次按 exchange、call_put、opt_code 拆分。
- 第一层使用文档交易所与父响应实际交易所的并集；补入生产已观察的 INE。
- 第二层使用 C/P 与父响应值的并集；第三层只使用该父响应观察到的标准合约代码。
- 每层继续保留 coverage_proven=0、universe_complete=false；观察值不冒充供应商闭合全集。
- 旧 blocked 父任务复用原始对象恢复，恢复本身上游调用为 0，不改写原始 attempt、tries 或对象引用。
- 既有单轴 index_basic、opt_daily 行为保持兼容；无合同声明的接口不会获得该拆分。
- 快车道在原六接口后加入 opt_basic，throughput_fast_lane_every 保持 2，全局公平队列隔轮继续。
- 私有回执 fast-lane-config-v5.json 不含凭据；旧配置 SHA-256 为 5e8d590c33db39c82ed4e09c1c9d529ea6c703abec68287c8df62eb1a216cf46，新配置为 4913c30f6a7e1dfae9928d30c3b2ce2c8b19108efd02b0a58d8a56f49a2a384a，回执为 808a26875abcb054ff0ba47bdc37bafb3c63de9a924bf57093055eee117cdfb5。

只读生产模拟显示，50 个旧父任务第一步只产生 142 条父子关系；保留响应推导的最细 opt_code 叶任务下界为 8214，属于有界千级任务，不是按全部期权代码对每个父任务做百万级扇出。

## 测试

109 项相关离线测试通过，覆盖 other 合同和读写、三层饱和拆分、旧 blocked 父任务零请求恢复、index_basic 单轴兼容、延迟拆分、观察值扇出、分区闭包、合同重评、董秘问答、分层限速和队列索引。Ruff、py_compile、git diff --check 通过；50 个真实保留响应的只读模拟无非法分区值。

## 生产部署与真实验收

- 等待原 PID 77474 自然完成 publish_only 周期后，在完成状态落盘的边界卸载；没有中断在途采集。只更新并重启 com.quantmind.tushare-archive，QuantDB、云端应用和云端研究缓存未停止。
- 新 worker PID 88122，LaunchAgent 为 running、last exit never。仓库与运行时 tushare_pipeline.py SHA-256 同为 d25024e269b17d7b7f2b8a2dc24bb3b78cd221a60af3d394393fcee2da1e4515；tushare_other_contracts.py 同为 b1aa288a55de3b349e4ded265cbce6d13a8e5dc521632415610e0e5d8596a5bf。
- 配置变化先完成一次 planning_only：86.877 秒、0 上游请求、failed_stage=null、并行文档处理 240 个，随后 5 秒恢复采集。
- 首两个完整真实周期分别完成 324 和 353 次请求，均为 failed_stage=null；每周期文档处理 240 个。
- 第一个周期用 0 上游调用恢复最旧无过滤父任务，观察到全部 8 个交易所并建立 8 个子任务。第二个周期用 0 上游调用恢复 SSE 父任务并建立 C/P 两个子任务。
- 真实 INE 交易所请求返回 6082 行，拆成 C/P；两个 C/P 请求各返回 3041 行、sample_ok、supplier_has_more=false。
- 真实 GFEX C/P 请求分别返回 7764 和 7763 行，继续按 opt_code 各拆出 137 个子任务；已完成的 opt_code 叶请求均 sample_ok、supplier_has_more=false，验收时最大 2520 行。
- 验收窗口 opt_basic 状态仅出现 sample_ok、empty_unverified、possibly_truncated；没有 rate_limited、transport_error、api_error、permission_denied、invalid_response、schema_gap 或 invalid_values，也没有 quota:opt_basic。
- 生产验收快照为 blocked=47、done=73、empty=2216、quality=1、split_pending=10、pending=11444。blocked 正随每周期旧父恢复下降；pending 会因合法叶任务展开先增长，不能据此误判倒退。
- 本地仍有约 2.3 TiB 可用，未触发 500 GiB NAS 提醒或 300 GiB 停写线。

## 双节点结果

双端 handoff 通过：head 6839e18b，源文件数 6756，内容摘要 ab8c22b199ea55eb2fb9c131de0e68a223a893aadb2edb2a12c9716f6a0c1045。云端 dual_node_check 通过，tushare-research-cache.timer active/enabled，未发现云端完整 Tushare writer。

完整本地同步仍在继续。本次关闭的是 opt_basic 已知饱和目录的可执行拆分路径；供应商未公开的更早历史、闭合场所全集、已删除标准合约和首次可知时间继续保留为来源限制，不宣称 PIT 完整。
