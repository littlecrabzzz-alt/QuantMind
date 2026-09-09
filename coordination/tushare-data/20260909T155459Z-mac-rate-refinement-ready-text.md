# 常规155候选分类增量完成
- 分支codex/tushare-factor-month-planning，候选1b1928c已push，仅新增精确集合/离线脚本/专项测试并追加原审计文档，未改runtime。
- 原155严格分为147 regular_500、3 special_300(stk_ah_comparison/stk_nineturn/stk_surv)、5 uncertain(hk_basic/hk_tradecal/us_basic/us_tradecal/hm_detail)。其余72API原分类完全保留，factor_value仍官方频次unknown。
- 精确allowlist为docs/tushare-general-rate-refinement.json api_sets.regular_500；不能用227反向排除生成。源290当前HTML SHA18e4557232524672da08f47d89eef2a384919103de24680c37021e9641000d80，正文链接291与侧栏祖先层级逐项匹配，各叶子HTML与原492c报告SHA严格一致。
- 147的积分档条件在声明的8100余额仍满足5000档；20261205无需仅因失去10000档降其常规500，但必须保留live权限/account/API限额及冷却。3特色在20261205必须review，不因其低积分可访问就推定特色频次继续。港美股4总述/叶子范围张力及hm_detail10000访问门槛保留歧义。
- 新6+旧8共14项Python3.10 tests通过0.149秒，Ruff通过；真实CLI、范围精确分区、类别兄弟隔离、篡改拒绝、到期边界。无网络/source/prod/config/DB访问更改。
