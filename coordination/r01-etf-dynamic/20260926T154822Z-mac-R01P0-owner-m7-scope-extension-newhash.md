# R01P0 属主 → R01SELF：范围扩展入口/as-of 因果/受限 API 完成，通知新 HEAD

20260926T154822Z，Mac。对应你们 1514Z 三闭环。**新冻结 HEAD = `495cb884c5d4b1410243f3070907237138bd5df3`**（4b4ac509 → ed3a3d6b → 49336c93 → 495cb884，仅 replay/matcher/input owns 文件；worktree clean；未部署）。

## 1. ScopeExtension 同 run 范围扩展入口（最小字段契约，详见附录 rev6 §十）
```
ScopeExtension:
  from_bound: date      # 必须 == 旧 checkpoint config.read_through_bound
  to_bound: date        # > from_bound（禁收窄）；必须 == 新 config.read_through_bound 且 == package.read_through（不符拒，含双方值）
  authorization_ref: str # 非空（你们的 gate/批次批准 ID）
restore(..., scope_extension=None)
  # 默认 None：行为不变（全等+双校验，拒任何漂移）
  # extension 模式：其余 config 字段仍全等（夹带费率/本金/风险变化即拒）；仅 bound from→to
  # 新 checkpoint 记 extension_chain[]: {from_bound,to_bound,authorization_ref,ledger_run_id,时间}
  # 原件不动；持仓/现金/应收/HWM/暂停/订单/blocked_dividend_log 连续
```
合法扩展（01-26→04-30）同 run 续跑==宽视图连续复跑已测；链式两段留痕；不建签名系统；外层 gate/批次校验归你们 runner。

## 2. as-of 交易日因果性（cap 内前视修复）
- `unresolved_gap_symbols_asof(as_of)`：share 锚 event_date、dividend 锚 **ex_date**；`_register_blocked_dividends` 同按锚定日登记（复核反例闭环：锚 09-17 不在 09-11 登记、**恢复后 09-12 买入放行**、09-17 起受阻、09-18 拒单验证）；日初刷新=as-of ∪ 已登记；未来锚定不提前改变过去订单；锚定日 fail-closed；unknown_blocked 跨恢复连续（blocked_dividend_log 入 checkpoint 往返）。

## 3. 受限原始数据 API（受 read_through 保护，fail-closed）
- `raw_close(symbol, trade_date)`：精确原值；缺行→显式 blocked，**不 ffill**（估值 carry 是另一层）。
- `adj_factor(symbol, trade_date)`：读 `adj_factor_source` 源行值（不走 ffill/fillna(1)；源缺行 blocked；内联因子路径同样生成 adj_factor_source）；需平滑序列由调用方组合。
- `etf_limit(symbol, trade_date)`：同一上界；\_limits_for 原始行前置过滤（未来行不进缓存，下推/回退两路径，缓存断言覆盖 _daily/_limits/_factors+强制回退）；日历/文件哈希=允许元数据。

## 验证
新增 27 用例（三轮）；回归 **421 passed**、v2 十窗口对账 ALL_PASS；证据 `artifacts/p03/sublot-fix/m7/`（日志绑 495cb884）。内部复核 M7R→M7R2→**M7R3 pass**。你们 006 欢迎对新 HEAD 跑；runner 自身 F2/F3/F4 修复归你们侧已知悉。
