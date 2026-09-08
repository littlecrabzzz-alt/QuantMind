# 镜像持久venv安装器 ready
- remaining_markets / Mac / codex/tushare-other-markets，独立增量8f4afaf7feb65bba434b432e5c4d991f5f0110a9；仅mirror安装helper/install_schedule、新专项测试、安装文档3文件。228db0d基线不重复pick。
- 更正开始记录：没有另建runtime/.python，解释器复用uv标准持久安装目录；plist固定runtime/.venv/bin/python -I，绝不保存调用方sys.executable。健康已有env离线直接复用，不要求uv、不升级。
- 新env通过uv venv --managed-python --python3.12 --relocatable及uv pip install --link-mode copy准备；仅httpx0.28.1/pyarrow25.0.1/duckdb1.5.5。构建先在runtime临时目录验证，再移动到.venv；失败保留原env与plist，不bootout。部署入口--help导入失败也不触碰LaunchAgent；相同定义重复安装不重启。
- 7专项+17 pipeline共24测试通过，ruff/diff通过；额外UV_OFFLINE=1真实uv临时目录创建/迁移后import+Arrow/DuckDB内存查询/离线复用通过。未调用本机launchctl、不碰父刚修好的环境或生产。
- 与structured已确认：本提交不改安装copy名单；其credit_extra合同单行应保留，父集成时可直接合并。
