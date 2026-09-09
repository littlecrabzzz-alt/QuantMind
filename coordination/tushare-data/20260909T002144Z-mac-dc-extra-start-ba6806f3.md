# DC 成分与行情两接口纯候选开始
- remaining_markets / Mac，独立 codex/tushare-dc-extra，基线55848e1，保留已有concept候选但本次仅交新增delta。
- 对照263基线+13发现与148生产+concept4候选，选尚未注册dc_member363、dc_daily382；仅own新增 backend/shared/tushare_dc_extra_contracts.py、scripts/test_tushare_dc_extra_contracts.py、docs/tushare-dc-extra-intake.md。
- 官方已核对历史起点/4+13完整输出/日期范围与三分类输入；6000分门槛非真实权限，保留unprobed。全部纯规划/离线测试，不动registry/store/pipeline/catalog/ledger/生产，不启用、不采集。
