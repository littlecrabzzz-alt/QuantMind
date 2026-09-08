# 信用基金7位原始标识兼容
- Mac/codex/tushare-credit-source-codes，基于父40bea6a。
- 归属：信用合同及专项tests；不改公共_stock/normalize/store/生产。
- funds及observed credit重入均兼容原值7位基金，6/7位不归并；OF不进信用outbound、原始输入与存储保留。遵循已有market原始代码读取规范，信用交换所范围单独限制。
- 内部normalize当前7位保留原始ts_code和source_ts_code，无截断；测试固定release不混淆6/7位，并记录canonical身份未验证gap，不等同交易资格。
