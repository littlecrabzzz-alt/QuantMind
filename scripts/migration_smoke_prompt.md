这是一次最多 60 秒的迁移只读验收，不是研究任务，不继续任何旧会话。
请仅调用一次执行工具，运行下面命令，再原样报告 stdout；不要联网、训练、下单或写文件：

python3 -c "import platform,pathlib; print('MIGRATION_READ_ONLY_SMOKE'); print('system='+platform.system()); print('quantdb_present='+str(pathlib.Path('/data/quantdb').is_dir())); print('backend_present='+str(pathlib.Path('/app/backend').is_dir()))"

工具失败只报告失败，不尝试安装或修复环境，不委派任务。报告完立即结束。
