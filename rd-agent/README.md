# RD-Agent：上游集成源码

用途：说明本仓库中的 RD-Agent 来源、QuantMind 接入位置与必须随包保留的资源，而不是宣传页或独立部署承诺。

## 来源与许可

上游：[Microsoft RD-Agent](https://github.com/microsoft/RD-Agent)，Microsoft 版权所有，按 [MIT LICENSE](LICENSE) 使用。安全披露流程见 [SECURITY.md](SECURITY.md)，上游行为与商标政策见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) 和 [policy](docs/policy.rst)。

## 集成与资源边界

- QuantMind 接入见 [RDLoop 包装器说明](../backend/services/engine/rd_agent/README.md)。模型服务、数据、执行环境必须按 QuantMind 实例配置，不能在此目录另建一套事实源。
- `pyproject.toml` 读取本 README 作为包元数据；`rdagent` 包中的 Markdown 也在 package-data 中，不得按文档后缀批量排除。
- Qlib `factor_data_template/README.md` 被复制到输入目录供模型读取；`factor_template/model_template` 随工作区注入。它们是运行时资源，不是占位目录介绍。
- 数据科学任务 `description.md`、Kaggle 组件 `spec/*.md`、微调数据集卡、AutoRL 的 instructions/skill 和各 CLI agent 指令是任务输入或 fixture；保留它们不代表 QuantMind 已开放这些上游场景。
- 上游技术参考从 [docs/index.rst](docs/index.rst) 进入，仅保留模型后端配置、框架接口和量化场景；具体启用能力仍以当前集成代码为准。

上游研究归属参考：[R&D-Agent-Quant](https://arxiv.org/abs/2505.15155)、[RD-Agent technical report](https://arxiv.org/abs/2505.14738)。

## Legal disclaimer

The RD-agent is provided “as is”, without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose and noninfringement. The RD-agent is aimed to facilitate research and development process in the financial industry and not ready-to-use for any financial investment or advice. Users shall independently assess and test the risks of the RD-agent in a specific use scenario, ensure the responsible use of AI technology, including but not limited to developing and integrating risk mitigation measures, and comply with all applicable laws and regulations in all applicable jurisdictions. The RD-agent does not provide financial opinions or reflect the opinions of Microsoft, nor is it designed to replace the role of qualified financial professionals in formulating, assessing, and approving finance products. The inputs and outputs of the RD-agent belong to the users and users shall assume all liability under any theory of liability, whether in contract, torts, regulatory, negligence, products liability, or otherwise, associated with use of the RD-agent and any inputs and outputs thereof.
