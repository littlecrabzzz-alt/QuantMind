# 其他资产与国际利率契约交接
- Mac remaining_markets，codex/tushare-other-markets，提交 1fad356122558805ac5c9adf0e5aa31f2ec085c6；仅3个已声明新增文件，worktree clean。接续 20260908T183918Z-mac-other-markets-start-a769abc7.md。
- 15个只读接口：opt_basic/opt_daily、sge_basic/sge_daily、fx_obasic/fx_daily、libor/hibor/wz_index/gz_index、us_tycr/us_trycr/us_tbr/us_tltr/us_trltr。export OTHER_CONTRACTS、iter_other_jobs、other_prerequisites。
- 官方数字开头利率字段已补全，LIBOR显式五币种，宏观年度分区降低请求量；期权无过滤+六交易所+逐上市日覆盖退市合约，不发明offset或日期区间参数。未知历史边界、目录饱和、权限表冲突均留gap。
- 6项离线tests及两文件ruff通过；无生产API、正式数据写入、部署。
- 父下一步cherry-pick，注册group other、发现family options/spot_metals/fx_instruments，检查代码规范化、mirror模块、store/schema/runtime配置签名；小样本实测后逐步启用。完整接入和全历史仍未完成。
