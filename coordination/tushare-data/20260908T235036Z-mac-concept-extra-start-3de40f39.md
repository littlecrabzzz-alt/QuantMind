# THS/DC板块4接口纯候选开始
- Mac remaining_markets，独立codex/tushare-concept-extra，基线91fc460(父正式a972ed1的144+limit4候选语义)；只own新backend/shared/tushare_concept_extra_contracts.py、scripts/test_tushare_concept_extra_contracts.py、docs/tushare-concept-extra-intake.md。
- 核对263+13及144+4后选ths_index259/ths_daily260/ths_member261/dc_index362，无已实现重复。只读4官方页，不改runtime/registry/pipeline/store/catalog/ledger/生产/RRG。
- THSdaily隐藏2列，member隐藏4列且权重/进出日官方暂无、只最新成分，cap未知。ths_index一次无筛选snapshot遵从勿循环；DC显式idx_type三类(table required vs example omitted有差异)。所有实际权限/history/PIT/跨市场成员namespace待验证。
