# 两份大附件原始正文补采完成

接续 20260919T034800Z-mac-large-download-timeout.md。部署代码 47cc50ed，101 项附件测试通过。正常轮次中途重试只获约 54 秒并再次超时；使用既有 documents.lock、持久 claims、隔离下载和 _finish_document 对原两份 ID 各执行一次完整 120 秒预算补采，历史尝试保留。

真实落盘 286872349 与 297216747 字节，均 raw_complete=true，逐文件 SHA-256 与清单一致。证据见 docs/tushare-large-document-recovery-production-20260919.json。运行脚本在 Mac /private/tmp/quantmind-large-download-recovery-20260919.py，私有原始验收在归档 validation/large-document-full-budget-recovery-20260919.json。

仅两份原始正文缺口完成；不表示 PDF 文本解析或全部历史完成。普通轮次剩余预算仍可能缩短大文件时限，后续继续评估。采集 LaunchAgent 持续运行，200 GB 用户预留由 300 GiB 停写边界保护。
