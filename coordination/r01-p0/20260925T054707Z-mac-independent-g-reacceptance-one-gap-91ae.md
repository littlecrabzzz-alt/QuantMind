# R01-P0 G 轮独立复验结束：剩一项公共产物适配

候选 e98feb70 clean，源代码、输入、交接原件未改。66项单测、27项真实HTTP、8项页面输入/重启API通过；正常页面实测预览下载、真实曲线、适配后持仓订单净值、分组/拒绝标签通过。F-AC06、F-UI02关闭，AC-01～05保留。

唯一剩余 G-UI01-ADAPTER：AB-QUICKSTART 的 ledger.export_evidence() 输出 equity+orders，页面仅接受 days 等别名；原生文件实测报“证据文件缺少逐日记录（days）”，演示脚本内转换后才正常。需公共适配入口并同步Quickstart，不重做已通过部分、不交给A/B各自补接口。独立结论 failed，研究暂未放行。

报告：/Users/lizeyu/Documents/ChatGPT/投资/投资学习与研究/课题/R01-P0-G轮独立复验报告-2026-09-25.md
证据：/Users/lizeyu/Documents/ChatGPT/投资/投资学习与研究/验收/R01-P0-G-2026-09-25/

原本地sidecar恢复、原节点确认，临时PG/容器/网络/Vite/凭据已清理；实际下载的非敏感JSON移入证据目录。未改共享研究库、未合并或云端发布、未运行研究/虚拟盘/实盘。学习入口已同步。
