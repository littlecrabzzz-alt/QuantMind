# fut_rcpt_mat 品种代码实际字段补采

负责 backend/shared/tushare_catalog_delta_contracts.py 和对应测试，在 /private/tmp/quantmind-futures-code-field-20260919 隔离开发。官方 doc496 输出表写 fut_code，但示例使用 ts_code；真实同时请求两列得到 23 行，ts_code 全部有值，fut_code 仍缺。原始观察 abccc4a28fe14209ad0c0b91d596702b.json 保存在 Mac 归档。

将 ts_code 加入额外请求字段，保留目录 fut_code 请求和 schema_gap，按真实品种名称保留仓库/厂库不同记录。不会把字段缺口伪装为完整。修正旧 field_gap_note 中“运行时不请求 fut_code”的描述：实际规划会合并目录字段。后续用新字段重新排入本接口已规划分区，保留旧 job/attempt/原始对象，不重置全局历史游标。
