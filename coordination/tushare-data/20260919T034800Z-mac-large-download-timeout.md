# 大附件下载时限修复

接续 20260919T033100Z-mac-large-document-recovery-start.md。两份 287/297 MB 附件在 320 MiB 上限下均实际触发 20 秒下载超时，证据在 Mac 私有归档 validation/large-document-recovery-live-20260919.json。

继续在 /private/tmp/quantmind-large-documents-20260919 修改 backend/shared/tushare_documents.py 和附件测试：扩大文件上限时总传输预算最多 120 秒，受整轮剩余时间约束；同步延长任务租约，单次 socket 等待仍为 20 秒。默认 25 MiB 路径保留 20 秒。采集进程继续运行，候选验证后自然排空升级，不触碰业务后端。
