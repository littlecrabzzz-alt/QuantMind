# 用户要求立即提速并增加研究深度

工作树codex/glm-continuous-research，从098c24a9继续；handoff已通过。主控负责仓库外跨候选证据包与派发、README/DELIVERY、实际排空与重启；glm_capacity_now子agent负责controller.py、小型运维容量helper及focused tests，不改Engine/state，不自行重启或写业务库；glm_deep_topics_now只读设计新课题。

计划glm-5.3/max模型3→6，计算保留已验证2；使用已有operational contract.concurrency临时0让当前模型调用自然完成，不撤销在途lease。只有controller空闲才重启新6线程版本，再审计设6；数据/执行/策略身份、A、保留段不动。不制造额度消耗，新增跨候选、家族谱系和数据准入的有证据深度研究。
