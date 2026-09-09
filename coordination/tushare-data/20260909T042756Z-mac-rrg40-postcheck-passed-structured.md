# RRG40实际提升后置只读核查

- structured/Mac，完成；既有cloud-compose quantmind python3 -S业务入口，仅stdlib/SQLite URI mode=ro + query_only +有限主键/attempt查询，未调Tushare、发布、写权威DB/配置或等待40全部执行。
- 操作 `rrg-diffusion40-20260909-b0b0f1b914894a928565212be8f0fd28`：云端prepared原字节SHA `71bcb2332d83eff05b8841d74274d7766ac47913e2f43f8c52d19d230f759a7c`一致；committed云收据与本地 `/tmp/tushare-rrg40-priority-applied3.json` 最后一行完整相同。40个prepared before/after仅priority45→24，其余列逐项相同，0插入/跳过，提交时config/checkpoint SHA不变。
- 04:27:42Z一致读事务中40个精确job均存在；id/rowid/logical_key/epoch/full job/group不变且priority24。当前40 pending、tries0、0 durable attempts，非空0/空0/失败0；这表示尚未消费，不是数据完成或权限失败。后续正常state/tries/result/retry/expanded变化会单独列出，不误当身份变动。
- 事后config SHA `97208d43373a853b9b1b9b459ef6d98b7ebeacb98d55ffd5bc65b06ae4c95b2b` 与提交时 `c6e25d8d5cd2f070ef18e4c5c2df85669a4b54006eba33a38a3f478d86969627` 不同；现已enable_cross_asset_extra/enable_market_sentiment，root明确另有授权enable操作。group_weights与prepared完全相同；planning/scheduler亦已推进。这里记录时序差异，不将后续配置或正常游标推进归因于40优先级事务。
- 报告 `/tmp/tushare-rrg40-postcheck.json` SHA `1f86337ca2b022cd8202a6be403e00412fcbf7a9a04d7396650906a7849bf9eb`，helper `/tmp/tushare-rrg40-postcheck.py` SHA `6499ec8578c86823a0daf3504ce9044b412eba4772a5ae860267afbb197a6282`。查询/校验0.041秒。准备文件实测3,224,343字节（含旧planning快照），首次2MB保守读界拒绝发生于DB打开前；只读stat确认后将本helper限额设5MB再验，没有改变任何生产文件。
- 本轮仅确认实际变更收据与当前队列身份；不验证未来原文/Parquet/固定release/Mac闭包，PIT与完整日历骨架仍按前述缺口保留。root继续正常采集，归属释放。
