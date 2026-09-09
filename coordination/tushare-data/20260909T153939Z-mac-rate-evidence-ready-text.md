# 官方频次分类审计候选完成
- 独立分支codex/tushare-factor-month-planning，父32fe472基线，候选492c43b已push；仅新增审计脚本/测试/文档/227API JSON。父可只cherry-pick此提交。
- 227分类：purchased_special9、independent_unverified38、per_api_override19、points_special3、points_general_candidate155、unknown3。源码30rpm60项，50rpm103项，是本地保守设置而非官方普遍频次。
- 官方现行290区分普通500/min、特色300/min与独立权益；stock_basic50/ths_member200等叶子覆盖保留；cyq_chips200与一般特色300、report_rc总量歧义明确。factor_value doc490没有rpm或每日quota，6000仅行数，保持unknown，不因成功样本/5000试用推权限。
- 用户已购文本有效期按原声明20270908；2000积分于20261205到期要重审特色档。官方频率无承诺有效期，不造TTL。
- docs/tushare-rate-evidence-32fe472.json包含每API文档/政策行SHA、分类、源码gate、历史permissionstatus、来源缺失与unknown；不是可部署配置。无token/生产配置/DB读取，无Tushare数据请求，无运行源码/配置更改。仅两次官方公开页读取及归档HTML本地读。
- Python3.10专项8tests通过（真实CLI临时fixture），Ruff通过。详情docs/tushare-rate-evidence-audit.md。
