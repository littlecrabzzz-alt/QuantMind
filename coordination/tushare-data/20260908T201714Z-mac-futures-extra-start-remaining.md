# 期货补充7接口纯合同开始
- Mac remaining_markets / codex/tushare-other-markets；独立worktree合入e8ee822，保留前序提交。目录7 API尚无运行合同。
- 独占新增backend/shared/tushare_futures_extra_contracts.py、scripts/test_tushare_futures_extra_contracts.py；不改registry/pipeline/store/台账，不访问生产。
- 官方467/492/337/139/468/216/368核查字段、日历/期货代码/周语义、权限、饱和与未知历史；复用_contract/_parse，离线纯planner测试后单独增量交接。
