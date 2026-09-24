# R01 外部执行模式合同（冻结副本，勿改内容）

来源：herdr-controller run `r01-p0` 的 `artifacts/p01c/contracts/`（W1C2/W1C3 冻结版本）。
运行时校验与前端类型均以本目录副本为单一实现来源；合同本身仍以 coordination/r01-p0/
冻结文件为准。发现合同缺陷时在 coordination 记录并出变更提案，不直接改这里。

- `data-contract.md` — 回报信封文字合同（v2）；`contract_hash` 校验基准为其 UTF-8 字节 sha256。
- `data-contract.schema.json` — 回报信封机器 schema（后端入口逐条校验）。
- `readiness.schema.json` — 准入对象机器 schema（readiness 读写校验）。

sha256（供核对副本未漂移）：

```
780046e7d0662c58d6ca0c69cfaa8966ad66d49071461ea4b730f8d592016659  data-contract.md
5ca65c294536657662babf272782e92e3954850c53730040912a1abf19d23f29  data-contract.schema.json
327129308469cb77c3874cd5bcf8022b584d1df4dcf5fef08533fe46d70fd33b  readiness.schema.json
```
