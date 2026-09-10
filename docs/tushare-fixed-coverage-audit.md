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

2026-09-10T14:20Z 对云端固定版 `data-66f5a3d5084ac67a14240f56ebc0e4b9eb54fbdf3911cec06bfc7ca2f8da3ffb` 的离线对账结果为：代码注册243项、固定版规划243项、注册但未规划0项、已有可查询数据集193项、已规划但尚无数据集50项。后50项均保留各自的blocked、permission_blocked或合法empty证据，不能填充伪数据；明细见 `tushare-fixed-coverage-20260910T1420.evidence.json`。这个结果证明命名运行时接口都已进入规划口径，不证明其中任何一项的历史或PIT已经完整。
