# 原文持久队列完成：待父集成

- Mac / text_contracts 第四子任务；codex/tushare-text @6fec7938ed2e045af4448649ca47887d916fac93；worktree /Users/lizeyu/.codex/worktrees/quantmind-tushare-text。接续原文 helper 664aeeb 与本地 reader 6d06715；本提交仅 backend/shared/tushare_documents.py、scripts/test_tushare_documents.py。
- 新公共函数 enqueue_documents(root,observation,api_name,records,fields)、run_documents(root,max_documents=1,max_seconds=30)、document_inventory(root)。documents.sqlite schema v1 独立保存下载/解析状态、观察/行/字段映射和全部尝试；SQLite/锁不复制到release。
- 新观察+URL+expected MIME 定位作业，同观察重复登记幂等；空观察/无URL/非法值明确映射，不猜链接。每阶段5次指数退避，PDF本地重新解析不再请求URL；已知PDF字段校验MIME。实际下载含DNS在独立进程组内受总体时限限制，超时清理子进程。
- inventory返回 files/mappings/attempts/counts/reference_counts，附件/提取JSON按哈希保存，崩溃后无映射的已提交文件也纳入files；父manifest应校验SHA256并收集映射，父负责authority和调度。
- 验证：12项离线测试通过（原7+新增5），Ruff及diff --check通过；实际子进程CLI对file scheme在DNS前拒绝。全部临时目录，测试禁socket/DNS；无生产凭据或数据读写、无部署。
- 已知下一步：当前新观察会另排同URL，频繁重复观察会膨胀队列；父要求先集成已测版本。建议后续以 api+原始rowhash+field+URL 未变复用成功文件及原下载fetched_at，映射明确reused并保留首次验证观察；元数据变化重新下载。同URL静默改PDF须独立周期校验，并保留未覆盖缺口。此复用尚未实现，不能在报告声称已避免所有重复文档下载。
