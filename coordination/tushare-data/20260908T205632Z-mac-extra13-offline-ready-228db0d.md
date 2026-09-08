# 13 接口离线集成通过；并行推进消费与吞吐审查

- 用户希望其他工作并行、不等待当前全量数据拉完。维持云端唯一采集、Mac 完整只读镜像；没有增加生产 worker 或调整限频。
- 主 worktree `/Users/lizeyu/.codex/worktrees/quantmind-tushare-data-intake` 已提交：56aa55c（HTTP 完整失败原文）、8bc2328（fina_mainbz P/D/I 请求身份）、f836b41（下一批信用 7 纯合同）、228db0d（本批期货 7 + 财务研究 6 运行注册、规划、日期、发现、失败体读取、mirror 模块和端到端离线测试）。父 worktree clean。
- 当前代码注册 122 数据集（另有 6 财务别名）；信用 7 尚未运行注册，不能算生产接入。生产/shared master 仍 8249f6c、109 数据集，当前批未发布或真实探测，不能说已部署。
- 全部 Tushare 离线测试 237 passed，Ruff/diff clean。新增集成验证全 13 的全部合同字段和未列明返回字段保留、固定 release 读取、P/D/I 同 payload 分开、report_date/surv_date/week_date 日期筛选、期货连续/指数代码发现、错误 HTML/HTTP500 code0 不作为数据、单家族非法配置不阻塞其他家族。
- records/read_samples 已衔接 HTTP 原文协议：错误正文仍可归档，但不尝试解释为数据。fina_mainbz 的老 fixture 通过固定 manifest 下有 SHA/bytes 的 immutable observation 恢复请求 type；不放宽生产身份校验。
- shared master 未暂存其他研究文件，不碰其 config/rrg_sector_rotation.json、research_case.py、research_watch.py 等改动。

## 接续动作

1. 本批 13 的真实云端能力探测（fina_mainbz P/D/I 合计至少 15 请求）、源字段/日期/身份验收、配置启用、发布固定 release、Mac 安装增加两模块并镜像离线读取仍待做。发布前按原流程让自己的采集/文档队列自然排空，合并/push master、等 Syncthing、handoff --align-git mac 通过，仅重启相关服务并恢复队列。现所有队列仍正常运行，无需解除暂停。
2. text_contracts 正只读梳理 RRG 可以立即消费的最小下一步；不重复已经通过的 30 行业 × 1286 交易日结构检查、不跑策略或改研究 case。父已读 `/tmp/quantmind-rrg-slice-parent-20260909/report.json` 确认 slice_structure_passed/38580 rows/0 upstream calls；分类历史版本、known_at、ETF 仍未通过。
3. structured_contracts 正只读审查吞吐；已取得当前 260 requests/90.082s、beat120s、账号240/min（按周期约130/min）的事实。最近200请求捕获均值0.0546s/P95 0.1366s，增加 API 并发未必首要；archive catchup每tick处理4项、manifest约43.55MB，待阶段计时确认。不得将性能推断当测量结论。代理将写自己的唯一coord。
4. 重要新限频证据：hk_daily 共享门已学习为 5 次/天、interval17280s（至少4.8h）；旧摘要1次/小时已经过时。配置3605s不会突破 MAX 共享门。不能为加速绕过配额。
5. remaining_markets 已完成信用7纯合同并释放，提交已整合；不要重复建合同。下一批运行集成另分范围。

完整263目录目标仍 active，本批代码与离线通过不代表全历史、全权限或量化可用性完成。
