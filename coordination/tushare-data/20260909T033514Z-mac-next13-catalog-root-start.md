# 下一13接口父集成与目录数字字段修正
- root在独立codex/tushare-data-intake基线f55c6e8上合入纯7/6候选为7daebbd/25b27fd。两agent各自runtime分支，父串行集成公共接点；text只读评估吞吐。
- 父归属：backend/shared/tushare_intake.py目录parse_document、scripts/test_tushare_intake.py、config/tushare-catalog.json及最终总数fixture、台账/进度；不改agent负责的新family代码。
- 已证parse_document字母起首正则遗漏tdx6字段及五利率API期限字段。只读公开官方6页后定点补目录、保留其他条目及运营状态。现有利率合同已请求相关数字字段，不将目录漏洞当实际已丢数据。
- 采集继续，候选隔离测试完再准备生产probe和部署窗口，当前不暂停。
