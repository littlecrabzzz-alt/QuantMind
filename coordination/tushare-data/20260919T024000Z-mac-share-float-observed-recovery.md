# 限售股解禁精确日期补采

Mac 运行操作；不修改业务后端或采集代码。复用已部署 Pipeline.enqueue，在生产 pipeline.lock 空闲时加入 3 个请求，由唯一采集 worker 通过现有限速执行。

官方 https://tushare.pro/document/2?doc_id=160 支持 float_date。保留原 ts_code、ann_date，补采原始结果中观察到的 20270308、20270907、20290907。原父任务继续 blocked，未宣称观察日期覆盖全部日期。

{
  "children": [
    {
      "float_date": "20270308",
      "id": "5605ddc6efcc050438e9840aa092436b56fe5a4220838c22733ef00c03fa9447"
    },
    {
      "float_date": "20270907",
      "id": "91a2726e5bfc0c7b6da8cf8641bbbd242c580649fefca86c3ef79f25c3724a64"
    },
    {
      "float_date": "20290907",
      "id": "76f2f076b180613ecb9ed99217b0af7151c2fc11f3c9914715054c8ab70a014b"
    }
  ],
  "coverage_proven": false,
  "created_at": "2026-09-19T02:39:03.852914+00:00",
  "parent_id": "693bbe812e3011be6a698181c254c48fcc78a11236616e35034cf7cbe70a5f9b",
  "parent_state": "blocked",
  "reason": "Observed dates recover rows but do not prove an exhaustive unlock-date universe. Parent left unchanged.",
  "source": "https://tushare.pro/document/2?doc_id=160",
  "verified_at": "2026-09-19T02:39:58.125281+00:00",
  "results": [
    {
      "float_date": "20270308",
      "id": "5605ddc6efcc050438e9840aa092436b56fe5a4220838c22733ef00c03fa9447",
      "state": "blocked",
      "row_count": 6000,
      "supplier_has_more": true,
      "object_sha256": "322334a9d15d27292b096cc3f1a8d8d440541ae832d766f931e52bf3611e5003",
      "new_rows_against_parent": 2868
    },
    {
      "float_date": "20270907",
      "id": "91a2726e5bfc0c7b6da8cf8641bbbd242c580649fefca86c3ef79f25c3724a64",
      "state": "done",
      "row_count": 10,
      "supplier_has_more": false,
      "object_sha256": "d2c2037755f33c0db16597b1875b70238777a3a7424354889304ddb3bb13c8dd",
      "new_rows_against_parent": 0
    },
    {
      "float_date": "20290907",
      "id": "76f2f076b180613ecb9ed99217b0af7151c2fc11f3c9914715054c8ab70a014b",
      "state": "done",
      "row_count": 4,
      "supplier_has_more": false,
      "object_sha256": "2d4b6b2773286f712be4782ec663e7b27b8cae3abc3e3b7829ecc6a98f3b2385",
      "new_rows_against_parent": 0
    }
  ],
  "parent_state_after": "blocked",
  "new_distinct_rows": 2868,
  "parent_rows_not_in_children": 2854
}

20270308 子请求仍触及 6000 行上限，缺口保留。后续不得将此次补采或无 has_more 的另外两个日期推断为全历史完整。

用户新约束：本地至少预留 200 GB；保留现有 300 GiB 周期停采线及 500 GiB NAS 状态提醒。另一个 agent 负责本地业务后端，本任务不修改其服务。
