# QuantBot 工作流验收：真实执行、反馈迭代与收尾

目的是验证工作流，不是开展长期研究或寻找盈利策略。用户已授权在本地调用已有 DeepSeek、训练和回测，过程落盘。请实际执行，不只给计划。你负责提出假设、解释证据并自主决定下一轮改动；外部程序只提供实验工具和固定验证规则，不替你选择候选。完整跑通下面的小样本流程后立即结束；候选不改善同样可以证明工作流有效，不得为追求收益继续扩展实验。

本次会话目录：`/data/agent_research/20260907-agent-loop`。
这是已看过的历史开发比较区间，不是最终独立测试。不做交易，不修改任何平台服务、凭证、全局配置、原始数据、冻结输入、工具代码或旧结果。不启动其他 Agent 或其他研究任务。写入仅限本会话目录内的 proposal、研究记录和报告。不要读取环境变量或密钥文件。

## 实验工具

工具是标准库 Python 脚本，在你所在的 QwenPaw 容器内通过 shell 工具执行：

```bash
python /quantmind/scripts/agent_research_tool.py describe --session /data/agent_research/20260907-agent-loop
```

程序已经固定真实 QuantDB/Qlib 数据、模型训练/验证/比较日期、100只主板股票池、T+1事件驱动成交、费用与资金核对。训练在独立 Docker 容器里运行，4核8GB，无网络。你可以调用此脚本启动这些本地离线实验；用户已授权这些操作。

先用文件工具把 proposal 写到会话目录，再调用：

```bash
python /quantmind/scripts/agent_research_tool.py submit --session /data/agent_research/20260907-agent-loop --proposal /data/agent_research/20260907-agent-loop/proposal-E00.json
python /quantmind/scripts/agent_research_tool.py status --session /data/agent_research/20260907-agent-loop --id E00 --wait-seconds 50
```

`submit` 返回实验ID；`status` 真正等待后返回运行状态或数值结果。shell 工具执行超时设为至少90秒。若 shell 返回后台 session ID，要使用相应的进程轮询工具取回结果，不能重复提交。实验可能需要几分钟，不能因未立即完成就终止研究。不要自己绕过实验工具调用训练脚本或交易API。

### proposal 格式

基线：
```json
{"kind":"baseline","hypothesis":"用真实冻结输入复现当前基线","expected_outcome":"三组对照均完成并通过逐日推理、现金和资产核对","changes":{}}
```

候选由你选择：
```json
{"kind":"candidate","hypothesis":"具体机制假设","expected_outcome":"可证伪的预期","evidence":"引用前一轮实验ID及真实指标，解释为什么下一步做这个","changes":{"features":["mom_ret_20d","vol_std_20"]}}
```
上面的特征只是格式示例，不是推荐实验。另一类 `changes` 是 `{"model_params":{"lambda_l2":10}}`。每轮只改一个轴：特征子集或模型参数。每个候选都从原始基线配置应用 changes，而非上一候选；如果要承接上一轮参数，需要显式包含它们。范围见 describe。

## 必须完成的研究过程

1. 读取 describe，写 `research-plan.md`，明确固定标准、假设与本轮结束条件。
2. 自己提交并完成一次基线 E00。不要使用旧报告假装新实验。
3. 根据刚获得的结果自主选择第一个候选，提交、等待完成、分析。再根据前面的实际反馈选择第二个候选，到此停止新增候选。不要提前固定全部候选，必须体现反馈如何改变下一步。也不要只盯总收益，要看验证集排序指标、回撤、成交与费用、开发区间前后半段。
4. 预先固定的候选门槛：比E00净收益至少提高0.5个百分点；最大回撤恶化不超过1个百分点；验证Rank IC为正；开发区间两个半段相对E00收益均不低于-0.5个百分点。它们仅用于开发筛选，不是显著性或实盘资格。没有候选通过就保留E00。将逐轮观察和选择理由写入 `research-log.md`。
5. 冻结你选出的配置，做一次费用全部翻倍压力验证。proposal格式：`{"kind":"stress","origin":"E00或候选ID","hypothesis":"固定版本在双倍成本下的敏感性","expected_outcome":"量化成本冲击，不再据此调参","changes":{}}`。压力验证以后禁止增加候选。
6. 把决策写成文件：`{"selected":"E00或候选ID","reason":"具体证据与淘汰理由","next_question":"下一轮需要人判断的研究问题"}`，调用 `finish --session ... --proposal ...`。若被固定门槛拒绝，先检查自己是否误读指标，不准修改工具或门槛。
7. 生成本目录 `REPORT.md`，以工作流验收为主：哪些工具被真实调用、前轮反馈如何影响后轮、错误如何处理、能否正常收尾、证据在哪里。列出全部实验（含失败）的假设、变更、指标、门槛、费用压力结果，指标只用于验证执行。清晰区分技术执行成功、开发期改善、尚未独立验证。引用本地文件证据；后续问题仅记录为待人工判断，不继续执行。

技术错误最多尝试两次诊断修复，但不能改冻结输入、评估口径或工具代码；修不了就报告具体阻塞。你有充分 token 预算，但不要重复无进展调用。遇到方法论分歧或需扩大范围时记录为待人工决策；在目前授权范围内把完整实验链跑完。
