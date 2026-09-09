# 港美财务 8 接口接入

2026-09-09 逐页核对。纯契约与运行注册已在独立候选分支合并；默认关闭，尚未生产发布或探测真实权限。

| API | 官方文档 | 完整输出列 | 单次饱和阈值 |
|---|---|---:|---:|
| hk_income | [389](https://tushare.pro/document/2?doc_id=389) | 5 | 10000 |
| hk_balancesheet | [390](https://tushare.pro/document/2?doc_id=390) | 5 | 10000 |
| hk_cashflow | [391](https://tushare.pro/document/2?doc_id=391) | 5 | 10000 |
| hk_fina_indicator | [388](https://tushare.pro/document/2?doc_id=388) | 87 | 200，原文冲突 |
| us_income | [394](https://tushare.pro/document/2?doc_id=394) | 7 | 10000 |
| us_balancesheet | [395](https://tushare.pro/document/2?doc_id=395) | 7 | 10000 |
| us_cashflow | [396](https://tushare.pro/document/2?doc_id=396) | 7 | 10000 |
| us_fina_indicator | [393](https://tushare.pro/document/2?doc_id=393) | 69 | 200，原文冲突 |

完整输出表作为数据一次定义，字段选择器、类型、默认/非默认列和说明从表推导。8 页当前所有字段标记 Y，未发现 N，不等于供应商不存在隐藏字段；后续响应新增列仍须原文及规范化全保留。官方 HTML SHA 在模块 DOCUMENTS，输出表 SHA 固定在离线测试；原抓取留 `/tmp/tushare-foreign-financial-docs/`。保留 `capitial_ratio` 原拼写，HK `start_date/fiscal_year` 官方 float 类型，避免擅自“修复”源数据。`hk_common_shares` 官方明确提示数据源有误，保留但不得未经校验用于推导股本。

[独立权限表](https://tushare.pro/document/1?doc_id=290)分别列港股财报与美股财报、2000 年、500 次/分钟；与积分无关，不根据当前 10100 积分或其他已付费文本权限判定财报已获授权。实际候选本地上限 50/min，仍须账户和接口门限。两个指标页说明写 200 条、提示又写 10000 条，故保守按 200 触发饱和并保留 `cap_gap`，须实际样本核实。

接口入口：

```python
from backend.shared.tushare_foreign_financial_contracts import (
    FOREIGN_FINANCIAL_CONTRACTS, iter_foreign_financial_jobs,
    foreign_financial_prerequisites, validate_foreign_financial_request,
    split_foreign_financial_request,
)
config = {
    "foreign_financial_apis": ["hk_income", "us_fina_indicator"],
    "foreign_financial_history_start": {"hk_income": "19900101"},
    "foreign_financial_recent_days": 400,
}
```

调用 `iter_foreign_financial_jobs(config, today, identifiers)`，返回现有 `{api_name, params, priority, epoch}` 接口；依赖 `hk_stocks/us_stocks` 的原始源代码列表或含 ts_code 的发现记录。复用 global 原标识校验，包括 `00001!A.HK` 退市标识、美股 `BRK.B`、`ABC/WS`；不截断、归一化或过滤未知上市状态，不能只传当前在市列表，也不等于证券可交易资格。不会访问 token、网络或数据库。

每证券每 API 先规划 400 天滚动**报告期**范围（25 优先级、日 epoch），所有近期范围完成规划后才规划更早的一个连续范围（45、history epoch），API 间惰性交错。范围到昨天，不只枚举季度末；默认 20000101 来自权限表 2000 年的规划边界，精确源起点及更早数据是否存在仍留 `history_gap`。允许显式更早范围，不按上市日或当前列表截去历史。无任意证券样本上限；父持久 planner 游标负责有界入队。

普通请求不加 report_type 或 ind_name 过滤，完整保留源报告类型/财务科目；可针对性使用文档允许的 Q1/Q2/Q3/Q4，但这些请求值不能与输出 `report_type`（例如“单季报”）混同。美股官方示例含 20250427、20050501 等非自然季度末，不能按 A 股 VIP 或自然季度逻辑截断。start_date/end_date 输入筛选的是报告期结束日期，不是公告日，也不是输出的会计年度起点。

**无已文档化 offset/limit 分页。** “可循环提取”只支持利用明确日期范围继续请求，不能猜分页参数。`split_foreign_financial_request(api, params)` 返回 `{children, gap, universe_complete: False}`，按含首尾日期二分，原证券/科目/类型过滤原样继承；满页单证券单日或无界请求保留 gap。仅观察到的科目名和分片成功不能证明供应商全集；这一纯函数没有 runtime 自动接线或关闭父分区的能力。

PIT / 完整性限制必须在 runtime 接入时继续登记：六张科目长表没有币种或金额单位字段，不能假定 HKD/USD，不能借后来的指标币种反推旧报表；指标币种及所有科目原值保留、不换汇。美股指标有 notice_date，但源公告日期不等于市场可用时间的独立证明；其他七接口没有公告日期列，全部没有明确不可变修订 ID。候选用复合自然键和 `preserve_distinct_rows` 保留源类型、币种、不同整行值；父接入后仍需证实 raw/观察/所有版本/字段保真。400 天报告期刷新不能发现所有旧期迟报和修订，需历史再核对。美股官网只承诺主要美股及中概股，非空发现不能证明退市、小公司及全市场覆盖。

隔离验证：

```sh
uv run --no-project --python 3.10 --with httpx python scripts/test_tushare_foreign_financial_contracts.py
```

下一步由父评审后决定 runtime 注册和独立权限有界探测；本候选没有开启生产采集，不修改 coverage 目录计数。


## 运行候选接线

foreign_financial通过registry/固定版store/mirror接入，8接口完整192字段显式请求，默认读取end_date；显式公告日筛选仍可用。来源标识回到独立HK/US历史发现，保留退市!和美股标点，不污染A股发现。科目长表保留ind_name与报告类型/不同源行，不压成单公司单期一行；未公开币种或修订标识继续gap。

与stock_context7、发布聚合优化联合498项Tushare测试通过；仅说明候选功能和隔离存取，不能提升账户权限。下一步按接口有限probe，只有非空字段/过滤/原文到固定版验证通过才启用，权限拒绝或空响应分别记录，继续其他组。


## 2026-09-09 生产探测

八个实际请求均为permission_denied。8份拒绝原文及8份观测已进入ed2f8b46…3faf固定版并校验SHA，均保持禁用；不由10100积分推断独立财报权限。权限缺口不阻其他组，Mac归档闭包待镜像超时修复。


2026-09-09后置Mac验收已完成：固定ed2f8b46的release、probe SHA、probe_samples、dataset_checks、gaps与云端逐项相等；16份拒绝原文/观测已离线可读。8接口仍permission_denied且禁用，无非空数据可用性证明。报告validation/intake-batch-20260909T025328Z/foreign8-mac-verified.json。
