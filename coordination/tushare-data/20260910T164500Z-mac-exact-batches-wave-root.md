# Tushare 下一组精确批次开始

- 时间/节点/任务：2026-09-10T16:45Z，Mac 主集成人，exact-batches-wave-root。
- 状态：本轮已完成，等待正常固定版发布与Mac镜像。
- 基线：`master`/GitHub/云端 `dd8c555b516b32816130970b244ad25c875e2753`；固定版和Mac镜像均为 `data-d5d918ce4bc2cfd3ef6e58c5caeefa29c7d9f9715cd5b8cd0d03d4d07cab64de`。
- 分工：主集成人只负责下一组财务三表、`fund_nav`、`fund_share` 精确批次与当前固定覆盖证据；三个只读并行审计不访问生产SQLite或凭据。保留主树现有RRG/研究文件。

当前固定版离线审计为243/243运行时接口已规划、193个有发布数据集、50个只有empty/blocked/permission证据。249项冻结命名范围中243项运行时可读；`ggt_monthly`是唯一公共只读合同阻塞项，另外2私有读、2写操作和1 SDK包装不进入公共自动采集。下一步等待当前`tushare_acquire`自然结束，暂停Beat和worker后重新冻结各批，逐项plan-only和哈希验证；低于100GiB或任务漂移即停止该批，不阻塞其他批。

结果：停写窗口内依次执行财务三表第9批、`fund_nav`第4批、`fund_share`第3批，三批均从权威库重新冻结，起始共1,080项 `pending/attempts=0`，plan-only和固定哈希通过。实际1,080次上游调用分别用48.788、49.170、46.786秒完成；结果为财务344 `done`/16 `empty`，净值179 `done`/41 `empty`/140 `split_pending`，份额270 `done`/90 `empty`。三份不可覆盖回执均已安装，执行器未发布或切换 `CURRENT`。常驻worker和Beat随后恢复healthy，云盘可用146,862,358,528字节，高于100GiB停线；文档worker继续停用。

固定版覆盖审计固化于 `docs/tushare-fixed-coverage-20260911.evidence.json`。新增批次等待正常一小时发布周期；发布后再由标准Mac镜像和断网reader验收，不能把当前权威终态提前表述为本地固定版已有数据。
