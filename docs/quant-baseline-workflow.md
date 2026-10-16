# API 量化基线流程

用途：通过本地 QuantMind API 验证因子目录 → 训练 → 模型注册 → 独立推理 → 含费用事件驱动回测 → 账务核对链路。不调用交易接口。本入口执行后才生成输入快照；需要计算前冻结数据与同口径对照时，使用[冻结研究入口](frozen-research-workflow.md)。

## 运行与恢复

前置条件：目标 API、管理员账户及标准 CN 数据布局 `data/quantdb`、`db/qlib_data`、`data/training_jobs` 均已配置。确认服务实际使用的数据根，不因源码在 Mac 就假定数据库和数据已迁移。首次留档按实际输入预留空间；原始数据、数据库记录及快照无自动清理。

```bash
python3 scripts/run_quant_baseline.py run \
  --api http://127.0.0.1:8000 --output results/my-baseline
```

默认用户 `admin`，密码交互输入；也支持 `QM_USERNAME`、`QM_PASSWORD`、`QM_TOKEN`，或 `--session <私有token文件>`。不要在共享命令、Git 或产物中写密码/token。

首次默认读取 `config/baseline_cn_l1.json`，可用 `--config` 指定。后续从输出目录 `baseline-config.json` 恢复，配置哈希和 API 地址在首次请求前落盘；已有 `catalog.json` 复用原目录版本。改变配置/API 要新建目录；旧实验未记录 API 地址时，首次恢复会绑定本次地址，必须先确认目标。

各阶段支持同一 `--api` 和 `--output`：

```bash
python3 scripts/run_quant_baseline.py prepare --output results/my-baseline
python3 scripts/run_quant_baseline.py train --output results/my-baseline
python3 scripts/run_quant_baseline.py status --output results/my-baseline
python3 scripts/run_quant_baseline.py infer --output results/my-baseline
python3 scripts/run_quant_baseline.py backtest --output results/my-baseline
python3 scripts/run_quant_baseline.py backtest-status --output results/my-baseline
python3 scripts/run_quant_baseline.py verify --output results/my-baseline
```

`verify` 不登录，但会重新校验保留快照的内容哈希。同一目录仅运行一个进程。失败保留任务与日志，解决原因后在新目录重试；不要删除意图文件来强制重发。

## 提交结果不明时

训练、推理和回测 POST 前保存 `*-submission-intent.json`，取得响应后保存 `*-submission.json`。只有意图、没有响应时，恢复会阻塞，不自动再次 POST。先在目标平台查询原任务，将核实的原响应恢复到对应文件；不能编造响应或借换目录再次提交同一不明任务。服务端没有本实验的幂等键，客户端留档只是防重复保护，不是恰好一次执行保证。

## 必须核对的产物

- 使用注册返回的正式模型 ID，核对独立推理、回测和保存的模型一致，不以训练任务 ID 或默认解析代替。
- 保存真实请求/响应、状态、CSV、实际配置、快照和校验值；平台登记、计算完成、账务通过分别记录。
- 从逐日现金、持仓、资产和费用核对净收益与回撤，另列标准每日净收益 Sharpe，不覆盖平台原指标。口径见[执行账务合同](execution-accounting.md)。
- `research-decision.json` 区分技术核对与研究结论；当前基线标记 `needs_validation`，不构成模拟/实盘权限开关。历史已查看区间只能作为开发比较；新研究遵守[最近半年保留与冻结合同](frozen-research-workflow.md)。

默认八因子 LightGBM 基线关闭自动筛选、调参、集成和 WFA，使用事件驱动回测。它没有自动提供同口径对照、全时段逐日重放、PIT 与全部历史市场规则证明。WFA 区间若反复用于调参同样属于研究反馈，不能称为最终独立测试；不同资金/执行器的历史收益不能直接拼成一次比较。

代码变更后的检查入口为 `scripts/test_quant_baseline.py`；真实训练依赖和账务回归需在隔离镜像/新产物目录另行验证，不复用真实基线目录。
