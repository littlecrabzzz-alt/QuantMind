# 13接口能力探测参数 ready
- remaining_markets / Mac，只写/tmp/tushare-extra13-probe-spec.json；15请求/13 API，mainbz显式P/D/I，参数已按已核查合同input_fields逐项校验。不改运行文件、未调用API。
- requests含api_name/params、全fields、keys、request_identity_fields、row_cap、逐接口audit。父复用云端业务子进程及共享request_gates执行，不独立发请求。
- 关键：weekly_detail用CU/202601..202653供应商年序号范围，不假定当前ISO周；输出week+week_date据实检查。weekly_monthly一条week/20260904，保留trade_date周期与end_date截至；month未由此样本覆盖。holding为DCE/C/20260904，不据此宣称SHFE/INE已验。
- 审计区分sample_ok/empty_unverified/permission_denied/schema/http/饱和；surv全市场单日可能400行需保留gap。fina_audit/mainbz用20251231完成年度，P/D/I请求身份必须跨raw同值保留。固定release读+source/隐藏字段审计后才可声称该样本接通，不证明全历史或PIT。
