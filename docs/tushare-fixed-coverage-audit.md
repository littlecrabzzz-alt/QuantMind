# Tushare固定版接口覆盖对账

`audit_tushare_fixed_coverage.py`在无上游请求的条件下，把当前代码注册的采集接口与一个明确的固定release对账。它分别报告：已注册、已进入固定版规划范围、已有可查询Parquet数据集，以及已规划但尚无数据集的接口。

这些状态不能互相替代。权限拒绝、合法空响应和待验证的实时接口都可能没有数据集；已有数据集也不证明历史、字段、修订、附件或PIT完整。报告保留固定版覆盖状态和API级能力记录，供下一批接入排序，不自动修改配置或任务。

Mac离线示例：

```bash
python3 scripts/audit_tushare_fixed_coverage.py \
  --root "$HOME/Library/Application Support/QuantMind/tushare" \
  --output /tmp/tushare-fixed-coverage.json
```

可用`--release-id data-...`固定旧输入。输出必须位于镜像根目录之外；脚本通过release ID校验manifest，不读取生产SQLite、Token或网络。
