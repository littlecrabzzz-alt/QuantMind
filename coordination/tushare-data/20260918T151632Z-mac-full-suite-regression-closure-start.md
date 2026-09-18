# Mac Tushare 全套逻辑回归闭合开始

- 目标：闭合 1354 项 Tushare 测试在当前 master 的真实回归，并用完整依赖环境区分代码缺陷、过时冻结证据和环境缺依赖。
- 已观察：系统 Python 缺 `duckdb` 导致 358 个读取类 error；生产采集 venv 含 DuckDB/PyArrow 但不含 FastAPI。除依赖问题外，独立复跑确认 7 个失败和 1 个 DC 测试 error。
- 修复范围：manifest C encoder eager 序列观测；DC 月范围规划测试；跨日 recent 根复用测试；VIP 加入后的 rate/scope 冻结计数。
- 约束：所有改动在隔离 worktree；只用临时数据库和离线 fixture，不读取 Token、不访问 Tushare、不停止或重启 Mac 生产采集。
- 验收：相关定向测试、完整 `test_tushare*.py` 测试、Ruff、compile、diff check；完整测试环境必须同时具备 FastAPI、DuckDB、PyArrow。
