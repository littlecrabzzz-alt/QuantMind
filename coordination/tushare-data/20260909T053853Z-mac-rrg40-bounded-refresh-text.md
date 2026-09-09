# RRG40单次只读刷新

text_contracts复用structured既有精确40job/attempt脚本，mode=ro/query_only；SQL事务只保存该40目标快照后即关闭，再逐raw/obs/Parquet验证。输出另命名不覆盖前次报告。一次刷新，无poll/采集/优先级/队列/配置/发布修改；Mac用已安装client，只核这批对应文件的fixedmanifest包含及SHA，0上游。

{
  "cloud_release": "data-dd07dbfd97f243e0f8d330bc9034f4e38c16555a926889b253fa802a21d07734",
  "mac_release": "data-dd07dbfd97f243e0f8d330bc9034f4e38c16555a926889b253fa802a21d07734",
  "cloud_snapshot": "2026-09-09T05:37:32.712726+00:00",
  "prior_snapshot": "2026-09-09T05:01:54.312152+00:00",
  "prior_done": 14,
  "done": 29,
  "pending": 11,
  "failed": 0,
  "newly_done": 15,
  "source_rows": 157377,
  "new_rows": 81385,
  "cloud_published_attempts": 22,
  "mac_available_attempts": 22,
  "mac_files_verified": 66,
  "mac_files_compared": 87,
  "api": {
    "daily": {
      "sample_ok": 14,
      "rows": 75911,
      "cloud_published": 11,
      "mac_available": 11,
      "pending": 6
    },
    "adj_factor": {
      "sample_ok": 15,
      "rows": 81466,
      "cloud_published": 11,
      "mac_available": 11,
      "pending": 5
    }
  },
  "issues": [],
  "full_window_reader_asof": "deferred_not_all40_complete",
  "source_dates": "20260831 single diffusion input, 20 dated lag endpoints x daily/adj_factor; complete calendar skeleton still required",
  "upstream_calls": 0
}

29/40完成，全部sample_ok，原行全字段/代码/日期/身份校验0issue；仍11pending，因此不执行完整40窗口reader/as_of闭包，不降级标准。下一步只需继续现有自动队列，等全部40真实响应及同版清单包含后做固定reader/as_of验证，再按标准镜像比对；不能把该40窗口当完整日历、行业PIT、ETF或策略准备完成。

- `/tmp/tushare-rrg40-text-refresh-20260909.json` SHA256 `8c696cb16a699a1db632931b5bb5e1a9189a8e470fa6f8819435c1e82391c5a8`
- `/tmp/tushare-rrg40-text-mac-refresh-20260909.json` SHA256 `ee960ee35c4386237377d948dbf91ca90540e92a4993d191bebb62fd90b051b4`
- `/tmp/tushare-rrg40-text-refresh-summary-20260909.json` SHA256 `2c8923d790a3d8211e841288a6d003262beca0fb3972eb499b19ac13dca0fbb7`
