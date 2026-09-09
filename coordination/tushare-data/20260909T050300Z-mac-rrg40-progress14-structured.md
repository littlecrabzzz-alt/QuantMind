# RRG40只读增量：14完成，8观察已到Mac

structured/Mac，复用原有限verifier，未上游请求/修改任务或游标/触发发布和镜像。05:01:54.312152Z云端一致读事务核查40个精确任务：14done、26pending；14响应全sample_ok，空0/失败0，总75992源行，比04:34时2done多12。所有新响应raw/observation/Parquet SHA、日期过滤、13+3全源字段/null、source码、rowidentity逐行比对差异0；执行4.3秒，不等待其余完成。

- 本轮云/Mac显式固定同版 `data-e79fc1f4ed2e1e029b5f81ee15e0e81565e9536abdc9f0a78c69e4029cda1bc7`。
- 已发布且Mac文件闭包SHA通过：daily、adj_factor各20250925/26/29/30，8观察对应24文件。
- 已取得响应但该版未含：两API各20250922/23/24，6观察18文件。其他26无attempt，不计已下载。
- 未满40，完整窗口fixed reader对账继续deferred；本次Mac只核验这批14观察42引用中24已入版文件的SHA，未冒称另外18或完整40离线可用。也不外推线性ETA，期间有部署/其他组调度。
- 云增量 `/tmp/tushare-rrg40-current-refresh-20260909.json` SHA `278896d0c881e167791a6a95246cbe1731b28d68132b6796b96779ecb50e11e0`；Mac `/tmp/tushare-rrg40-mac-refresh-20260909.json` SHA `08e749ba5eb6fe924dc228781d87ff554d2fdead5e5e0ddfd8f46147fbbac103`。原04:34报告未覆盖，保留可比时点；全部/tmp仅证据。
- RRG坐标和薄输入适配已独立通过，不需263全目录。单点扩散底数剩26滞后端、自然发布与镜像；仍必须保留240交易日日历骨架和成员历史known_at、官方分类/PIT、自由流通市值口径、ETF历史映射/可交易性等独立门槛。member6 fixed验证继续等root实际release ID；无研究文件或全局progress/ledger修改，归属释放。
