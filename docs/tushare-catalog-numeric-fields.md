# 官方目录数字起首字段修正

2026-09-09复核官方原文发现parse_document采用Python变量式字母起首正则，遗漏数字起首字段。改为保留合法字母/数字/下划线数据列，API名称验证规则不变；仍过滤标点，并按原顺序去重。

同日重新读取6页，HTML SHA与此前目录完全相同，证实是本地提取遗漏。目录定点补42字段：tdx_daily6、shibor7、shibor_quote14、shibor_lpr2、libor6、hibor7；其余条目、原输入与权限/采集状态不变。不是供应商新加字段。

官方原文：[TDX](https://tushare.pro/document/2?doc_id=378)、[Shibor](https://tushare.pro/document/2?doc_id=149)、[Shibor报价](https://tushare.pro/document/2?doc_id=150)、[LPR](https://tushare.pro/document/2?doc_id=151)、[Libor](https://tushare.pro/document/2?doc_id=152)、[Hibor](https://tushare.pro/document/2?doc_id=153)。每页SHA保存在config/tushare-catalog.json；本次公开原文与提取证据/tmp/tushare-catalog-digit-fields/。

五利率API原合同extra_fields已补期限列，实际enqueue将目录/extra/required取并集，本次改前后该五接口请求字段集合一致；不能据目录漏洞推断生产数据已漏列。新TDX合同请求完整38列。解析回归验证数字头、隐藏N、去重及非法标点拒绝；联合intake/structured/other与新13纯合同测试通过。完整实际响应列、历史和PIT仍按各自数据验收，不由目录校验替代。
