# 自选组合只读 2 API 纯候选 ready

- Mac remaining_markets；基线6b18287；分支codex/tushare-portfolio-read已push，唯一待pick提交005c47e2740abd06cff764308304d87adbcb2792。worktree `/Users/lizeyu/.codex/worktrees/quantmind-tushare-portfolio-read`，clean。只新增contract/test/intake doc3文件（tushare_portfolio_read）。父持有runtime，无生产/上游请求/组合变更。
- p_list446全5列+p_get449全8列，与现存官方HTML和catalog精确一致；隐藏N无披露，默认Y全显式请求，未知/null保留。p_get只查询，唯一name输入来自同epoch真实成功的未过滤p_list(id/name)，不发id/猜名，不包含p_save/p_delete。
- 默认enable_portfolio_read=False，显式portfolio_read_snapshot_epoch UTC+北京时间日界；当前快照不制造历史任务。空列表有效无自建组合观察；失败/饱和/旧epoch不产生p_get；歧义名称/身份固定错误信息，不输出私有值。请求身份name，成分name与其不同；snapshot+request隔离来源id，成分代码/ts_type保持opaque，不默认A股。
- 全历史/删除重命名/PIT/时间戳时区/weight单位/分页cap/rpm/权限未知继续gap；本地30rpm/1000仅保护。未来runtime须认证列表观察来源、实施账户访问控制、审计通用状态/manifest不外泄私有内容，纯合同不是已具备这些运行保障。
- 验证：`/tmp/quantmind-calendar-factor-test310/bin/python scripts/test_tushare_portfolio_read_contracts.py` 7/7通过(0.005s)，socket/DNS禁用；ruff check/format及git diff --check通过。详见候选docs/tushare-portfolio-read-intake.md，官方HTML/SHA与接入结构均在其中。
