# 旧 Connect 有界参数复核开始

- 时间、节点、任务标识：2026-09-10 04:36Z，Mac，legacy-connect-probe。
- 状态：进行中；基线`01265aa70bdc67e0e434304a06a441405a21a848`。
- 分工：父线程仅新增`scripts/tushare_legacy_connect_probe.py`及对应测试；目录外接口审计、RRG任务准备、附件提速由三个独立agent继续。
- 目标：复用生产锁、共享账户/API门控和不可变原文路径，最多执行4个预先审定请求，验证`moneyflow_hsgt`范围参数、`ggt_daily`日期/范围参数与`ggt_top10`精确日期；默认只生成计划，不读取Token、不连上游、不改配置或启用范围。
- 边界：旧空参响应仅是历史证据；失败、空、饱和和字段变化都原样记录，不猜月度接口别名，不从`ggt_daily`派生`ggt_monthly`，不把成功样本等同完整历史。
