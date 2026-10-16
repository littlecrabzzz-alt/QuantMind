# 数据库冗余回收前置证据
- Mac 重新逐字节验证 11 份冻结数据库检查点，共17442406400字节；全部与冻结 inventory.jsonl 的大小和 SHA256 匹配。含5份主状态库及6份 validation 历史数据库。检查的是不可变检查点，不把持续更新的本地 live SQLite 当成旧版副本。
- 私有证明：~/Library/Application Support/QuantMind/tushare-checkpoint-databases-verified-20260917.json，status=preserved_checkpoint_databases_verified，含 inventory/owner/current/各库哈希；未写 Token/订单。
- 云端原 SQLite 主文件与检查点头部不同，可能有 WAL 和备份头部规范化，不能只比较主文件或忽略 WAL。只读源库 -> 新临时 SQLite backup 的 archive.sqlite 实测 SHA256 与冻结备份完全一致：aa43ce67ffe444ce96ab681f9977bdd0d26b482c47261c4d498cf8d3604c0376。
- 该云端验证在 tempfile 专属目录中执行且已清理，只读源库，不修改/删除原数据库。其余10份源库仍待同法全量验证；不能用这一个样本宣称全部可删除。
- 云端 payload 清理仍是 quantmind-tushare-prune-apply-20260917.service / PID704312，最新 220000 文件/101801522218逻辑字节已处理。数据库/检查点尚未删除。
- 下一步：payload 清理完成后，在源持续停写、锁排空和读取切换成立的前提下，对剩余源库逐个 SQLite backup+哈希比较并保存完整证明，再删除已证明在Mac保留的冗余库和云端检查点数据库；小型迁移证明及停写标记保留。
