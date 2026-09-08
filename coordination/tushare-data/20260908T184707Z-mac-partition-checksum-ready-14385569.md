# 父审查补正：分区文件SHA256校验
- Mac / text_contracts，独立codex/tushare-text，接续183930 partition-closure-ready。增量942af8cbbde311cd9b4612a7eb483873119bcd56；仅pipeline和原closuretest，文件已释放给父。
- 原v4仅is_file不足以证明文件完整，现按已有parquet bytes/sha256做1MiB流式检查，校验读前后fd/path文件身份，变化/坏hash/缺文件撤回父及祖先resolved。哈希读取不超过预期大小加一块，异常追加文件不会无限读。
- 每实例最多4096项缓存，键含设备/inode/mode/size/mtime_ns/ctime_ns与预期SHA/bytes，未变化时不重复hash；变化重验。无需新持久表，v4版本不变。
- 验证30项通过：closure11（新增同大小替换+缓存命中+嵌套撤回/恢复）、global7、pipeline12；Ruff/diff check通过。无生产调用/凭据/部署。父cherry-pick增量后继续统一迁移发布。
