# 股票开发边界事件止血

2026-09-27 小时独立复核发现冻结 loading.py 在 test_end=2026-03-24 后仍加7日读取；baseline execution.log 证实实际读取至03-31，test标签未与train/valid同样purge。fit及GLM实际暴露范围继续只读界定，不读取新增保留行情。

本组在 codex/glm-continuous-research 增加最小认证运维暂停入口与测试，范围 scripts/continuous_research/hold_stock_scope.py、tests/continuous_research/test_stock_scope_hold.py、深度研究交接说明。保留原合同/报告/结果，停止本课题股票计算并阻止新提交；ETF及只读复核继续，A不动。不修换冻结数据包或继续回测直至边界负例验收。
