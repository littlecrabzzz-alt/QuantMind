# 持续研究：GLM 真实 API 单轮验收完成

- 时间/节点/任务：2026-09-08T16:00:28.208215+00:00，Mac 协调云端，glm-research-validation。
- 状态：单轮验收完成；完整服务内持续研究队列尚未上线。
- 分支/提交：codex/glm-research-validation，8e989e17ef84afd648d790fcc1604a66e000b330；Mac worktree /Users/lizeyu/.codex/worktrees/quantmind-glm-research-validation。
- 文件范围：scripts/glm_research_runner.py、scripts/glm_model_probe.py、scripts/test_glm_research_runner.py、docs/glm-research-validation-20260908.md 及原持续研究方案的后续记录链接。与 tushare-data 任务没有写入重叠。

方案：[持续研究](../../docs/continuous-research-and-strategy-plan.md)。详细结果在上述分支的 docs/glm-research-validation-20260908.md；本轮只提交独立分支，未合并主分支或重启主服务。运行期间发现主分支已增加本主题协作规范，结束时补记此条共享记录。

验证：十一项隔离测试通过；真实八个实验、二十四组组合独立账务核验通过；协调进程 SIGKILL 后手动重启，原容器/响应/截止时间不变，无重复实验。23:57:29 正常收尾。主流程 36,589 Token，全轮含两道模型审查调用与 smoke 为 38,344 Token；金额未返回。

云端输入 results/frozen-controls-20260907-v3，输出 /root/code/QuantMind/data/agent_research/20260908-glm-comparison；closeout.json、summary.json 与各模型 verification.json 为证据。云端独立代码目录 /root/data/disk/quantmind/staging/glm-research-validation-20260908。未复制权威数据到 Mac，未启动模拟或实盘。

后续从分支提交接续：服务队列/任务租约/自动恢复、跨窗口合同与独立验证尚未实现。Coding Plan 支持范围须匹配执行器；不能把自定义脚本响应成功当作长期套餐权益证明。密钥只在受保护配置，不入记录。此共享增量记录暂未提交，以免混入其他主分支工作。
