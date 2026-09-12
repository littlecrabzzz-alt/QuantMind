# 自选组合只读候选（446 / 449）

候选已接入合同、两阶段离线规划、固定版本地查询和 Mac 镜像运行文件，仍默认关闭；没有生产配置、真实账户读取或组合变更。只允许 `p_list` / `p_get`，明确排除 `p_save` / `p_delete`。组合内容是账户私有数据，查询元数据固定标记 `account_private`；当前入口只读取调用者显式指定的本地固定版，不新增公共 HTTP 数据接口。

| API | 官方输入 | 完整输出 | 语义 |
|---|---|---|---|
| [p_list / 446](https://tushare.pro/document/2?doc_id=446) | name 可选；规划使用不带参数的完整列表 | id(int)、name(str)、desc(str)、create_time(datetime)、update_time(datetime) | 查询本人自定义组合；成功空列表表示本次未观察到自建组合 |
| [p_get / 449](https://tushare.pro/document/2?doc_id=449) | name 必填，必须来自实际 p_list | id(int)、ts_code(str)、ts_type(str)、name(str)、desc(str)、weight(float)、create_time(datetime)、update_time(datetime) | 只查询组合成分，无写入语义 |

13 个输出字段全部 default Y，没有已披露的隐藏 N 列。示例只选 3 个成分字段，不能据此缩小合同；显式请求全部已知字段，原文、未知返回列和 null 全保留。`p_get.name` 输出是成分名称，请求中的 `name` 是组合名，两者不可混用。

来源为此前保存的官方 HTML，未访问私人组合或调用 Tushare 数据 API：

- `/tmp/tushare-full-schema-audit-20260909/446.html`，SHA256 `0da5b3515d7edeea480afb0da2c88ec91572513d0d3dbacdc233561a1ac98d12`。
- `/tmp/tushare-full-schema-audit-20260909/449.html`，SHA256 `2d5ea23348bca63430b672300ce7200328736bc753a56b4bd351b09b9c067039`。
- 合同逐列元数据与目录字段集合一致。官方未说明积分、独立权限、频控、数值上限或分页参数；保持 `unprobed`。本地 30 rpm / 1000 行仅为保守保护值，不是供应商限额。

## 规划接点

导出 `PORTFOLIO_READ_CONTRACTS`、`iter_portfolio_read_jobs(config,today,identifiers=None)`、`portfolio_read_prerequisites(...)`。family 为 `portfolio_read`；`enable_portfolio_read` 默认关闭；`portfolio_read_apis` 只能选择上述 2 API。必须显式 `portfolio_read_snapshot_epoch=YYYYMMDDTHHMMSSZ`，沿用现有 `_epoch` 验证属于传入 `today` 的北京时间日期；实际供应商时间戳时区仍未知。

`p_list` 先产生无参数快照；`p_get` 只有在 Pipeline 从同一 authority 中最新的持久化、同 epoch、终态成功的实际 `p_list` 任务重建列表观察后才能规划。依赖结构为 `identifiers['portfolio_read_list']`，内含 `api_name='p_list'`、`params={}`、`epoch='snapshot-'+UTCepoch`、`status='done'/'empty'`、原文 `rows`（只投影规划必需的 `id`、`name`）。手填配置名不构成来源。未完成、权限拒绝、饱和或旧 epoch 观察不会规划成分。

组合名只作为合法结构化 `name` 输入，不拼接命令；不裁剪、大小写折叠或 Unicode 标准化。源 id 只用于发现身份检查，不作为上游参数。同名不同 id / 同 id 不同名视为歧义并拒绝推断。缺字段、非法字符仅抛固定文字，状态和 gap 只输出计数，不输出私人名称、描述、代码或持仓；生产运行接线还必须审查通用任务状态/manifest/读取鉴权，不能假定本纯模块已完成隐私边界。

历史配置不会生成日期任务；没有官方 date/range/as-of/history 参数。未来定时快照可留存新增观察，无法补齐首次采样前、两次采样之间或已删除/改名组合的全部历史；不能把“当前所有组合”称作全历史。未来调度必须校验快照时效、账户归属及实际权限，并在新 epoch 重新发现；列表与成分之间也不是原子快照。

## 身份、时间与未完成项

- 列表自然键候选为账户范围 id；成分 id 只称“编号”，不能证明跨组合唯一或永久不变。合同以实际持久化的 `_observation`（成分再加 `_request_identity`）隔离不同快照/请求，保留来源 id 和完整不同源行。请求身份是组合 name；运行层需保留列表 id 的私有来源关联，但不能把列表 id 伪装为合法请求输入。
- `create_time` / `update_time` 是供应商创建/修改元数据，没有 timezone、精度、成员有效期或 PIT 保证；默认查询日期为 `None`，不可当作交易日或历史成员起止时间。保存实际请求/观察时间，后续不改写旧观察。
- `ts_type` 是用户自定义分类；`ts_code` 可为股票、行业、概念等，保留原始代码/类型与账户组合上下文，不能一律转 A 股前缀。跨市场识别和内部 opaque namespace 投影须在运行接入时明确验证。
- `weight` 单位、百分比/比例、是否归一化、负数/零含义均未说明，不缩放、不检查合计为 1、不强加非负约束。
- cap 不明且没有合法分页、成分过滤或历史拆分。达到本地保护值必须保留饱和缺口，不自动猜组合名或重复源请求；同值多行 multiplicity 和跨时点删除语义也未证明。
- 空列表是成功观察，不是接口失败，也不证明历史上从未存在组合。空成分可能是本来为空、已改名/删除或读取竞争；需要保留原响应和来源，不制造失败或完整性结论。

隔离验证：Python 3.10 专属 7 tests，禁 socket/DNS；全 13 字段/合法输入、默认关闭、时区日界、真实观察依赖、空列表、旧 epoch/失败观察拒绝、私有错误信息不外泄、排除写 API、惰性有限消费与完整后续序列。
