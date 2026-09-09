# 风险5有限probe与固定版验收脚本 ready（未真实执行）
- remaining_markets / Mac；独立源码1e6716a clean，无新repo代码提交或生产写入。仅生成/tmp脚本与本文，不持有父运行文件。
- /tmp/tushare-risk-probe.py：9请求，5API先各1；ST300125.SZ官方pub20250424/imp20250425/代码全历史3对照；alert20260311全市场/301373.SZ精确/0310-0312范围3对照；其他3API20260904。共享account/api gates+quota间隔、Pipeline lock/capture/normalize/attempts；90秒采集deadline、拒权同API跳过、限频停止共享backoff。保存完整响应与明确无观测gap，不猜非空/权限/完整，不promote capability、不改config/enable、不publish；父审计后manual固定publish（时间另计）。
- /tmp/risk5-fixed-verify.py：同一脚本云/Mac验证固定release-id，SHA raw/observation/Parquet、29官方列/未知列保留、source_ts_code/T内部前缀、来源identity/独立去重、默认st pub_date/alert start_date及显式imp/end、ST精确vs全史和alert宽窄/范围全列多重集合。空/缺列/越界/饱和/无观测留gap，不证全历史/PIT。
- --cloud-api只127.0.0.1:8001 trust_env=False，既有INTERNAL_CALL_SECRET→X-Internal-Call与X-User-Id:tushare-risk-acceptance，匿名401，不打印secret、不JWT/新登录。Mac不带此flag，socket/DNS/providersecret全部拒绝。验收输出只能放固定data root外；具体父命令与阶段说明/tmp/tushare-risk-probe-handoff.md。
- AST语法检查通过；/tmp/test-risk5-verifier-fixture.py临时mock验证通过：5API、12全列/默认/显式查询、4非空日期轴来源对照；9拒权/无观测均保留gap。HTTP mock验端口/既有header/匿名401，真实upstream_calls0。probe main从未执行、未读取真实数据或凭据；仓库clean。下步父review、风险runtime另行发布后按证据执行。
- SHA256 tushare-risk-probe.py: 87de9fb5b56644aad0aeeccc9102f8334639bcceba48a09bd61ffcd71992aec9
- SHA256 risk5-fixed-verify.py: 545866589e198772aa8870b527dc6790280c4f3985bf0bbd6f059aa60ad6beed
