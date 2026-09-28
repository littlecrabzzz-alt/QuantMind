# 股票研究恢复：剩余五道门（09时，只读计划）

依据固定提交 `88f70c6c82600510589f8c1c4587d9eb3b0a2fba` 的源码及03–08时进展。本轮**无测试、无模型/数据执行、无GLM调用、无独立验收**；未读真实行情或受保护旧评价。下表已证事实引用既有记录，本轮未复跑。前史、受限provider及其公共freeze连接已在合成域收口，不再列为待重做项。

| 剩余门与可证伪条件 | 已证明 / 仍未证明 | 最小安全补证 | 决定方 |
|---|---|---|---|
| **1. 同一候选完整worker联通**：同包、同代码/镜像/config，实际名单→选池→标签/purge→约定模型分支→逐日信号→首末日执行与基准全部闭合；缺依赖/字段不得回退。 | 导入、loader/split、provider→Qlib/CnExchange和freeze→选池已有分段合成证据；**完整worker同包贯穿未测**，07–08时名单由harness镜像；10时新增真实Qlib名单→同包选池通过，derived条件分支也不能被基线结果覆盖。（S1:205–227；S2:181–298） | 实际 `D.list_instruments`→同包过滤/选池子项已于10时完成，停止重复。生命周期副例只证明查询语义，不证明真实来源或逐行准入。完整worker含训练的验收，本轮仅准备固定分支、一次运行/时限/访问哨兵与手算断言的方案，不执行。 | 主控明确下一子任务范围；独立验收方判全链是否成立。局部成功不能自动开放训练或股票。 |
| **2. 真实来源/PIT与生命周期**：每个准入字段/证券/日期可追到来源版本、当时可得时间、修订/复权规则及上市退市依据；未知不得当已验证。 | 合成范围/身份/声明校验已支持；真实来源、历史可得性、原子源快照、生命周期及真实新包均未准入。可读缓存和hash不能证明PIT。（S1:188、198、227；S2:304–306） | 先整理已有非敏感发布元数据的“字段→版本→可得/修订规则→生命周期依据→unknown”小表。实际开发期白名单抽样或真实新包须另明确范围；不得扫描未来尾或保留行情补身份，不覆盖旧包。 | 数据所有者供证，主控限定用途/读取范围，独立数据验收方签署；保留政策变化由用户决定。 |
| **3. 研究目标与执行语义**：标签总体、信号时钟、可交易日、复权数量/价格、缺价/陈旧度、历史ST及费用有明确合同，并与最小手算反例一致。 | 先全输入同日rank再筛池与先筛池后rank有合成差异；这是**尚待选择的定义，不是已确定bug或泄漏**。部分费用/缺末日报价行为已测，历史ST与完整执行语义未验收。（S1:207–211；S2:194–209、300–307） | 先书面选择保留当前标签总体，或另建池内总体候选；不改旧基线。之后只补一个尚未证明的语义反例，如跨停牌/缺行日期的标签结束与次日执行时钟；已有排名算术/前史案例不重复。 | 研究负责人定标签总体，执行合同负责人定交易/缺价政策，独立验收方核对；用户只需决定涉及其风险政策的变化。 |
| **4. 已暴露范围处置与验证协议**：字段/包/任务/投递/引用清单完整，旧结论明确用途；已用信息不能再声称未见。 | 已确认旧加载缓冲越界及证据包间接暴露；修代码、新hash、删字段不能清除知识暴露，也不证明全部拟合/曲线均污染。（S1:50–60） | 复用已存路径/hash/投递记录列范围，不再次展示受影响数值；分开“继续开发比较”和“最终验证”协议，给出独立或前向验证安排及代价，禁止自行滚动/改名保留段。 | 主控与独立方法审查方界定证据；**用户决定保留期或最终验证政策变更**。 |
| **5. 独立边界签署与限定恢复**：实际输入/代码/镜像/config/截止/节点/用途绑定；缺签署或身份漂移仍阻塞，只恢复获准的新候选。 | 文件与runtime身份保护、stock hold硬拒绝是工程止血；尚非真实候选的独立签署。旧包verify成功、GLM报告和内部自检均不能代替准入。（S4:111–162；S5:548–550） | 复用现有incident/合同/事件记录，由另一验收方审1–4；隔离验证未签署、旧身份、错截止、漂移不能恢复及同签署幂等。通过后才按授权范围更新合同，保留旧记录与回退点，不自动重放旧队列或放开保留期/交易。 | 独立验收方签署，主控按授权执行限定恢复；涉及第4门政策先取得用户决定。 |

**10时状态更新**：第1门的“真实Qlib名单→同包选池”纯合成连接已完成，仍不等于完整worker验收；训练部分只列方案。下一步先明确候选集合日期与逐行生命周期这两层合同，并整理第2、4门的既有元数据/待决定项，不派GLM重述本页。较早README/03时设计中已过时的“整Qlib仍枚举、前史仍缺”等状态，以后续进展和固定源码为准，不重开已收口分支。

## 固定源码身份

完整SHA256取自上述提交，而非可能正在更新的工作树文档；行号亦绑定该提交。历史六门设计 `巡检/20260927T1900-evidence/D3-ACCEPTANCE-NEXT.md` 仅作要求来源，其当时未实现状态不覆盖04–08时结果。

- S1 [docs/continuous-research/DEEP-RESEARCH.md](/Users/lizeyu/Documents/ChatGPT/投资/QuantMind.worktrees/glm-continuous-research/docs/continuous-research/DEEP-RESEARCH.md:50)：`869a2cf283b7c0396445948a53b88ce2706ba6b72e9f9b0af19b236094921823`
- S2 [scripts/frozen_research_worker.py](/Users/lizeyu/Documents/ChatGPT/投资/QuantMind.worktrees/glm-continuous-research/scripts/frozen_research_worker.py:160)：`e685c6567c4b4caf8bc55bebfd0526c66a9e22a35ef7d42acec630a544bb7d64`
- S3 [scripts/run_frozen_research.py](/Users/lizeyu/Documents/ChatGPT/投资/QuantMind.worktrees/glm-continuous-research/scripts/run_frozen_research.py:270)：`7405214589232aadbba6cab4aeb1db38281751a08fadbb9f91d370cd28feb96e`
- S4 [backend/services/engine/research/runtime.py](/Users/lizeyu/Documents/ChatGPT/投资/QuantMind.worktrees/glm-continuous-research/backend/services/engine/research/runtime.py:111)：`b1108e52b6cdace518751aada904f055de4a729e18a99fb79d3e3364bffc61c5`
- S5 [backend/services/engine/routers/continuous_research.py](/Users/lizeyu/Documents/ChatGPT/投资/QuantMind.worktrees/glm-continuous-research/backend/services/engine/routers/continuous_research.py:548)：`6be019e206a9f0a02fc8d92e58eb981f26083dfe7991f9efb62dcb0c023cadec`


## 10时补证范围

391份同一冻结产物、35个实际加载模块核hash；实际Qlib名单消费后1161/903行和3成员池与此前文本路径CSV逐字节一致。独立7名称/8声明/8人工工作日的小例，4次实际查询与原始区间交集复算一致；区间、截止日和逐行成员是不同概念，真实可交易性仍未知。候选集合的选择时点与每行生命周期约束可组合，不能强制三选一。GLM f9c89405bc56cef846ba473a只作反证，不属于独立验收；其“volume/覆盖部分缓解生命周期”未获支持，合同登记也不能替代新实现检查。

这项有限连接收口。没有真实源/训练/回测/准入政策变更，旧间接暴露事件保持。源码身份上表仍绑定88f70c6c，实跑代码来自08时冻结包（3b1ac291）。原件见仓库外巡检20260928T0200-evidence/D3-MEMBERSHIP-RESULTS.md。

## 11时合同准备

已写[两层名单合同草案](MEMBERSHIP-CONTRACT.md)，将候选集合时点、逐行生命周期与独立执行资格区分。推荐方案只是新候选设计，未选择真实数据/改变现行规则，不能宣称已冻结完整研究方案或通过准入。没有新的实现执行或GLM复核；10时有限连接保持收口。
