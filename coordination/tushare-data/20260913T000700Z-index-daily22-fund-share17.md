# Tushare index_daily batch 22 and fund_share batch 17

同一受控窗口完成两个成熟exact批次。Beat先停止，普通Tushare worker完成已开始任务后自然退出0；主服务、文档worker和QuantDB持续运行。闭包完成后worker和Beat恢复healthy，五个服务restart0、OOM false。

`index_daily`第22批固定960e版本，冻结360个pristine history任务，全部为CSI指数，范围20240101至20260901。45.498秒完成360次请求，343 done/17 empty、82299行，474.746rpm。与前21个唯一manifest的7260任务在task、logical、canonical API/params和full job四层重叠均0，CFX/SI/SW均0。1063个引用/17447229字节逐SHA复核通过；960e负对照缺全部1063项。

`fund_share`第17批冻结360个pristine history任务，沪深各180，日期20180908至20190306。44.415秒完成360次请求，234 done/126 empty、55354行，486.322rpm。与前16个唯一manifest的5640任务四层重叠均0。954个引用/5662402字节逐SHA复核通过；960e负对照缺全部954项。

`fund_share`第一次闭包复用了index任务投影，因manifest不含state/tries字段而安全拒绝。它只复制了固定输入，未生成物理inventory或closure，保留在`validation/fund-share-batch-20260913/batch-17`。修正后接受的create-only归档是`batch-17-v2`。历史扫描同时发现失败目录里的同一manifest副本，按内容SHA去重后准确比较16个先前唯一manifest；失败与去重记录均收入接受归档。

机器证据：`docs/tushare-index-daily22-20260913.evidence.json`和`docs/tushare-fund-share-batch17-20260913.evidence.json`。两个批次都未发布或切换CURRENT；与top10第2、3批一起等待正常publisher、云端精确校验、Mac标准镜像、本地精确校验及禁网读取。完整历史、修订、空响应完整性和known_at/PIT继续开放。
