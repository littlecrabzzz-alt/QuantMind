# Mac上游连通性与文档运行环境验收
- 首次Mac只读trade_cal探测在HTTP客户端构造阶段ImportError，未发请求。确认macOS系统代理含SOCKS，而runtime缺socksio；没有绕过代理设置。
- masterecb2769b已推送，native installer安装httpx[socks]==0.28.1并构造Client做健康检查。已安装socksio1.0.0，未启动采集。
- 用原私有Token重试两日trade_cal：2026-09-17 01:21:33 CST HTTP200/code0/rows2，耗时0.209秒。只做连通性探测，无整库采集或冻结状态改写；Token未输出。状态在Mac Application Support/QuantMind/tushare-local-connectivity-20260917.json。
- 8项迁移/安装/worker/authority测试通过。PDF测试需要reportlab仅用于生成fixture，未安装到生产runtime；在uv隔离环境中18项文档解析/队列/恢复测试通过（pypdf同为6.17.0）。
- Mac暂存documents.sqlite2204909568字节已单独哈希比对源冻结清单通过；加上archive/daily-quota共3个已验证。pipeline.sqlite仍在传输。
- 云checkpoint原PID253095持续active，inventory已114.3MB（观察值），无COMPLETE；附件precopy和checkpoint-prestage原任务继续。尚未finalize或启动Mac采集，源Tushare仍暂停，QuantDB不变。
