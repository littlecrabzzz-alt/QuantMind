# 开户历史数据运行时

`stk_account` 和 `stk_account_old` 作为独立数据集注册到 `account_history`，复用固定release原文/观察/Parquet、共享限速、队列和本地reader。默认关闭，不修改模板或生产配置。启用需明确 `enable_account_history=true` 和历史范围：`account_history_history_start`（实际纯规划键，日期或逐API映射）或全局 `history_start`；支持 `account_history_apis`。缺范围仅留gap，不猜最早日期。只按月规划history，不对已停更系列反复生成近期请求。旧版请求终点按官方20150529截取；不认为月计划/已停更等于历史全量。

14已知字段全部请求，允许数值null但不豁免列缺失；未知字段、原数值/字符串和修订版本保留。两API口径不同，不跨API合并：新版4个量为万，旧版new_sh/new_sz为户、其他6个量为万户。新版20170210后weekly_hold/weekly_trade缺值有文档依据，不能填0。600积分只是文档门槛，实际权限未验证；1000行是未验证本地guard，不是供应商已证cap。

## 旧统计周期的本地查询

旧版原 `date`（例如 `20141229~0102`）保留原样。规范化复用纯合同 `project_account_period`，只对已识别、合法且不超过7个自然日的 `YYYYMMDD~MMDD` 生成：

- `_period_start=20141229`
- `_period_end=20150102`
- `_period_projection_status=projected`

不展开逐日、不假定周五/交易周，不把结束日期改写进 `date`。`read_dataset`/JSONL 的默认 `date_field=date` 筛选采用**闭区间相交**：周期末日不早于查询start，周期首日不晚于查询end；因此查询20150101会匹配上面的跨年原行。显式 `date_field=_period_start` 或 `_period_end` 改为指定端点的区间比较。可投影只读原date和所需数值列，schema metadata仍解释本地语义。

这只是可重复验证的本地输出解释，不证明供应商start_date/end_date按首日、末日或相交筛选。官方例子在2014年范围返回跨到2015年的周期，因此旧版满guard时暂不自动日期二分或宣称完整父子覆盖，保留blocked cap；没有捏造date/offset/limit参数。新版仍复用其合法请求范围拆分，历史完整性与上游过滤验证另行验收。

未知/非法/过长周期：**raw与完整Parquet均保留**，派生端点为null、行状态为`period_projection_unverified`，attempt保存明确gap，既有运行错误路径标blocked。固定版默认无日期读取/导出仍可查看全部行。若日期查询的`as_of`可见范围包含无法投影的行，reader明确拒绝并返回`period_projection_unverified`，避免把这些行默默排除；已识别的更早as_of视图仍可日期查询。旧文件若未保存投影列亦明确拒绝日期过滤，无日期仍读原数据。schema标明未验证投影行数（整个固定数据集范围）。这不是关闭接口能力，更不是删除源行。

`stk_account`只比较原8位统计标签，不推断周起点。`as_of`仍仅本系统观察时间；新旧接口20150508/20150529边界矛盾、发布时间/修订历史/PIT均保留缺口，不宣称无缝接续。

## 隔离验证和接续

专项覆盖14列/未知/null/修订、跨年和闰日相交/显式端点、原文与JSONL、固定旧版/as_of、未知周期保留与显式拒绝、权限错误/列缺失、1000guard不伪造旧版分区、真实scope键变更后补新月份且旧job不变。stocks不参与该流policy。新pure模块纳入镜像安装清单；不修改标的发现/records缓存入口。

下一步由权威采集入口做有限合法历史样本和云端/Mac固定版验收，确认实际权限/上游过滤/范围；本候选未调用Tushare、未启用或发布生产数据。
