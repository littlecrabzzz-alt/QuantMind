# fut_rcpt_mat ts_code 字段补采验收

接续 20260919T040600Z-mac-futures-product-code.md；代码 4f06e209 已部署。原定 442 个日期分区全部返回：294 empty、148 quality，共 1500 条源记录，1500 条均有 ts_code。逐一校验全部 442 份 observation 和 442 个原始对象的 SHA-256，全部匹配。详见 docs/tushare-futures-product-code-production-20260919.json 的 backfill_acceptance。

quality 原因仍是供应商缺少文档表格中的 fut_code；未合成该列、未降级缺口判断。空响应仍为 empty_unverified，完成这批请求不证明官方全部历史完整。旧 job/attempt/对象和全局规划游标保留。本地原生全量采集仍运行，未触碰业务后端。
