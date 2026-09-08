# 镜像安装器持久Python修复开始
- remaining_markets / Mac / codex/tushare-other-markets，已合入228db0d。父手动修当前客户端，本任务不操作LaunchAgent/生产。
- owns scripts/tushare_mirror.py中install_schedule与必要小helper、新scripts/test_tushare_mirror_install.py、新docs/tushare-mirror-installation.md。
- 持久runtime/.venv，uv管理解释器在runtime/.python、依赖copy；健康旧env离线复用，准备失败不bootout不替换plist。仅mock子进程与临时目录验证。
