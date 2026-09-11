# 2026-09-11 11:10 CST — 指数日线、基金净值与基金份额精确波次

- 节点与输入：云端正式 writer，固定输入 `data-00177d548289255711d171ddd8ffc86332f5078951ccb8a618792c82a0528288`；Mac、GitHub、云端代码在执行前均为 `f8362076`。
- 安全窗口：先停 Beat、取消 `tushare_acquire` consumer，等待 active/reserved 连续两轮为空后正常停止 worker；没有 revoke、强杀、重启或 OOM。三份 360 项清单均先通过 plan-only，固定任务、配置、helper、prepare 与 release 哈希。
- 生产结果：`index_daily` 第3批 360次/44.372秒/45152行，281 done、79 empty；`fund_nav` 第9批 360次/48.922秒/245455行，207 done、40 empty、113 split_pending；`fund_share` 第8批 360次/44.847秒/101328行，248 done、112 empty。
- 闭包：合计1080次HTTP 200、零429、391935行；1080 object、1080 observation、849 Parquet逐文件SHA和大小通过，唯一实体共53879750字节。authority闭包 `validation/exact-index-fund-wave-20260911T1100/closure.json` SHA256 为 `f5a026bfae854ba5f12abb5684bf22f8e4d253b9e5488ce300235b242ec04c9d`。
- 恢复：API、Tushare worker、Beat均healthy，restart 0、OOM false；云盘可用228470714368字节，高于100GiB硬保留线。
- 下一步：等待正常 publish-only 将本波与董秘问答首批纳入固定版，再由标准 Mac 客户端单向镜像并做断网、空Token、只读输入验收。旧基金runner的plan输出缺 `would_write` 字段作为schema缺口记录；完整历史、修订、known_at和PIT仍未闭合，RRG保持 `blocked_data`。
- 机器证据：`docs/tushare-index-nav-share-wave-20260911.evidence.json`。
