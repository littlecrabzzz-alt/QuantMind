# 币安16项批次补录完成
- 节点：Mac local-sandbox采集和验证；云端authority发布新独立根。用户已确认“按上述范围先补一批”。
- 实现提交：6c2c0d1ba1c443ddc9cf49e0aa7ac0afee20a49c；批次文档提交：5f3836ce。工作树 codex/binance-data-20260926；主分支已快进合入，其他任务未提交内容保留。
- 发布：`/data/binance-batch-20260926`，4,010个传输文件SHA通过，29,550条唯一UTC日线，10币/4bStocks/2股票永续；共新增13标的并重新核验原3标的。各品类、上市范围、release/hash详见 `docs/binance-data-batch-20260926.md` 与同名JSON。
- 唯一上游尾部缺口：UNITREE09-25归档404；保留partial原始证据，显式截止09-24的37行完整前缀已发布。CXMT39行至09-25。两者research_ready=false、PITfalse。
- 独立验收发现Qlib将8个晚上市币种首日设成全局首日；已修复仅CRYPTO生命周期，保留原failed报告和修复前instruments。本机/云端修复后两份H5每份29142×7值、70份Qlib203994个值/offset、10币起止和来源绑定全过。云端RD准备及70个真实因子读取样本通过。
- 测试：采集/发布42项 + 含Qlib/PyTables的研究输入/路径31项 = 73 passed, 0 skipped。正式路径产品隔离拒绝测试通过。
- 范围：原quantbc及旧AAPLB CURRENT与BC08:15调度不变；新批一次性补录，未设为默认或页面数据根，不启用新增调度、策略或交易。ENABLE_CRYPTO/ENABLE_REAL_TRADING保持false；未重启共享服务。
- 代码与数据分开核验：实现提交双端handoff通过（7343files，digest04fedcb11d315a2ba9d7ee7669d5813d9156638b0dabafd27adb9e3e996d6d7e）；CLI实加载新源码，数据逐文件校验后原子发布，再在正式路径实读。文档和本记录提交后沿既有handoff对齐元数据。
- 证据：Mac `output/binance-batch-20260926/`；云端 `/data/maintenance/binance-batch-20260926/`。没有云端新批自动回传或全市场历史/PIT完整性的承诺；新池下一步扩日更须显式配置目录与币池。
