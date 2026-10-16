# 全局股票池合同

用途：统一回测、训练、推理和交易消费方的成员来源、代码格式、权限与空池行为。

## 事实源与保存

一个池是一行 PG 元信息 `qm_stock_pool` 加一个磁盘成员 TXT；`qm_stock_pool_binding` 记录引用。默认成员目录 `/data/stock_pool/`：

- 全局池：`<code>.txt`。
- 用户池：`u<user_id>/<code>.txt`；租户池：`t<tenant_id>/<code>.txt`。
- 一行一个 `SH600036` 风格前缀代码，`#` 开头为注释。API/前端/TXT 使用前缀式；内部 parquet/Qlib 消费通过 `normalize.py`（委托 `StockCodeUtil`）转换后缀式，禁止自行切片。

保存直接重写 TXT 并生效；无草稿/发布/版本回滚。`checksum` 是排序后成员集合 SHA-256 前 16 位，消费结果应保存以识别成分变化；需保留旧成员时先导出。

## 解析入口

消费方只通过 `PoolResolver` 或导出的 `resolve_pool/resolve_pool_sync` 解析：

| ref | 语义 |
|---|---|
| `pool:csi300` | 按 code 解析 |
| `pool_id:sp_xxx` | 按 ID 解析 |
| 裸 `csi300/all_a` | 先查库，再查内置目录 |
| `list:SH600036,SZ000001` | 临时成员列表 |
| `file:/abs/x.txt` 或裸路径 | 本地 TXT/CSV 文件 |
| `all` | 显式不过滤，不是空池兜底 |

```python
from backend.shared.stock_pool import resolve_pool

snap = await resolve_pool("pool:csi300", tenant_id=tid, user_id=uid)
# snap.api_symbols: 前缀式；snap.symbols: 后缀式
# snap.checksum: 成员凭证；snap.warnings: 缺失/空池/来源未接入原因
```

池为空或与输入信号零命中时显式失败，**不能退化为全市场**。旧 COS/策略路径仅作兼容透传并告警，不作为新增接口写法。

## 内置池与权限

`builtins.py` 是内置目录；不要在 SDK、前端或研究模块复制白名单。成员由启动准备和每日 worker 从 QuantDB 刷新；来源未接入的可选池必须告警，不伪造成员。内置池不可手工编辑；被引用的池不可归档/删除。

- 管理接口：`/api/v1/admin/stock-pools`，需管理员权限。用 `/resolve?ref=...` 排查解析，用 `/health` 查看缺文件和空池；`/{id}/members` 读写成员，`/{id}/refresh` 刷新内置池，`/{id}/export` 导出，`/{id}/usages` 查引用。
- 用户只读接口：engine `/api/v1/stock-pools` 的 options、列表、resolve、详情和成员。
- 回测将解析结果物化为 instruments；训练由有数据库访问的编排器传 `pool_symbols` 给容器；推理/模拟盘等通过 `filters.py` 统一过滤，不能各自实现空池回退。

元信息、权限和 TXT 必须一起核对：直接改文件不会自动修复错误的 PG 归属或引用。初始化 DDL 在 `migrations/001_create_stock_pool.sql`，启动准备入口为 `backend/main_oss.py`；执行它们会写库，不是只读排障。
