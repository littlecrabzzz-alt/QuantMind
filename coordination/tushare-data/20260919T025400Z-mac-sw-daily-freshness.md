# 申万日线时效补采与规划顺序缺口

Mac 单写入者仍运行，未改动另一个 agent 管理的业务后端。股票 daily/daily_basic/adj_factor 的最近有值请求已到 20260918；不能用 jobs 最近 rowid 代替最大数据日期。申万 sw_daily 的最近真实尝试停在 20260910，且无 pending 任务。

生产 recent:market 快照锚点 20260919、offset 5500、done=0。market 规划器在近期日历任务前遍历 fund_div/fund_nav/index_weight 等代码集合；每 900 秒只推进 500 个源条目，因此短期日期更新被延迟。历史游标不应重置，需为受配置控制的近期按日期请求增加独立、有限、幂等的优先入队路径。下一步实现该根因修复并验证不跳过历史。

本轮先在 pipeline.lock 空闲时复用已部署 Pipeline.enqueue，加入 20260911..20260918 的 sw_daily 精确日期任务（priority=5、epoch=20260919、reuse_recent_open=True），通过正常限速 worker 真实执行。读取原始对象校验返回 trade_date 与请求一致。

```json
{
  "created_at": "2026-09-19T02:51:57.621114+00:00",
  "jobs": [
    {
      "id": "b3441c4ac02e78febdc8a429436db6416e5b7f571d16def2e901e4897e1406f9",
      "trade_date": "20260911"
    },
    {
      "id": "353b65cccb87d90d2316f1ad2c6a8834a531240e79328580cd0419b05dc89515",
      "trade_date": "20260912"
    },
    {
      "id": "c52c9674ad2052562bef1ef1bc87eb4c2ae585f1335169caa4abda60f5cf809d",
      "trade_date": "20260913"
    },
    {
      "id": "c87ddd55f50435503aa8a2850324d3332fada3a057106b19e0ccec1c66482189",
      "trade_date": "20260914"
    },
    {
      "id": "871834c48075a35b34d3ea3633f49b7fc17a1e395ae877e13d4e98f657cb5402",
      "trade_date": "20260915"
    },
    {
      "id": "cb637decfd0a4d960b670c44c3b5eee28fd4189d370a919d4d86938ffc9e8c78",
      "trade_date": "20260916"
    },
    {
      "id": "98ac41d759dd26340707d6e2504a3ccb95a3710499ec7fd49f39c3d41725e7f5",
      "trade_date": "20260917"
    },
    {
      "id": "1a8ca466063f3147f3bef002a5df07548cea9c4b622ff3fad3c84965d977ab57",
      "trade_date": "20260918"
    }
  ],
  "reason": "Recover latest SW daily dates while the finite market planning snapshot advances through identifier requests. Historical cursor unchanged.",
  "results": [
    {
      "id": "b3441c4ac02e78febdc8a429436db6416e5b7f571d16def2e901e4897e1406f9",
      "trade_date": "20260911",
      "state": "done",
      "row_count": 439,
      "status": "sample_ok",
      "object_sha256": "ef90a48d75bce3173afd515d8fc5204be899ad5ae2c02bf1b391f9c2383bc16e"
    },
    {
      "id": "353b65cccb87d90d2316f1ad2c6a8834a531240e79328580cd0419b05dc89515",
      "trade_date": "20260912",
      "state": "empty",
      "row_count": 0,
      "status": "empty_unverified",
      "object_sha256": "54a510b4486aaaa16da5c6b7b8991e3e5d3603d23ddd938598793659cbbc10a5"
    },
    {
      "id": "c52c9674ad2052562bef1ef1bc87eb4c2ae585f1335169caa4abda60f5cf809d",
      "trade_date": "20260913",
      "state": "empty",
      "row_count": 0,
      "status": "empty_unverified",
      "object_sha256": "480823c49a6b386f18a2586a64d33dbc6be57a3427ca9e5fc4d0aae0e957d77c"
    },
    {
      "id": "c87ddd55f50435503aa8a2850324d3332fada3a057106b19e0ccec1c66482189",
      "trade_date": "20260914",
      "state": "done",
      "row_count": 439,
      "status": "sample_ok",
      "object_sha256": "87cb7bbb2a486dfee8acedb36d8c24c9d0d212df85a856809ab9d1b6a708f297"
    },
    {
      "id": "871834c48075a35b34d3ea3633f49b7fc17a1e395ae877e13d4e98f657cb5402",
      "trade_date": "20260915",
      "state": "done",
      "row_count": 439,
      "status": "sample_ok",
      "object_sha256": "8512744effa22bc90c60cb3b4fea9ae75f88c380fb7b8ea1e0a555a94ff52cc8"
    },
    {
      "id": "cb637decfd0a4d960b670c44c3b5eee28fd4189d370a919d4d86938ffc9e8c78",
      "trade_date": "20260916",
      "state": "done",
      "row_count": 439,
      "status": "sample_ok",
      "object_sha256": "9ffc513156245f6747afd5b849c750d9d87874975ac79a11e3a9d34e392cddf9"
    },
    {
      "id": "98ac41d759dd26340707d6e2504a3ccb95a3710499ec7fd49f39c3d41725e7f5",
      "trade_date": "20260917",
      "state": "done",
      "row_count": 439,
      "status": "sample_ok",
      "object_sha256": "ea52206807476978ec0ea91eafe033c663fdbc9b5c8af515f28e01d0034ceee0"
    },
    {
      "id": "1a8ca466063f3147f3bef002a5df07548cea9c4b622ff3fad3c84965d977ab57",
      "trade_date": "20260918",
      "state": "done",
      "row_count": 439,
      "status": "sample_ok",
      "object_sha256": "61728d89801010ceb0c7f0e8d4ff8ab24a86be3457e58069aa48e06924ffba14"
    }
  ],
  "verified_at": "2026-09-19T02:53:56.309155+00:00"
}
```

本地新增对象需等待正常固定版发布后才进入云端研究子集；缓存同步 success 不代表实时最新日期。全量补采未完成。
