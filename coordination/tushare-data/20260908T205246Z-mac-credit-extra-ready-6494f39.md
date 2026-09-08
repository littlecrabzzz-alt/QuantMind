# 信用7纯合同 ready
- remaining_markets / Mac / codex/tushare-other-markets；独立增量6494f390877516ee6de5493026ff8ad652288366，仅2新增文件。已合入8249f6c基线，不重复pick merge。
- exports CREDIT_EXTRA_CONTRACTS / iter_credit_extra_jobs / credit_extra_prerequisites / credit_identifiers。预期group credit_extra；config credit_extra_apis、credit_extra_history_start(str/API map，fallback history_start)、planning_epoch。
- 官方58/59/326/331/161/111/110对应margin、margin_detail、margin_secs、slb_len、block_trade、pledge_detail、pledge_stat；58字段全显式。7详情未公布历史下界/offset分页/停止日期；权限始终unprobed、独立权利None。slb_len不与目录标停的其他slb API混同，未宣称当前更新已实测。
- 依赖复用equity_event._stocks保留T600018.SH，与600018.SH不同。credit_identifiers构造stocks及credit_securities=stocks∪上市funds∪显式观测credit_securities（源后缀，保留退市；OF留在原fund master但不用于该市场请求）。margin_detail/margin_secs/block_trade饱和用credit_securities，父后续应采集原始响应增发现；pledge用stocks。
- 近期7日覆盖延期/假日；margin/slb_len历史按月交易日范围，pledge_detail按月公告范围，其输出start/end为质押期限，不能当查询轴；detail/secs/block逐日。历史各API轮转惰性，未知下界仅近期+gap。
- pledge_stat例外：仅ts_code/end_date输入，每股无界源历史发现+近期逐截止日；不制造start_date/周频。单股1000饱和需验证准确截止日后细分，目前保留saturation_gap。
- block_trade/pledge_detail preserve_distinct_rows=True，读键需源_row_identity；完全同值两笔大宗交易没有公开ID，原始保留multiplicity但content-hash视图不能证明笔数，此multiplicity_gap显式记录。旧质押公告解押/修订超出近期窗口，revision gap保留。
- 新7+复用事件6共13离线测试通过，ruff format/check/diff通过，worktree clean；未改运行模块/台账/限频，无生产API调用。父当前13接口优先集成，信用7可后续独立注册与probe。
