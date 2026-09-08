# 信用7 runtime 候选交接
- Mac/codex/tushare-structured；基线已合父 d83c402；候选 2a4bbb1d444e9141ec8eeff970c8742a65e40dee。
- 归属释放：registry、pipeline identifiers/extra gaps/plan 配置签名、store合同映射、mirror copy名单1行、新 scripts/test_tushare_credit_pipeline.py。未改tick/records/normalize/_dataset/install_schedule其他内容/ledger/文档；未部署/生产调用。
- 已与 remaining_markets 协调 mirror copy 名单边界。

接入 margin/margin_detail/margin_secs/slb_len/block_trade/pledge_detail/pledge_stat，family=credit_extra。开关 enable_credit_extra；credit_extra_apis 可选7名单；credit_extra_history_start 可日期或API字典，也可沿用 history_start。未知最早日期、发现全集、旧公告修订、内容完全相同事件次数、不可合法再拆 pledge_stat 均保留合同gap。

发现并集使用已有 stocks/funds 加 margin_secs 原文历史观察；ETF包含、场外.OF不进入证券请求、历史T身份保留。没有把 margin_detail/block_trade 全历史加入反复 identifiers 扫描；其饱和父响应已见 codes 仍沿用 split_request observed union。该发现机制仍会重读 margin_secs 旧对象，性能需结合阶段计时后续评估，本候选不改扫描架构。

验证：6新集成+7信用纯合同+3extra+17pipeline+7observed fanout=40通过。全7字段/未知字段/单位数值保真、T/ETF、未来质押期限与公告轴区分、不同状态事件 _row_identity、合法日期二分、未证明全集保留、无offset猜测、planner去重/配置签名、坏发现仅阻信用、旧观察发现不丢、固定release零上游读取。Ruff/diff通过；AST确认被保护函数完全未改。仅临时fixtures/MockTransport且socket/secret拒绝。

下一步：父集成后决定正式开关与最小权限样本；候选不代表7接口真实权限/历史完整或RRG准入已验。
