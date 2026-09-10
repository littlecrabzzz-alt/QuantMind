# 基金规模历史精确批次

`fund_share` 已经由全量 planner 生成 26,788 个沪深市场逐日历史任务。本批执行器只从云端权威队列固定 360 个仍为 `pending` 的任务，沪深各 180 个；默认只做离线清单校验，生产执行必须同时固定任务集合、配置、共享执行器和准备器 SHA256，并通过 authority、schema 6、`ENABLED`、非阻塞共享锁、360 次/90 秒和 100 GiB 余量检查。它不生成新任务、不发布 release、不切换 `CURRENT`。

[Tushare 官方 `fund_share` 文档](https://tushare.pro/document/2?doc_id=207)列出 `ts_code`、`trade_date`、`start_date`、`end_date` 和 `market` 查询参数，单次最多返回 2,000 行。当前队列使用官方支持的 `market + trade_date` 精确日请求；任务存在和成功调用仍不证明供应商的最早历史日、基金全集、修订时间或 PIT 完整。

## 第一批：历史起点诊断

第一版准备器按最早待处理日期、沪深轮转选取 1990-01-01 至 1990-06-29 的 360 个任务。46.368 秒完成 360 次真实请求，全部为 `empty`。清单 SHA256 为 `b1b70f174b342a8e72587ec61445d9b3821620b57e252c0eb9803e61012f85db`，任务集合 SHA256 为 `7453a1ead52b802d4131b8041cf2bd00ae06c7ed801f57b5cfc600e20a450fe5`，收据 SHA256 为 `47f764871e17a5a5c18cf890bb569777e8b4b9008d5f109fd1b4dd44d63abb99`。

这只能证明这 360 个精确请求在本次观察时返回空，不能据此把 1990 年至某个日期整体判为无数据，也不能删除其他历史任务。为了更快形成研究可用的本地存量，后续清单改为优先处理最近的 pending 日期；原有历史任务、planner 游标和普通消费顺序均保留，仍会继续补齐。

## 第二批：近期优先真实验收

近期优先改动以 `54a517c4d3f3fb2f246b1e64c60dbb824a0f6782` 合入 `master` 并部署到云端。相关 `fund_share`/共享 `fund_nav` 10 项测试、Ruff、格式和语法检查通过；部署前生产镜像中的完整 `test_tushare*.py` 断网回归为 994 项通过、174.688 秒。旧的 oldest-first 清单仍可验证，避免已有证据失效。

常规 worker 自然排空后，第二批从 26,397 个 pending 中固定当前最新 360 项，沪深各 180，日期范围为 2026-02-19 至 2026-08-18。默认 plan-only 明确不读取 authority、凭据或网络。生产执行 51.099 秒完成 360 次调用，结果为 256 个 `done`、104 个 `empty`；批内无 pending，执行器没有发布或切换 `CURRENT`。

- manifest：`/data/tushare/validation/fund-share-batch-20260911/batch-2-manifest.json`，SHA256 `e2606ccd5a9671ba42211025939056512af8465b0d2e75cce701283a1f84c8ba`
- 任务集合 SHA256：`96250457d8b3bc67007fe592468c44a5b815af9df85d605578c97a6200bd3105`
- receipt：`/data/tushare/validation/fund-share-batch-20260911/acceptance-batch-2.json`，SHA256 `80d8490b2412615153849b6edcd9561491481a4c0d4fe813ec3888982d2dc0bc`
- receipt ID：`b63ebdaf30062ce41edcdf9cdd2c3e92f939702854d5580e77c25c51e3540078`

两批合计 720 次请求、97.467 秒，最终 256 个非空任务和 464 个空响应。`done` 只表示该请求得到并保存了非空响应；字段、历史下界、全部修订和研究时点可用性仍需在固定 release 上分别验收。正常一小时发布任务用 220.122 秒把结果原子固化为 `data-d5d918ce4bc2cfd3ef6e58c5caeefa29c7d9f9715cd5b8cd0d03d4d07cab64de`；Mac 900 秒镜像任务新增下载 14,028 个文件、完整校验 670,543 个文件后退出 0，错误日志为空。

Mac 随后在移除 `TUSHARE_TOKEN`、禁止 socket 连接和 DNS 的进程中，从该固定版读取 `fund_share` 的 `ts_code/trade_date/fd_share`，限定第二批日期范围并返回 5 行样本；元数据确认 `upstream_calls=0`。这证明新数据可离线消费，不会为已有 release 向 Tushare Pro 重拉；它不把 5 行样本提升为全历史、字段或 PIT 完整证明。

## 第三批：继续近期优先

第三批从固定版发布后的权威队列重新冻结2025-08-23至2026-02-19的沪深各180项，360项全部为 `pending/attempts=0`。46.786秒完成360次调用，结果为270个 `done`、90个 `empty`；清单 SHA256 为 `5a5173cebe2f8b63cbea5686d82c87e0b9045fc4fd4324679bc66b50f0da74cb`，任务集合 SHA256 为 `c122d92211f2f3118565c892a32f8b0eb5987213c61779f978fb6c06e75f807b`，收据 SHA256 为 `0fbdbb190a9cb723b9d08d8294b54c79cf589dca34e7bd46dfdcad5de591aa9f`。三批累计1,080次请求、526个 `done`、554个 `empty`；第三批未发布或切换 `CURRENT`，等待正常固定版周期。

执行前固定版的严格断网审计验证290个已发布 `fund_share` 文件和哈希，总计11,847,041字节。原始224,843行按自然键得到222,116条最新观察，覆盖2026-02-23至2026-09-08、149个日期、2,210只基金；2,727个重复自然键在该固定版内没有不同 `fd_share` 值。代码覆盖仍不均匀：493只基金少于20个日期，1,556只不少于100个日期；manifest仍有26,037个pending任务。部分周末形态日期实际返回1至2行，因此不能按日历启发式跳过请求。该审计证明固定版可查询和文件完整，不证明供应商历史下界、修订全集或PIT完整。
