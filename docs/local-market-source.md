# 本地市场数据源运行说明

2026-09-27 用户确认：供应商采集以 Mac 为唯一日常入口；云端接收已校验文件并提供研究服务。PostgreSQL业务数据、研究结果和队列仍由各节点自己维护。

| 数据 | 本地触发（北京时间） | 云端处理 | 自动范围 |
| --- | --- | --- | --- |
| QuantDB | 每天03:00，15分钟补查/唤醒补跑 | SHA-256清单校验、PG行情、Qlib、市场分析 | 现有23个数据集；分钟/Tick/旧ETF目录不更新 |
| Binance | 每天08:15，15分钟补查/唤醒补跑 | 固定release核验、Qlib/H5 | BTCUSDT、ETHUSDT已收盘UTC日线 |
| Tushare | 原生worker每5分钟有限批次；研究版每小时、全归档每日发布 | 私有SSH供数，15分钟轮询研究缓存 | `config/tushare-local-research-only.json` 的18个接口 |

Mac离线或休眠时不采集；云端使用最后一个校验版本。联网唤醒后补跑；请求成功不等于发布成功，送达不等于PG/Qlib可用。固定研究输入不会跟随CURRENT变化。

## 原始数据与证据

- Mac QuantDB/BTC-ETH 源：`~/Library/Application Support/QuantMind/market-source/working/project/data/{quantdb,quantbc}`，与研究沙盒隔离。
- 本地编排：`com.quantmind.market-source`，独立客户端在 `market-source-client`；执行的采集代码由主工作树只读挂入本地Docker，2GiB/2CPU，不挂业务库或Redis。
- `market-source/status.json` 分别记录每市场采集、云端应用、本地应用版本；原始采集结果在 `A-collection.json`、`BC-collection.json`。
- 云端接收回执：`/data/local-market-source/{A,BC}-receipt.json`；仅 `applied` 表示派生校验结束。
- 本地 QuantDB 回执：`.local-dev/QUANTDB_SYNC.json`；本地BC使用自己的 `/data/local-market-source/BC-receipt.json`。
- Tushare：既有 `tushare/archive-worker-status.json`、`RESEARCH_CURRENT.json`，云端 `/data/tushare-research` 缓存状态；继续保留历史缺口与权限失败。

## 运行与恢复

在 Mac 主项目执行：

```sh
python3 scripts/local_market_source.py install
python3 scripts/local_market_source.py tick
# 明确需要立即补查时：
python3 scripts/local_market_source.py tick --market A --force
python3 scripts/local_market_source.py tick --market BC --force
```

常规定时失败会保留已成功的采集结果，下轮继续交付；无需反复force。成功版本内容无变化时复用相同清单ID。云端A股接收使用既有行情写锁，目录原子交换前写入恢复日志；中断后判断已安装文件，继续派生，不反向交换旧目录。校验失败不应用；派生失败标记 `files_applied`，不能宣称整条链路完成。

源文件、收件和派生需明确区分。研究任务固定release/快照；业务查询可能在更新期间看到尚未完成派生的旧结果，应以回执和真实截止日为准。云端A股接收不会停止研究worker；已有任务必须使用其固定输入。

本地QuantDB应用复用现有沙盒空闲检测；活动任务、文件冲突、后端未启动时保留待应用版本，下轮重试。本地API及相关worker仅在空闲应用窗口暂停，派生成功才恢复；不操作独立R01容器。

Tushare调整须先移走 `ENABLED`、等待pipeline/documents锁空闲，再停原生worker和安装客户端。合并研究配置时先把旧 `enable_*` 置false，再覆盖白名单配置；保留凭据、限流、检查点及其他已有值。仅关闭planner不足以暂停旧任务，`collection_api_names` 同时限制自动派发。

## 空间与回退

Mac采集保留300GiB最低余量，Tushare500GiB预警；云端接收保留100GiB。新增源中转版及该编排登记的本地/云端A股回滚副本保留最近两版，旧备份、Tushare完整归档、Binance原始release与研究固定输入不自动删除。APFS克隆共享数据块，目录逻辑大小不可直接相加当作可回收空间。

迁移前原生配置保存在 `~/Library/Application Support/QuantMind/maintenance/local-source-20260927`。出错先停止新的 `com.quantmind.market-source`、保留回执与日志，使用最新已验收版本；不要重新开启云端采集作自动回退。需要回退市场目录时，在行情写锁与相关查询维护窗口内使用回执指向的备份，并重新校验派生日期。跨版本回退不能复用旧applied回执。

## 优先级

- P0：股票/指数/ETF日线、复权、交易日历、涨跌停/停牌、基础标的；先保障当前研究能取到一致输入。
- P1：指数权重、行业分类/成分、资金流；继续本地有限批次采集。Tushare历史完整性和PIT仍按课题检查，不能由日更成功推断。
- P2：公告/PDF/文本、广泛财务补采、海外/期货/分钟等Tushare接口暂停，旧记录保留。QuantDB已有财务数据集继续日更，减少重复采集；ETF持仓、复杂财务或特定市场课题有需求时再显式增加范围。

数据接入不会启动研究、调参、虚拟盘或实盘。后续研究继续遵守最近半年保留验证规则。
