# 下一分钟/因子候选父验收完成，固定发布接续
- main/GitHub/cloud同876386e；4793文件/digest96141b0cbc2bf08cd14646ce42b6158be660c44b9a36669e78936970cbb5c4cf，handoff首失败后逐文件diff空才重试通过，无服务重启。父codex/tushare-data-intake现5d442d3已push，干净，尚未merge/deploy。
- 父pick text def23cb→792db04及structured96ec42e→17b6c88，已审实际runtime diff；623完整Python3.10 tests32.462秒通过，日志/tmp/tushare-minute-factor-parent-full310.log。候选212采集API/218dataset，生产仍205/211；只需后续集成发布这组，不重复pick纯模块。
- factor range真实一次调用已完成，session1949 exit0；780行，0901/02/03均出现，0904末日195行全字段多重集等于旧源，无缺列/过滤错误。/tmp/factor-value-range-probe.json SHA82c256757f0b51c5c4995c770def9cdeb16e738d947981e26f68c00c38b2a42f，原12样本SHA96bf…9f82不变。固定reader/月窗口未验证。helper dcd9…6a851和源samplerbc5…d46c均原文件，父17tests通过。全部新证据已归档/data/tushare/validation/intake-batch-20260909T053533Z，清单/tmp/minute-factor-next-evidence-archive.json。
- RRG40最新postcheck：40done、40sample_ok、217026来源行/0issue，/tmp/tushare-rrg40-postcheck-20260909T0626.json。structured优先复用原raw/obs/Parquet/固定reader/as_of闭包；源接口数据完成不等于全RRG240日历/成员PIT/ETF准入。
- 父已启动正常publisher session74591（唯一root尚待poll进程），/tmp/factor-range-rrg40-publish-output.json；使用现有tushare-calendar-factor5-publish-probes.py和boundedsharedlock，0请求/0enable，不暂停消费者。新fixed发布后通知structured核RRG40及给Mac标准镜像；不要重复publish或假设session终止。
- 并行：structured准备factor_value code_only专用启用helper并优先RRG40固定验收；text准备7分钟actual-source probe/fixed验证；remaining准备eco3国家×2对照+idx有限范围至多8call helper（均未执行）。旧4-name补充helper已废弃未审，绝不能执行。
- 根下一步：poll74591；新fixed通知agent、标准Mac镜像（先查无已有process）；完成固定新range780与RRG40验证；待helper交付后一次部署minute+factor候选，cloud新runtime核验前禁止执行code_only enable。所有非阻塞country语义/空公告/独立权限/完整历史/附件/PIT义务保留，goal active。

- 即时接续修正：session74591已exit0，06:30:23Z实际发布data-ca7c1fcb7305d3248b3d820714c4b868087e0fbf66facf2bd17e00cded0c2001（34.325秒/0HTTP），已通知structured固定此版；无需再poll74591或重复publish。随后父标准Mac镜像已启动，输出/tmp/factor-range-rrg40-mirror.json/.stderr，进程handle见工具结果；下一步poll镜像并通知structured做同版Mac核验。
