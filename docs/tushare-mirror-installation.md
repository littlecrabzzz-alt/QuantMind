# Mac 镜像定时任务安装

入口与数据边界见 [接入运行手册](tushare-intake-runbook.md)。安装器将不含凭据的客户端代码放在 `~/Library/Application Support/QuantMind/tushare-client`，定时任务固定使用其中的 `.venv/bin/python`。不会再把调用安装器的 `uv run` 临时解释器路径写进 plist；临时环境清理后，后台镜像仍有持久运行环境。

首次安装或更新客户端代码，在已核对的代码目录执行：

```bash
uv run --no-project --with httpx==0.28.1 --with pyarrow==25.0.1 --with duckdb==1.5.5 \
  python scripts/tushare_mirror.py --install-launchagent
```

安装器复用已通过离线导入、Arrow 和 DuckDB 内存查询检查的 `.venv`，不需要 uv 或网络，也不自动更新健康环境的版本。没有可用环境时，通过现有 uv CLI 创建 Python 3.12 专用 venv；基础解释器使用 uv 默认持久安装目录，不复制另一套解释器。新环境只安装上述三个客户端依赖及其传递依赖，不安装生产 `requirements.txt`；包使用 copy 模式，避免依赖临时缓存链接。

新环境在运行目录内准备、校验后移到固定 `.venv`。环境创建、依赖安装或客户端 `--help` 导入检查失败时，安装器报错并保留原 plist，不执行 `launchctl bootout`。没有 uv 且没有健康环境时同样保留原定时任务。创建失败清理本次临时环境，不删除原 `.venv`。已安装相同 plist 时再次执行不会卸载、重新注册任务。

已有健康环境时，也可直接用它离线重装客户端：

```bash
"$HOME/Library/Application Support/QuantMind/tushare-client/.venv/bin/python" \
  scripts/tushare_mirror.py --install-launchagent
```

检查后台任务时，`launchctl print gui/$(id -u)/com.quantmind.tushare-mirror` 的程序应指向持久 `.venv/bin/python`，参数包含隔离模式 `-I`；不得指向 `.cache/uv/builds-v0/.tmp...`。镜像仍每 900 秒运行，日志位于相邻 `logs/tushare-mirror.*.log`。检查实际退出状态及本地固定 release；仅成功安装 plist 不等于同步成功。Mac 休眠或断网期间由下一轮补拉，云端采集独立运行。

验证：`scripts/test_tushare_mirror_install.py` 使用临时目录和模拟子进程，覆盖稳定解释器、依赖失败、临时 base interpreter 拒绝、旧环境保留、入口导入失败及重复安装。另以 `UV_OFFLINE=1` 在临时目录完成真实 uv 创建、迁移后的导入检查和健康环境复用；这些检查不操作本机 LaunchAgent、不连接生产。
