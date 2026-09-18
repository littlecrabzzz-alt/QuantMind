# Mac Tushare 发布扫描优化生产部署

- 候选 `b0fe6bf2` 已合入 master `8dd6a8a3`。`_index_original_files` 保留每次完整目录核对、孤儿文件纳入与符号链接拒绝，只将 Path 多次元数据读取改为 `os.scandir` 单次元数据读取，并按 4096 行批量写入索引。
- 回归：`test_tushare*.py` 1355 项全部通过，107.007 秒；日志 `/tmp/qm-tushare-full-suite-publish-scan.log` SHA-256 `d144b39a29a5f924ebaf7b10bf69d16cae0ca229ab5b7dc8aa8073d3703db807`。Ruff、py_compile、diff check 通过。
- 真实目录只读基准：同一批 50000 个 extracted 文件逐项结果一致；旧扫描 7.834/6.130 秒，新扫描 4.806/4.241 秒。报告 `/tmp/tushare-document-index-scan-benchmark-20260918T155000Z.json` SHA-256 `cac30621040410b5cff5bdbe9ddafad4929a233296ea7388e1b1fc9254249054`。下一次 6 小时正式发布会记录全数据集 stage timing。
- 安全部署：等待旧 worker 自然进入 disabled 后更新运行副本，新 PID 48264；ENABLED SHA `6b45163b…`、配置 SHA `f13a9045…`、archive.env 0600 未变，运行副本与 master 的 `tushare_documents.py` SHA 均为 `220652a0…`。
- 生产验收：规划轮实际处理 2500 个文档任务；下一真实轮 103.263 秒完成 737 次 Tushare 请求及 2200 个文档任务。attempt rowid 748472–749208 全部 HTTP 200：395 sample_ok、341 empty_unverified、1 possibly_truncated；无失败阶段。当前 done 391870、empty 335079、pending 2843949、blocked 871、permission_blocked 5847、split_pending 10316，持续补采。
