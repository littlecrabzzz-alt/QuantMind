# 15接口及历史规划修复部署窗口

root接管main Git与quantmind/两Tushare worker单次发布；主树631b229，候选f2d8ec3及随后的仅文档提交，507 tests通过。各agent只做独立/tmp准备或只读before/after，不编辑主runtime。准备完成后才取消自己的两个消费者，原任务自然排空，不revoke普通US或研究。schema维持6，无数据库回退或配置批量覆盖。

部署后依次有限foreign8/stock7 probe→固定版原文/reader核验→逐API可用者启用→恢复消费者；HTTP/Mac在恢复后验收。完整输出仅validation与/tmp报告，已配置token不输出。历史规划旧signature/offset由text前后只读验证；空/权限/字段不符分别保留gap继续。
