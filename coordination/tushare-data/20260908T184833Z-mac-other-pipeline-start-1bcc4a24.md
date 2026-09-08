# other 15类端到端接入
- remaining_markets，Mac隔离codex/tushare-other-markets；合入父b58433a，942af8c等价pick为b227732。
- 独占registry/store/mirror、新test_tushare_other_pipeline.py；pipeline只改other导入、规范化、identifiers、规划gap和配置签名。父保留publish，不改此函数；不动其他既有测试、ledger/配置/生产。
- 代码命名空间OPT:/SGE:/FX:保留原始source_*，防止合约/品种误归A股。全部15类走MockTransport采集→Parquet→publish→store离线读取；权限拒绝与不完整发现保留gap。
- 下一步独立测试通过后单一delta提交。
