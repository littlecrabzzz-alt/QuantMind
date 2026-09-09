# 分钟与因子运行时发布恢复、并行分工

- 时间/节点：2026-09-09 06:54 UTC，Mac root / 云端业务入口。
- 提交：两端及 GitHub master 5d442d3ae4d083530ff492fa7cfbd07d7ae19fd1；接续 20260909T063106Z-mac-minute-factor-parent-ready-876a65ae.md。
- 发布已完成：最终 handoff 4805 文件内容一致；仅 quantmind、tushare-worker 重启，exit 0；四内部服务健康检查 exit 0。06:52:50 UTC 已幂等恢复采集消费者，06:53:36 再次看到 tushare_acquire 任务 7f13d0ac-b591-4b2d-9b39-9fc4d86b54c4 正在运行且队列存在。文档队列正常；既有美股任务 88fe98db 保留。
- 证据：/tmp/minute-factor-handoff-final.json、/tmp/minute-factor-restart-output.json、/tmp/minute-factor-restored.json、/tmp/minute-factor-postresume-inspect.json、/tmp/minute-factor-runtime-import.json。Mac 镜像客户端代码已刷新，原 900 秒调度不变，/tmp/minute-factor-mac-client-install.json。
- 用户希望并行缩短等待：历史采集保持云端统一限速/单写；structured 复核因子 code_only 启用与提交后恢复，remaining 复核日历缺口探测交接，text 以 ca7c 固定镜像诊断 RRG 67 个已有停复牌对应端点。均复用现有隔离 worktree，无并行生产启用/上游请求。
- RRG 日历与价格不再笼统标缺：见 20260909T065243Z-mac-rrg-ca7c-single-point-inputs.md。240 日历骨架、必要价格端点和当前权重字段均已读取；行业成员 known_at/历史版本及权重语义仍需验收，正式研究状态未变。
- 未完成/下一步：factor helper 旧 f443 版本暂不执行，structured 正修复成功发布后 receipt 写失败的误分类；分钟 probe 仅使用 695d4b7e 版本，旧 62a3658b 禁用。两者及 calendar-gap 仍待最终审查/有界执行/双端固定版本验收。623 项父集测试通过不等于所有 API 或历史已下载。新发布与 RRG ca7c 证据尚待归档入云端不可变 evidence capsule。
