# concept extra runtime 候选开始
- remaining_markets / Mac，独立 codex/tushare-concept-runtime，基于 f2ef011 + e1041f2 的纯合同等价 pick 0f80c5f；不生产访问、不启用、不拉取。
- own registry.py、store.py、mirror.py 的模块安装名单、新 scripts/test_tushare_concept_extra_pipeline.py、必要既有 store 合同数量 fixture。只接 ths_index / ths_daily / ths_member / dc_index。
- pipeline 仅准备独立小 delta（prereq import/map/validation、两族 identifiers、opaque normalization），由父串行整合；不修改主 planner / publish / timing / limit 模块，不争用父工作树。
- 复用现有固定 release / 请求身份 / source 字段 / gaps；THS member 当前成员、历史/PIT/未知 cap 和跨市场 con_code 全部保留未知。
