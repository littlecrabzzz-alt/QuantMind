# Tushare 第二次精确波次

- 云端authority停写窗口内串行执行财务第12批、指数权重第4批、基金份额第7批和基金净值第8批，合计1440次请求、179.841秒，返回480735行。
- 四批均通过manifest、任务集、生产配置和工具哈希门控，未发布且未切换`CURRENT.json`。合并验收重算1440个任务及4148个唯一物理引用，0错误；权威摘要SHA256为`e88c8f8638bcc22d1f8d5495c7bea98c7ebef89895efce94ea1db9f53ae4203a`。
- 恢复后DB、API、`tushare-worker`和Beat均healthy，restart0、OOM false。两个停写期间超过110秒有效期的旧Celery消息按过期语义丢弃；04:19:57的新周期任务`aee5532f…`已接收，未丢失逻辑请求。
- 机器证据为`docs/tushare-exact-wave-20260911T0406.evidence.json`。本次结果等正常固定版周期发布和Mac自动镜像；历史、修订/PIT及RRG数据准入仍保持未完成状态。
