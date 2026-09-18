# Mac Tushare 研究子集首次生成超时修复开始

- 云端 2026-09-18 23:47 CST 首次请求新本地发布 `data-96ef14e1…`，本地研究子集准备超过客户端 600 秒读取响应窗口；云端该轮 TimeoutError，本地继续完成子集 `data-afff6006…`。
- 23:59 CST 重试成功，160 秒内验证并下载 14508 个新增文件；缓存 3317837768 bytes，upstream_calls=0，timer active、service inactive。
- 候选仅延长 loopback `/CURRENT.json` 的首次准备等待窗口并增加精确测试；不改单文件传输超时、公开监听、缓存预算、API 范围或供应商调用逻辑。分支 `codex/tushare-research-cache-timeout-20260919`。
