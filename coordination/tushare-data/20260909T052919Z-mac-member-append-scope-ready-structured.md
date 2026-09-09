任务：成员自动追加 scope 候选就绪；接续 20260909T052200Z-mac-member-append-scope-start-structured.md。
节点/分支：Mac isolated codex/tushare-member-append-scope；基线79f4498；提交06acf3ac5a6550387c2c41dc9007485546d8d015已push，工作树clean。
文件：registry/pipeline最小scope接点 + scripts/test_tushare_member_append_scope.py + docs/tushare-member-append-scope.md。归属已释放；remaining进口/validation相邻接点由父串行合并。无生产执行/启用/配置修改。
实现：独立APPEND_PLANNERS仅参与plan_extended；不改旧PLANNERS消费组、next_job、原五接口policy/config。独立recent/history:market_members使用已有预算和snapshot，日期bulk+已观察原始合法板块；新来源在有限快照结束后补全配置范围。默认关闭；旧组未启用、旧清单含新2API则validation_blocked。独立历史起点不继承旧global1990，未知起点/universe/PIT/第二轴均保留gap。
验证：Python3.10专项8、原sentiment6、planning14通过；Ruff和git diff --check通过。旧五接口四轮对照任务/游标相同、既有观测不变、真实next_job消费及权限/account/API gates、历史/近期续跑+新来源追赶、合法饱和child增量且coverage=false均覆盖。
额外全套日志保留：/tmp/tushare-member-append-scope-regression.log 为573 tests/15 errors（含紧凑日期Python3.10解析与缺依赖）；/tmp/tushare-member-append-scope-regression-py312.log 为580 tests/1 failure(pypdf_not_installed)。不声称全套通过，父在既有/tmp/quantmind-calendar-factor-test310/bin/python环境统一复验并包含其日期兼容修复；本任务不再扩环境。
重跑：/tmp/quantmind-calendar-factor-test310/bin/python -m unittest discover -s scripts -p test_tushare_member_append_scope.py（在候选worktree或父集成树）。
下一步：父review/pick/复验/决定有限起点启用；配置例见短doc。预计请求量=日期数×Σ(1+观测板块数)，不等同完整历史或吞吐收益。
