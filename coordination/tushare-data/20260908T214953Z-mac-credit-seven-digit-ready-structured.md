# 信用7位供应商基金标识修复交接
- Mac/codex/tushare-credit-source-codes；基于父40bea6a；候选4e414e4e48754d7b6016a2cdc2a6c044c7f4a234。
- 归属释放：仅信用合同及2个信用test；不改公共_stock/normalize/store/pipeline/生产。

信用funds读取复用market._codes供应商记录规范，并限制信用交换所/6或7位基金；observed credit集合不再交给仅股票语义的_stock，独立接受6/7位及既有T6位源身份。基金与observed两路OF均不进入outbound，输入原文不删改。6/7位永不截断/别名化；股票发现仍拒绝7位，非法长度/市场/控制字符仍拒绝。

normalize/store检查：七位ts_code当前保持原供应商值（如1500011.SZ），source_ts_code同值；六位150001.SZ为SZ150001。两者原文、Parquet、固定release自然键和查询均不碰撞；未统一映射为前缀。为此每个涉及信用证券的API记录opaque_fund_identity_unverified gap（coverage_unverified），明确内部canonical映射与交易/信用资格未认证；不阻止原始采集。

验证22通过：8纯合同+7信用集成+7observed fanout。使用父提供全部21个七位基金（3OF/18场内）验证原值、重入、未知资格gap；Mock临时链路验证planning:credit_extra从validation_blocked恢复、七位证券新增/重复分片、OF主表保留、6/7位固定release分别读取及原始数值。Ruff/diff通过。无真实请求/部署/配置修改，父负责集成后新周期规划验收。
