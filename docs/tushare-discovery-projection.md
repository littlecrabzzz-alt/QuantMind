# 标的发现的临时字段投影

在现有 `Pipeline.records(result, *, fields=None)` 增加可选投影，仅 `identifiers()` 使用。默认仍返回全字段；原始对象、normalize/Parquet、任务和 attempts 的发现范围、SQL、历史游标、schema 和已有计时都不变。无需迁移或修改配置。

当前完整发现列为 `ts_code,index_code,level,fut_code,o_code,n_code,name,hm_name,l1_code,l2_code,l3_code,con_code`。未来新增发现分支必须同时更新此集合。测试覆盖跨市场、历史 T/!AE 身份、ETF、期货、行业三级代码、游资名称、成员代码及 jobs/attempts 并集；静态测试检查显式 record 访问未超出投影。

每份 JSON 仍完整读取、解析。仅预先建立字段位置，避免为每个宽表行再构造全字段字典。重复列沿用最后值胜出及首次插入顺序；所有源字段仍检查可哈希性。所有行长度仍检查，即使异常在未选列中也报错；非数组或长度不符的行走原 `dict(zip(..., strict=True))` 路径。缺失选中列不会猜填。既有两个 discovery mock 只补可选参数，原断言不变。

隔离 Python 3.10 fixture：4 份不同对象，每份 6,000 行 × 342 列，共 68,543,176 字节；旧/新读取均 4 次、去重命中均 0，发现输出 SHA256 均为 `e3644b1b5f0bdad9293ea263dc9d003db5becb86d38b9c1091a02833d7576142`。未启用 tracemalloc 的单次耗时 0.461 → 0.303 秒；另一次 tracemalloc 测量峰值 178,914,663 → 101,944,296 字节。该测量是有界合成宽表，不是生产吞吐承诺或进程 RSS 测量。完整 JSON 解码与全历史 SQL 仍是现有上限；没有跨 tick 缓存。

可复跑：

```bash
PYTHONPATH=scripts UV_OFFLINE=1 uv run --python 3.10 --no-project --with httpx --with pyarrow --with duckdb python scripts/test_tushare_discovery_projection.py --benchmark
```

本候选不操作生产。部署后的 planning/identifiers 原有计时才能判断真实收益；此前两个实际批次的 immutable-body 去重命中为 0，不将此前优化宣称为已证实加速。
