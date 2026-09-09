# RRG 固定研究输入薄适配候选交接

- Mac / text_contracts / codex/tushare-text；基线e87dc2b已合入，候选增量commit da146cf，仅新增scripts/prepare_tushare_rrg_case_inputs.py、scripts/test_tushare_rrg_case_inputs.py、docs/tushare-rrg-case-inputs.md。父可cherry-pick此单提交；不带主树dirty/untracked research_case/config/研究笔记。
- 现有坐标consume会重跑行业verify和算法，因此不另调用它；复用同一个read_dataset并要求现有已验坐标报告显式SHA，核对report/release/config一致，保留供应商原列和观测来源，仅生成旧研究glob可读的industry_prices/calendar。research_case外部源码仅路径/哈希参考，未复制/执行；当前SHA b088a620ca9276ea0150e7d238f3a1ba388f06f0049b735ea0cfa0891daec788。
- 新输出 `/tmp/quantmind-rrg-case-inputs-20260909-final/`，input-report.json SHA490dad76ec985055155534cdcb7662de4b07684850de4666a3c356669331ab8f。36008行业价行、1934日历行；48月末下一开市日映射全部有值，最后20260831→20260901，仍execution_price_verified=False。
- 明确两版来源：价格及原日历6e00837911a40223d75d7e4e7b770b4b60b4b7c9f2d208091c6e343f7283bee6；新增日历e1386fc1f304f2ef6ef34d3c59ec99b4f3d1ec34fd49c9841ddd7591a74e1bce。原已验report SHA f6918cc7d445ba4e8c3745c3f830dfc86ce272ee8151cb272647ae24145e5f60；不跟随CURRENT，未改原报告。
- Category只固定审计标签，逐行frozen_audit_scope_only；无known_at造列，industry_members/etf_prices/etf_holdings/etf_pcf明确unprepared。所有语义gates unknown、workflow_stage blocked_data，不写case/state/registration、不回测或算收益。
- 专项3测试通过（来源保留、指纹/输出拒绝、缺日/旧映射冲突及状态门槛），ruff/check+format通过，git diff --check通过。实际离线适配一次后元数据精确查询修正再跑最终新输出；结果manifest三文件字节/SHA复核通过，禁socket/DNS/get_secret。未重复全30行业审计/算法测试，未上游调用/生产写入。
- 入口及完整可复跑命令见新doc。它只是独立输入目录，尚不替代research_case原有源码归档注册和语义审核；下一步父审查后接输入契约版本化，原case仍blocked_data。
