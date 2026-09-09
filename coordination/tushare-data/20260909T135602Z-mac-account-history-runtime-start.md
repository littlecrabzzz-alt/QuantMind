# 开户历史2接口runtime开始

text_contracts / Mac / codex/tushare-account-history-runtime，基线745e0a6。拥有registry/store/mirror、新专项及doc，pipeline仅imports/normalize/plan_extended，不碰identifiers()/records()（structured诊断）。复用pure跨年周期投影，raw date不改、本地默认区间相交/显式端点，未知周期保留gap不丢；实际account_history_history_start签名与生成结果测试。默认关闭，无近期轮询/无源HTTP/无生产。
