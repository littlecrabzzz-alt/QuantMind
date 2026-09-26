# 币安数据接入：开始
- 节点：Mac sandbox；基线 e23b6712；双端 handoff passed。
- 授权：用户要求完成历史补采、UTC/字段规范、质量与增量更新、研究入口贯通；核实币安股票相关产品。实盘保持关闭，不启动策略研究。
- 工作区：/Users/lizeyu/.codex/worktrees/quantmind-binance-data-20260926；分支 codex/binance-data-20260926。
- 分工：root 负责 blockchain_sync.py 的数据校验/发布、独立验收和部署；data_fetch 子任务负责 crypto_data.py；research_wiring 负责 crypto Qlib/RD 入口与日历；products 子任务仅核实官方产品范围。
- 复用：现有 QuantBC parquet、QlibDataBuilder、RD loop、市场同步入口。先完成 BTCUSDT/ETHUSDT 现货日线；股票现货/代币化股票/股票永续按官方证据分别标识，不混用 CN/US 股票数据。
- 写入：独立输出与测试容器先验收，之后仅新增币安数据集；不覆盖现有研究输入、A股基础数据或业务库。共享服务发布需协调空闲窗口。
