# Mac 新增采集 → 云端研究缓存真实增量验收
- Mac release data-63ee57e83ba8e0ea954088bb2b4ad82dcf83831ddde14be2dfd3bf9d00feb974 已发布；云端 cache data-035988bc3c20c3853dd62c955d9d4268ee350ef5e3a6719d814d1dd39af2ce87 source_release_id 一致。
- tushare-research-cache.service 正常结束，Result=success/ExecMainStatus=0/MainPID=0。
- 与前一缓存比较新增 146 个文件（73 observation + 73 Parquet），在云端逐个验证长度和 SHA256。所有新 observation 的 fetched_at 都在 Mac 接管之后：UTC 18:35:52.266587 至 19:12:31.678024。覆盖 index_basic/ci_daily/fund_daily/adj_factor/daily_basic/stock_basic/index_daily/trade_cal/daily。
- 云端实际运行容器的路由读取 daily、adj_factor、ci_daily 各 2 行，upstream_calls=0。非外部认证 HTTP/UI 验收。
- 本地完整版本覆盖审计：246 注册，245 规划，194 有发布数据；51 无发布数据中 37 permission_denied、11 api_error、3 available_empty_only。唯一未规划 p_get 为私人组合依赖。注册与规划不证明完整历史。
- 11 api_error 的冻结证据均指向同一已校验原始对象 f8f00c12283dbb2123ccee6f5afb59063d2fed51e47acfc2a1812e933c6b164b，code=40101，供应商记录为“请指定正确的接口名”；这是既有响应证据，不是本次新权限探测。
- 私有验收产物：~/Library/Application Support/QuantMind/tushare-native-to-cloud-second-release-20260917.json，以及 tushare-native-coverage-20260917.json / tushare-scope-audit-20260917.json。
- 云端清理预检 PID 632645 仍运行，最近进度 40,000 文件 / 77,518,927,420 逻辑字节；没有执行删除。全量历史补采和旧副本清理继续。
