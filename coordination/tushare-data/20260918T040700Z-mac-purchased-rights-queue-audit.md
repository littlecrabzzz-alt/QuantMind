# Mac Tushare 已购九接口权限与队列审计

- 时间、节点、任务：2026-09-18T04:07:00Z，Mac 全量归档所有者，purchased-rights-queue-audit。
- 范围：`news`、`major_news`、`cctv_news`、`anns_d`、`irm_qa_sh`、`irm_qa_sz`、`npr`、`research_report`、`monetary_policy`。只读 immutable 检查生产 `pipeline.sqlite`，没有上游调用或队列写入。
- 权限结论：生产 4694 个 `permission_blocked` 任务中，上述九接口为 0。私有配置仍按新闻 400、公告/问答/政策/研报 500、央行报告 200 次/分钟设置独立档，并保留 2027-09-08 到期事实；账户总上限仍为 500 次/分钟。

当前队列状态：

- `news`：done 2081、empty 2629、pending 3263、split_pending 709；`major_news`：done 2498、empty 1674、pending 5233、split_pending 1107；`cctv_news`：done 4249、empty 66、pending 1913。
- `anns_d`：done 1486、empty 2613、pending 4289、split_pending 1322；`irm_qa_sh`：done 3327、empty 14194、pending 108155、split_pending 152；`irm_qa_sz`：done 1807、empty 301、pending 14。
- `npr`：done 834、empty 528、pending 7、split_pending 51、blocked 2；`research_report`：done 1227、empty 41、pending 7；`monetary_policy`：done 28、empty 905、pending 7。
- 相关 capability 均有 `available` 记录；新闻按来源记录可用状态。`empty_unverified` 表示该次合法请求为空且不伪造数据，不表示权限拒绝。

`npr` 的两个 blocked 是同一合法叶：`2008-03-28 08:00:00`、机构 `国务院`，真实响应均达到 500 行并返回 `supplier_has_more=true`。生产已保存两个原始 observation、object 和 Parquet；此前 39 次真实合同复核证明供应商公布的 `ptype` 过滤在该数据上不可用，因此不能虚构分页或把截断改成 complete。它们保留为显式供应商覆盖缺口，不属于权限问题。

其余 permission-blocked 主要是未购买的 `cb_price_chg` 父任务及其 4656 个后代，以及分钟、实时、港美财务等独立权限探针。当前审计证明已购九接口仍在正常回填；不把 pending 或合法空结果错误提升为全历史完成。
