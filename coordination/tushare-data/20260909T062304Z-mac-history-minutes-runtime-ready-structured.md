任务：history_minutes7 runtime候选就绪，接续060834Z start。Mac isolated branch codex/tushare-history-minutes-runtime，基线de8e8eb，先独立pick text def23cb→62f8e22（父已持有），唯一新runtime增量96ec42e已push。父只pick96ec42e。
归属7files：registry/pipeline/store、mirror复制项、通用store fixture、分钟专项test、docs/tushare-history-minutes-runtime.md；当前归属释放。无config/ledger/生产/probe修改，分钟默认关闭。
完成：7API58已知列全显式；freq不可变request身份，未知源freq不覆盖。新family trade_time秒级无时区比较，ISO T/空格及跨午夜保留，其他reader日期行为不变。真实源分族和历史标识：股票T、ETF7、IDX CI、SW全层级、fut_mapping实际合约、OPT连字符、HK!；连续期货留unmappedgap。共享秒拆分保code/freq，无猜分页/时区。reader透传所有权限/单位/历史/边界/PIT gap。
相邻授权factor mode：_planning_inputs按spec.planning_dependencies_by_value_mode选择factor_value依赖，mode进policy；不改factor_list或缺省factor_name枚举。实际未完成扫描mode变更测试证明新签名/原jobs保留；生产模式切换须单独审核，不隐式开启。
验证：父固定/tmp/quantmind-calendar-factor-test310/bin/python，最终623 tests全部通过30.318s；日志 /tmp/tushare-history-minutes-runtime-final-full310.log SHA6b6ed6cb74e79ffc0fb833e8dd06545cb7115bd578bb7df1f140405b0dfdcf99。新专项7、纯分钟8、store6、calendar/factor8均通过；Ruff和diffcheck通过。测试全部临时SQLite/MockTransport，socket/DNS/get_secret禁止。
未验：各分钟独立权益/真实供应商schema/时间边界/adjustment/完整历史/吞吐/线上cloud+Mac；text已接收7API与reader详细接口用于仅/tmp probe准备。后续父review/pick/部署决定，不将候选接线当分钟权限已获取。
