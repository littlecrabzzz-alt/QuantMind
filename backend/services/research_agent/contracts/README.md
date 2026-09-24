# R01 外部执行模式合同（冻结副本，勿改内容）

来源：herdr-controller run `r01-p0` 的 `artifacts/p01c/contracts/`（当前 data-contract **v2.2**，
R01P0-W2C4 订正冻结：layout 订正，不改变语义；v2/v2.1 见 run rev1-backup/ 与 REVISION.md）。
运行时校验与前端类型均以本目录副本为单一实现来源；合同本身仍以 coordination/r01-p0/
冻结文件为准。发现合同缺陷时在 coordination 记录并出变更提案，不直接改这里。

- `data-contract.md` — 回报信封文字合同（v2.2）；`contract_hash` 校验基准为其 UTF-8 字节 sha256。
- `data-contract.schema.json` — 回报信封机器 schema（后端入口逐条校验；与 v2 相同字节）。
- `readiness.schema.json` — 准入对象机器 schema（readiness 读写校验）。

sha256（供核对副本未漂移；W2P3 已从 v2 同步至 v2.2）：

```
5337b291b8d1ba5faac6f10290bb86b1b27a2a62016aa6282a9bbdc26961c39e  data-contract.md          (v2.2)
5ca65c294536657662babf272782e92e3954850c53730040912a1abf19d23f29  data-contract.schema.json
327129308469cb77c3874cd5bcf8022b584d1df4dcf5fef08533fe46d70fd33b  readiness.schema.json
```

历史：v2（sha256 `780046e7d0662c58d6ca0c69cfaa8966ad66d49071461ea4b730f8d592016659`）已被 v2.2
取代；envelope `contract_version` 当前唯一接受 `"2.2"`（旧 `"2"` 未登记 ⇒ 422 unknown_contract_version）。
