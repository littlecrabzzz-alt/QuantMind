# RRG 单时点股票输入：固定镜像到可复核产物

基线 `4446d36`。本候选把已验证的 `/tmp/rrg-ca7c-input-prereq-check.py` 的股票输入部分变成独立可复跑入口，复用现有固定 `read_dataset` 和已冻结作者 `_up_flags`；没有新增策略算法或Tushare接口。它与 [行业坐标/case适配](tushare-rrg-case-inputs.md)互补，不重复注册或放行 research_case。

## 当前门槛，按事实拆开

| 门槛 | 已证内容 | 仍不能声称 |
|---|---|---|
| 行业指数开收盘 | 旧固定坐标验证已覆盖28行业/36008行；当前单点30价格代码与成员l1_code匹配 | 历史分类方法、成员可知时间、修订PIT仍未通过；240股票骨架不是319行业预热 |
| 股票单点扩散输入 | 20260831的240开市日位置，当前20日与lag220对应20日价格/复权，当前20日free_share等字段可用 | 不能填价/剔除成员来修改行业分母，也未做行业聚合/排名 |
| 行业历史成分 | 源含in_date/out_date和历史记录，并非完全没有历史成员 | 没有经认证的known_at；有效期、采集_fetched_at都不能替代当时公开时间 |
| ETF/基准 | 已有ETF日线、复权、持仓和PCF；行业等权基准可由已验行业价格构造 | ETF历史可交易池、分红/成交单位/暴露公告及历史行业映射未通过；季度持仓不是每日PCF |

固定`0e961a886dafaefd91941dd113039652c294c1ccf0a60d4bb36aae15236b7c82`的物理Parquet观察数为fund_daily1630、fund_adj2923、fund_portfolio13299、沪深PCF981+776。数字来自固定manifest，重复观察也计入，**不作为唯一日期数或完整历史证明**。不再把ETF“全部没数据”作为阻塞理由，也不据这些数字放行。

## 新入口与输出

`prepare_tushare_rrg_stock_point.py` 固定220日lag与20日窗口，需要显式release、目标开市日、作者文件和新输出目录。作者文件必须匹配现有坐标验证器的SHA；不会加载任意替代算法。

- 从自然日完整的SSE日历推240个交易位置；当前20与lag20端点分别窄窗查询。中间200位置保留NaN，绝不ffill。
- 保留完整已读daily、adj_factor、daily_basic、成员、行业单点与日历原始存储列及观察引用；不将派生字段回写源Parquet。
- 仅计算作者定义的逐股比较标记。close×adj_factor用于同股两端比例；同时输出原close/free_share/float_share/circ_mv，不擅自做自由流通市值权重或行业分母。
- 缺复权、缺价和缺资本字段都留明细。整日期缺失、冲突日历、重复代码日期、查询触上限均拒绝，不出“完整”结论。
- `report.json`包含查询与固定reader元数据、缺口、物理观察分区数；`manifest.json`给全部产物SHA/大小。输出恒`blocked_data`，不改case状态、交易状态或results。
- CLI禁socket/DNS、secret和SQLite连接；输出禁止覆盖或位于源/数据/Git目录。中断的不完整目录不能作为已完成产物，只以最终manifest验收。

```bash
UV_OFFLINE=1 uv run --offline --no-project \
  --with numpy --with pandas --with httpx --with pyarrow --with duckdb \
  python -B scripts/prepare_tushare_rrg_stock_point.py \
  --root '/Users/lizeyu/Library/Application Support/QuantMind/tushare' \
  --release-id data-0e961a886dafaefd91941dd113039652c294c1ccf0a60d4bb36aae15236b7c82 \
  --target-date 20260831 \
  --author /tmp/quantmind-rrg-author-hdjyrhn1/author/src/factor_algo.py \
  --output /tmp/rrg-stock-point-new-output
```

参数与当前外部case一致（220/20），但工具不读取/修改别人未提交的case/config；若研究参数变化，应重新审查入口，而不是沿用本报告。

## 实际结果与最小后续

[机器证据](tushare-rrg-stock-point.evidence.json)包含固定ca7c和0e961a报告/产物清单SHA、精确比较列。111520行股票输入业务投影完全一致：107862有效比较、末日5394股、连续20日均有效5337股、5576观察股票、坏复权连接0。最终守卫版又在0e961a禁网复跑，结果不变。既有67停牌端点解释不被本工具重新覆盖；未匹配端点仍待分类。

最小新源补证只针对20260831的实际源代码`920680.BJ`、`000851.SZ`：daily各1，必要suspend_d各1，**最多4调用/共同120秒、默认仅计划**。请求来自旧已验端点清单及SHA，完整参数在机器证据next_probe_plan。父须先查现存权威观察，沿既有Pipeline/同锁/gates/不可变原文规则执行；已终态不重复。空、权限、饱和、缺列留gap。发布新固定版后可用本入口重跑同点与旧产物对照；它不会自行采样、启用或发布。

成员PIT需要来源能证实20260804–20260831当时公开的版本或修订公告；反复拉当前ci_index_member不会生成known_at。ETF下一阶段先冻结实际目标池和来源映射，再做该池完整历史/公告/复权/成交核验，不从最优收益倒选。故本轮直接推进输入闭环，保持研究`blocked_data`，无需等227接口全历史下载。

验证：Python3.12.12缓存科学依赖下6专项+3旧case适配共9测试通过，Ruff通过；两真实固定版禁网复跑。Python3.10语法编译通过；现有3.10临时环境缺NumPy/Pandas且离线无对应wheel，运行1项纯日历测试、显式跳过5项科学依赖测试，**未把skip宣称为3.10全量通过**。没有安装新全局依赖、上游调用、生产修改或研究放行。
