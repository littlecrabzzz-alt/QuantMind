# Tushare 精确批次继续结果

- 时间/节点：2026-09-10T15:53Z，Mac 主集成人；生产代码仍为 `4b359b29076ff6336cd5b5d52eb26268217794f9`。
- 财务第八批：360次、47.626秒；三API各116 done/4 empty。manifest SHA `2b485d6b92ea4ad198a8d466640dd00676a52365929eedbbf15859e91dfc54c5`，receipt SHA `702572f42c48783721c57834770178d0c0c9a60096f4e84f98708dc1648f5a81`。
- `fund_nav` 第三批：270拆分叶+90历史根、225只基金；360次、49.602秒，202 done/39 empty/119 split_pending。manifest SHA `add2f3cf9c145628fea2e861d908d8940cc1914a32f51244645ec187bb7d91c7`，receipt SHA `6826ccd3616cdbaa4c900770dd22fd8e7f48629db36ea2dc5861e2655426ebf9`。
- 两批均为重新冻结的新清单，通过plan-only和生产哈希/authority/锁/容量校验；不发布、不切CURRENT。worker/Beat已恢复healthy，文档worker保持停用。
- 当前固定版仍为 `data-1ed568…`；本轮以及上一波四个精确批次共1440项等待2026-09-11 00:26:31到期发布。批次后可用147769589760字节。
