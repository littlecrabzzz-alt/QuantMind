# Mac Tushare VIP 主营构成范围台账修复开始

- 任务：修复 `fina_mainbz_vip` 已在官方目录快照和运行时注册、但未进入 coverage ledger acquisition scope 的证据缺口。
- 约束：Mac 完整归档生产 worker 持续运行；本次只修改离线覆盖台账和测试证据，不读取凭据、不访问上游、不重启采集服务。
- 依据：`config/tushare-catalog.json` 的 doc 81 同时列出 `fina_mainbz` 与 `fina_mainbz_vip`；运行时 registry/store 均已注册 VIP 合同。当前 scope audit 唯一的 `registered_outside_named_scope` 为 `fina_mainbz_vip`。
- 实施：在隔离 worktree 中把 VIP 名称补入 doc 81 的 `acquisition_api_names`，重跑 catalog、ledger、scope 审计测试并重新生成临时只读审计结果。
- 边界：只修正可审计命名范围，不把注册或已有样本解释为历史、修订、PIT 或文档完整。
