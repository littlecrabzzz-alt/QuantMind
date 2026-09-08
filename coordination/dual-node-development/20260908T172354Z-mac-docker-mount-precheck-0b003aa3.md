# Docker Desktop 挂载路径预检兼容
- Mac / Tushare full goal；独立 worktree codex/tushare-data-intake。
- 发布预检新报 Local sandbox mount escaped isolation: /data。只读inspect证明当前研究沙盒Source为 /host_mnt/Users/.../QuantMind/.local-dev/project/data，QM_NODE_ROLE=sandbox，HOST_RUNTIME_PATH正确；这是Docker Desktop VM路径表示差异，未发现旧主库挂载。
- 20260908T165909Z-mac-quantdb-scheduled-714717a4.md 已明确释放实现文件；本次仅接管 scripts/dual_node_check.py 与对应已有test_dual_node.py 的路径规范化校验，不改本地运行容器、研究代码或调度。
- 修复仍先验证Mac宿主、本地Docker Desktop，再规范化其 /host_mnt 前缀，并保持resolve后必须位于隔离根内；增加真实隔离路径/旧主库/目录穿越/符号链接逃逸检查。通过后继续完整双端预检。
