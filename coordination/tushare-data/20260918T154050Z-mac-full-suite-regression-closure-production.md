# Mac Tushare 全套逻辑回归闭合与生产部署

- 候选/合入：`codex/tushare-full-suite-regression-20260918` 候选 `1bcaf730`，master `f0994fe4`。修改 1 个生产文件和 10 个测试文件；生产配置、Token 文件、归档数据库和权限门未改变。
- 修复：manifest C encoder 的 tuple 被正确识别为 eager，并按 1 MiB 字符窗口进行 UTF-8 编码/写盘；测试与已上线逻辑重新一致，包括 DC 历史月范围、跨日 recent 根复用、VIP 接口范围/频次/reader 总数、fund-nav 时钟、文档 worker 权限复查 mock、当天 portfolio 私有快照。
- 全套验收：临时 Python 3.13 环境同时具备 FastAPI 0.128.0、DuckDB 1.5.5、PyArrow 23.0.0、HTTPX 0.28.1、Pydantic 2.12.5；`test_tushare*.py` 共 1354 项通过，82.848 秒。日志 `/tmp/qm-tushare-full-suite-run-v2.log` SHA-256 `858d705689e0592926203e71902c1fd92ad3fff54a75458df1b93b8e115cd928`。Ruff、py_compile、diff check 通过。
- 序列化基准：三类约 20 MB manifest 与旧实现逐字节/SHA 一致，窗口数 20；候选耗时 0.069/0.080/0.085 秒，未引入可见回退。报告 `/tmp/tushare-manifest-window-benchmark-20260918T152519Z.json` SHA-256 `05b9000de5f3d9082921a35691345ec8e49868b09fd2c5964338ef6f8ff53b82`。
- 安全部署：原 PID 71541 在 ENABLED 暂停后先自然完成到期发布 `data-96ef14e1…`，发布耗时 788.345 秒；随后写出 disabled，才 bootout。ENABLED SHA `6b45163b…`、配置 SHA `f13a9045…` 和 archive.env 0600 均保持，安装后 runtime/source pipeline SHA 同为 `fa5079bd7b8ccc8f9cbc246c4ce18fa17554fe8b916e7ed92c228005129e832d`。
- 真实生产验收：新 LaunchAgent PID 24039、last exit never。首个规划周期处理 2500 个文档；随后真实周期 104.921 秒完成 778 次请求及 2500 个文档任务。attempt rowid 742879–743656 共 778 条，全部 HTTP 200：408 sample_ok、368 empty_unverified、2 possibly_truncated，零 rate/transport/API/permission/invalid 错误。
- 当前队列：done 389036、empty 332430、pending 2847359、split_pending 10308、blocked 871、permission_blocked 5847；结构化和文档全量补采继续。磁盘约 3.6 TiB，总用量 42%，可用约 2.1 TiB。
