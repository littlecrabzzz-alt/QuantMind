# 研究独立发布升级窗口
- 状态：进行中；节点：mac；候选 3aabc7d7，121 项发布/缓存/归档回归通过。
- 占用范围：主工作树 FF 集成、native tushare-archive/source；云端 research-cache timer 在供数进程升级期间短暂停止并恢复。
- 先移开 ENABLED，等待 pipeline.lock、documents.lock 自然空闲，再替换 runtime。保留配置、指针及源进程配置备份。
- 不重启 QuantMind 后端、研究 worker 或 R01 服务，不切换现有课题输入。不修改 R01 验收/执行文件。
- 验证：独立研究 manifest、原 CURRENT 不变、云端来源版本追平与实际读取；完成后释放窗口。
