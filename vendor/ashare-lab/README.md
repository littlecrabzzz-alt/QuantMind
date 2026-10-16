# ashare-lab

A 股日频策略研究框架。数据来自本机 QuantMind 的 Tushare 归档（只读），撮合按 A 股真实规则（T+1 开盘成交、涨跌停/停牌顺延、手数、印花税、除权、退市）。

- 文档：`docs/01-策略设计.md` → `02-接口约定.md` → `03-数据层约定.md` → `04-策略与实验约定.md` → `05-研究记录.md`
- 构建数据：`PYTHONPATH=src python3 -m ashare_lab.data.build --out data/panel`
- 跑实验：`python3 experiments/run.py <实验名>`（实验登记在 `experiments/configs.py`）
- 测试：`python3 -m pytest -q tests`
