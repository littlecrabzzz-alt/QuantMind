# 每日研究资料采集与增量评审

- 状态：进行中；本轮由已有 heartbeat 触发，沿用研究资料工作流。
- 分工：运行现有 `scripts/research_watch.py`；只写其本次 run_dir、既有 digest_state 评审索引及本记录。保留采集脚本和其他任务未提交修改，不编辑业务代码或服务。
- 预检：Mac arm64 / desktop-linux / local-sandbox；handoff passed，HEAD `5a110c714ae569ebfd1152f064ea4066efd4ae20`。本轮不读行情快照，旧沙盒快照不影响公开资料抓取。
- 去重：沿用已评审指纹、14 条待评审及今天两份深研索引；无新增可行动内容时不发研究简报。
