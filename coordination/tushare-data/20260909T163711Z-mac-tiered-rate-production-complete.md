# Tushare权限分层限速：500档生产验收完成

- 时间、节点、任务标识：2026-09-09T16:37:11Z，Mac集成/云端authority执行，tiered-rate-production。
- 状态：本分层限速子目标完成；Tushare全量历史、修订、附件、PIT及RRG缺口继续。
- 分支、提交：`master`/`codex/tushare-rate-integration`均已push，运行时代码`aad9310`；本记录与进度文档另行提交。
- 接续：分类证据`20260909T155459Z-mac-rate-refinement-ready-text.md`，运行候选`20260909T155637Z-mac-tiered-rate-policy-ready-structured.md`。

完成：227接口证据细分为147常规、3特色、5不确定及原有已购/独立/单页类别；静态allowlist与证据逐项测试。部署时只暂停`tushare_acquire`接新任务并等待在途任务自然排空，文档/研究/US任务保留；先重启quantmind加载新代码，300档写配置后再重启采集worker，随后用不可覆盖验收SHA逐级升400/500。最终配置SHA`2600c2b5f3446bd1b9fba8a839c494a23a65091ca283483f065166f38356d72c`，500档保留，服务healthy、无OOM/意外重启。

验证：专项35、全Tushare 777测试、Ruff通过。300档三样本207次、400档两样本133次、500档两样本100次，全部HTTP200；连续请求中位约300/387/495.9 rpm，0个确认供应商限频事件。验收SHA：300=`5e80adeb9e4fce6c1ac9768a589d6315c3d1f4c41e51db82e7a411108236909d`，400=`221d88aec8c0a4f97dbcc6eab6abfba2f7ef7f16b43d4f87533a95087f133c26`，500=`dcc7abb4414a7e119ff84799df55b4fbc7e726285921f5b02754e4e1f04f14d9`。Mac安装副本的policy/quota/mirror文件与源码SHA相等；两次SSH瞬断后固定`data-703b5dc1…`394321文件完成校验、0文件需补传，安全重试未覆盖旧完整版本。

边界：10100及分笔到期为用户声明，不是供应商实时授权回执；2026-12-05按北京时间00:00保守降8100并触发特色复核，当前90天提醒已可见。`cyq_perf`部署日guard及以后本地日账本仅覆盖当前root；`factor_value`不假定500。每批仍在约78–81秒规划/标识符解码及已有API冷却后触发160秒软超时，需作为独立性能工作继续；不影响本次分钟门控与无429结论。
