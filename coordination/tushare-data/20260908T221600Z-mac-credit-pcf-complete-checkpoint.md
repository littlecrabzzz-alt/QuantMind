# 信用恢复与PCF生产离线验收检查点

- 父任务01a0817d-7378-7673-9b7f-59c302713981，Mac主master bb1fc15（本条/台账/进度待commit）；父worktree quantmind-tushare-data-intake同HEAD。运行代码44d1748/schema5；bb1fc15只新增5纯合同及doc/tests未注册，不需要重启。完整scope未完成，goal保持active。
- 本轮完整事实见docs/tushare-progress.md 06:15；290专项回归、信用7位恢复、PCF2真实样本400行、slb无日期2811行、原文/Parquet/云端API及Mac固定版逐字段类型审计均通过。fixed data-cdf881db31f95b1aefcbdc92de75fdc6e65d8e47b9baec75d6b459ef6f25a680共96064files；Mac手动mirror exec36259已exit0，局部验收脚本/tmp/tushare-etf-basket-mac-verify.py已exit0。运行环境已刷新持久client，不要用uv临时解释器部署LaunchAgent。
- 当前无遗留暂停：只暂停过acquire自然排空，随后仅重启quantmind/tushare-worker；采集7d8e9db3、附件13855542实际恢复，doc worker没有重启。US定时同步88fe98db仍原任务；普通/research未重启。22:12:08Z完成316requests/112.814s整批；信用与PCF非probe自动done24/49。证据cloud validation/credit-pcf-runtime.json及etf-basket-{probe,acceptance,api-acceptance}.json；Mac/tmp/tushare-etf-basket-{probe,acceptance,mac-verified}.json。
- 下一最优先：review 17e23320eb70afb17745d7c3c692b40e53e148f9（remaining worktree quantmind-tushare-other-markets，分支codex/tushare-planner-progress，基线50ee715）。仅pipeline规划块+新tests；62项通过且原方法3/3复现游标重置/尾部饥饿。没有schema迁移，但signature变为有版本JSON；先独立review全部family依赖/anchor/近期6日追赶与manifest体积，再正常部署，不能新旧planner交替覆盖进度。不要为赶本轮直接放生产。
- text在独立quantmind-tushare-text开发元数据优化候选（archive/documents/mirror/tushare_data reader+tests，基线44d1748），尚未交付。只归档新alias硬链接（跨FS复制）、Mac匹配复用、states索引3hex且旧2hex兼容；不自动删除既有对象或历史版本。接续221022Z记录，下一轮收候选review，发布需两个专属consumer自然排空与新旧reader兼容，Mac runtime同步更新。
- structured新5纯合同bcd9e4e已pickbb1fc15，尚未注册/probe；父下一轮可接connect。structured目前补47/49/196/197旧官方依据和最多4只读probe建议，不做真实API；当前网页404不排除历史获取义务。完整目录/历史/修订/PDF/独立权益/源缺口继续保留。
- 采集token只在忽略共享配置，所有API复用持久account/API门与已学习quota；hk_daily现有5/day门不可放松。Mac为无凭据完整镜像读者，权威data/results仅云端。其他用户dirty研究文件必须保留；RRG27104坐标技术通过仍整体blocked_data，不开启策略发现/回测/实盘。
