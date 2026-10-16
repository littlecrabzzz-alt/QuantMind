# Mac 与云端应用读取切换验收
- 状态：读取切换完成；全历史采集、云端清理继续。
- 提交：c1cf6328c7eada7a16ad130e5a789d6248d334c7，master；handoff --align-git mac 已成功，仅快进云端 Git 元数据，保留共享工作文件。
- 双端源文件 6679，摘要 a1fd3c4af76949629e8983d90797b6f52a54d601bc013e006c6a8e9cbf96fa32。
- Mac quantmind-dev 实际只读挂载完整归档，API healthy。实际容器路由读取 daily 返回 2 行，release=data-448cb8610aa7f67890cc4fb4c2f2a0b765646ad6e8ea4f9d874d938429ab3d48，upstream_calls=0。该检查不是外部认证 HTTP/UI 验收。
- 本地 DB、Redis、research-worker、research-agent 的启动时间与切换前记录一致。云端 QuantDB worker 仍 healthy，Tushare 两个专用采集容器已退出，Mac PID 98801 继续采集。
- 云端 research-cache CURRENT 指向本地上述版本的派生子集，timer active，应用 healthy。
- 云端清理前实测：旧 Tushare 192 GiB，研究缓存 1.5 GiB，snapshots 306 GiB，文件系统可用 162 GiB。未删除旧归档或快照。
- 只读检查 research_cases / research_drafts / qlib_backtest_runs / qm_research_candidate_snapshot / qm_user_research_pool / research_windows 全行 JSON：未匹配 data-64位十六进制版本号。这仅覆盖六张表的直接版本引用，不能代替文件和路径依赖检查。
- 下一步：检查文件侧研究引用、快照组成，随后释放已验证迁移且无读依赖的云端归档；继续本地全量补采。
