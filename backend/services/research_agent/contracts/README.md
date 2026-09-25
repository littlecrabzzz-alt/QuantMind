# R01 外部执行模式合同（冻结副本，勿改内容）

来源：herdr-controller run `r01-p0` 的 `artifacts/p01c/contracts/`（当前 data-contract **v2.3**，
R01P0-F1C1 修订冻结：AC-01 分红三日期事件结构，配套 schema v3/包版本 v2；v2.2 见 REVISION.md）。
运行时校验与前端类型均以本目录副本为单一实现来源；合同本身仍以 coordination/r01-p0/
冻结文件为准。发现合同缺陷时在 coordination 记录并出变更提案，不直接改这里。

- `data-contract.md` — 回报信封文字合同（v2.3）；`contract_hash` 校验基准为其 UTF-8 字节 sha256。
  注：F1C1 的 "schema v3" 指 etf-input-package.schema.json；回报信封 data-contract.schema.json 字节未变。
- `data-contract.schema.json` — 回报信封机器 schema（后端入口逐条校验；与 v2 相同字节）。
- `readiness.schema.json` — 准入对象机器 schema（readiness 读写校验）。

sha256（供核对副本未漂移；W2P3 已从 v2 同步至 v2.2）：

```
97bae9de50855a419d9d77a339d0ebc5cc0ba2217f59b2845c15b094d5b33f44  data-contract.md          (v2.3)
5ca65c294536657662babf272782e92e3954850c53730040912a1abf19d23f29  data-contract.schema.json
327129308469cb77c3874cd5bcf8022b584d1df4dcf5fef08533fe46d70fd33b  readiness.schema.json
```

历史：v2（`780046e7…`）→ v2.2（`5337b291…`）→ v2.3（当前）；envelope `contract_version` 当前唯一
接受 `"2.3"`（旧 `"2"`/`"2.2"` 未登记 ⇒ 422 unknown_contract_version）。ledger-contract（p03 消费）
现为 v3（`1569448f…`），p04 sidecar 不 vendored、不校验，仅证据引用。
