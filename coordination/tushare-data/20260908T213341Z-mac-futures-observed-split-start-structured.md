# 期货父观测分片候选
- Mac/codex/tushare-futures-partitions；直接基于父e7eedbf；信用/索引候选保留各原分支。
- 归属仅pipeline.split_request及直接helper、新专项test；不改其它方法/合同/配额/生产。
- fut_holding按真实exchange+symbol；fut_weekly_detail先opaque week原值、再exchange+prd。无文档全集证明；缺字段/非法值/父过滤不符/无剩余分片维度分别保留证据gap；仅新增observed children。
- 隔离离线验证，不修改原文/attempt，不猜ISO/补零/offset。
