# 本地用户策略

用途：说明文件系统策略入口与 Qlib 配置格式。当前 `UserStrategyLoader` 的主存储可为 PG + COS；`STORAGE_MODE=local` 或数据库读取不可用时可扫描本目录，不能假定把文件放进来就完成了用户/租户注册。

## 本地布局

加载器位于 `backend/services/engine/qlib_app/services/user_strategy_loader.py`：

- `ai_generated/`：生成策略。
- `manual_created/`：手工策略。
- `templates/`：本地模板。
- `archived/`：留存文件，默认列表不扫描。

代码是 `.py` 文件；可用同名 `.json` 保存元信息。具体导入、保存和身份隔离走平台 API；不要用手写文件绕过校验，也不要把本目录当作线上全部策略的事实源。

## Qlib 策略配置

提供 `STRATEGY_CONFIG` 或 `get_strategy_config()`，例如：

```python
STRATEGY_CONFIG = {
    "class": "TopkDropoutStrategy",
    "module_path": "qlib.contrib.strategy.signal_strategy",
    "kwargs": {"signal": "<PRED>", "topk": 50, "n_drop": 10},
}
```

`<PRED>` 需要目标用户有可解析的模型预测，不是内置演示信号。自定义类须匹配目标 Qlib/平台适配器合同；普通 `on_bar()` 样例不能当作 Qlib 可执行策略。

执行用户代码存在安全风险；AST 校验不等于完整沙箱。不要运行不可信导入，不要在策略内写密钥、绝对个人路径或真实账户信息。接口、任务与加载排障见 [Qlib 回测合同](../backend/services/engine/qlib_app/README.md)。
