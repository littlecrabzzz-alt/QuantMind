# Tushare identifier small-key candidate rejected after representative benchmark

- 时间、节点、任务标识：2026-09-12T07:52:10Z，Mac，`/root/financial_next_batch`
- 状态：阻塞集成；候选拒绝
- 候选：`codex/tushare-discovery-small-keys`，提交 `3127facd662d5ca4162615aab4a8e352888181ec`
- 更正：`20260912T075043Z-mac-discovery-small-keys-fnb-complete.md` 的高重复夹具仅证明重复对象上限收益，不代表生产分布。

新增固定夹具包含 5000 个唯一对象、15 个重复 result（约 0.3%）、1000 个与 attempts 精确重复的 jobs、32484 行、3624692 原始对象字节，并调用完整 `Pipeline.identifiers()`。两次基线为 0.188504/0.183579 秒，候选为 0.207180/0.206190 秒；候选慢约 10%–12%。四次规范输出 SHA 均为 `794c9db84c26230fa7ec7baa36c316118534724281c2dd21c1b129b70fcb8301`，计数均为 5015 results、5000 body reads、15 duplicate bodies。

结论：生产报告的重复对象比例同样约 0.3%，小键聚合增加的 JSON 提取、GROUP BY 和读后 stat 成本无法由去重收益抵消。不得合入或部署该候选；保留分支与提交作为审计材料。原高重复基准不覆盖或删除。代表性脚本 `/tmp/benchmark_tushare_identifiers_unique.py` SHA256 `742ef5ade37a6af0cf9f50814c1ea6733efc96152010a8450a54c312651ad66c`，结果 `/tmp/tushare-discovery-small-keys-unique-benchmark.ndjson` SHA256 `00e25ccab4899ed40205a49795fe17e7580fe9628d4ee79befd760c4631067d9`。

下一步：若继续优化，应先增加 identifiers 内 SQL、JSON 解码、stat、对象读取的分段计时，再针对真实主成本提出新候选；不要用高重复夹具或线程池数字替代生产分布。
