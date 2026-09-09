# 规划实测与投影候选归属

只读结果：30b3194 后9038aaee首批 SoftTimeLimitExceeded，160.086175秒，在document_registration失败；planning39.5482秒，identifiers34.1991秒，14325 results/13276 body_reads/1911 bypassed/0 duplicate。停止等待通知前已读取下一cf4df246成功批：220请求，planning33.1066秒，identifiers28.1916秒，14416 results/13363 reads/1930 bypassed/0 duplicate。两批都证实新失败诊断字段生效，去重实际0命中。父并行probe可能争锁，不作为控制吞吐比较。最终错误证据用python -S直接Redis GET，无app导入、无上游请求；此前正常Python曾引入LiteLLM价目表自动联网警告，已告父并改用-S。

- `/tmp/tushare-first-timing-failure-meta-20260909.json` SHA256 `186e72dc82b995898ed9139feeb01621d87add52fd4c9213eab609a9d4b4dbf7`
- `/tmp/tushare-planning-timing-live-second-20260909.json` SHA256 `b2913ab4996018b1e461df686eb0afb79fb89a80b230ae0684a44a9e142a0275`
- `/tmp/tushare-planning-timing-live-third-20260909.json` SHA256 `43bac7c1e5b486104fbf7003caa7ca872192fb86c8a5dc6ec8b29a2b463e4f61`

新归属：text_contracts在独立codex/tushare-text合30b3194，只改pipeline.records可选投影、identifiers使用及专项tests/doc；旧timing保持。当前12发现字段全保留，所有jobs/attempts来源不变；只临时宽表fixture验证，不生产操作。父不改这些块；既有两个records单参数mock仅补可选签名。
