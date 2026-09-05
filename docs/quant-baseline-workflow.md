# 可重复运行的简单量化基线

本流程通过 QuantMind 正常的本地 API，完成因子目录准备、训练、模型注册、独立推理、含费用事件驱动回测、资金核对和输入留档。不调用交易接口。

## 已验证的本次实验

2026-09-05 的结果保存在 `results/baseline-20260905/attempt-02/README.md`。

- 训练：2023-01-03 至 2024-12-31；验证：2025-01-06 至 2025-03-31；测试：2025-04-07 至 2025-06-30。
- L1 的8个价量因子，LightGBM最佳迭代8轮；测试Rank IC约0.056895。
- 100万元、Top20、每日最多淘汰5只，T+1收盘成交。57个交易日、578笔成交。
- 净收益6.59697%，沪深300收益9.65722%，收益差为-3.06025个百分点；最大回撤-3.77016%。
- 输入与模型快照约2.99GiB；原始数据、成功和失败数据库记录全部保留。

这证明研究流程跑通，不证明具有稳定超额收益，也没有实盘验收。

## 运行

在项目根目录运行，使用已配置的本地 QuantMind 服务和管理员账户：

```bash
python3 scripts/run_quant_baseline.py run --output results/my-baseline
```

默认用户名为admin；密码交互输入，不写进代码和结果。也可通过 `QM_USERNAME`、`QM_PASSWORD` 或 `QM_TOKEN` 环境变量传入。不要把密码写在共享命令记录中。

第一次使用 `config/baseline_cn_l1.json`，之后从输出目录的 `baseline-config.json` 读取已冻结配置。首次网络请求前保存配置哈希与 API 地址；已有 `catalog.json` 则复用原版本。同一命令重跑会恢复既有任务、复用已验证推理和回测，不重复提交已取得ID的任务。修改参数或 API 地址要使用新目录；显式传入不同配置会被拒绝覆盖原实验。旧实验未记录 API 地址时，首次恢复会绑定本次地址，应先确认服务正确。

第一次留档会复制相关输入和产物，预留至少4GB磁盘。`snapshot/`、数据库和原始数据均无自动清理步骤。每次校验都会重新验证保留快照的内容哈希。

各阶段也可单独执行：

```bash
python3 scripts/run_quant_baseline.py prepare --output results/my-baseline
python3 scripts/run_quant_baseline.py train --output results/my-baseline
python3 scripts/run_quant_baseline.py status --output results/my-baseline
python3 scripts/run_quant_baseline.py infer --output results/my-baseline
python3 scripts/run_quant_baseline.py backtest --output results/my-baseline
python3 scripts/run_quant_baseline.py backtest-status --output results/my-baseline
python3 scripts/run_quant_baseline.py verify --output results/my-baseline
```

`verify`不需要登录。训练/回测失败立即保留任务及日志并停止；解决原因后用新实验目录重试。训练、推理、回测 POST 前先保存 `*-submission-intent.json`，收到响应后保存 `*-submission.json`。若存在意图文件而没有响应，恢复流程会停止，不自动重发。先在平台查明原任务，再将确认的原响应恢复到对应文件；服务端尚无实验幂等键，这只是客户端防重复保护。同一输出目录只运行一个进程。

## 本次优化

1. 去掉训练入口对PyTorch的强制导入。LightGBM可在现有OSS镜像运行；深度学习仍按需导入真实PyTorch，没有mock回退。
2. 固定已发布因子版本和8个显式特征；关闭自动筛选、调参、集成和WFA，并限制LightGBM为4线程，不暂停其他容器。
3. 使用模型注册返回的正式模型ID，验证推理和回测实际使用的模型一致，无预测缺失或模型回退。
4. 回测通过8000端口的认证代理进入，身份由服务端认证上下文决定。
5. 保存状态、请求、响应、CSV、实际配置、校验值和输入副本；区分平台注册成功、任务完成和资金核对通过。
6. 独立核对逐日现金、资产恒等式、期末收益，并另算标准每日收益Sharpe，保留平台原指标供比较。
7. 输出 `research-decision.json`，区分技术核对通过与研究结论。当前基线固定标为 `needs_validation`，列出缺少同口径对照、独立时期检验和全时段推理重放。该文件是研究报告，不是交易服务的权限开关；盈利或跑赢指数不会自动获得模拟盘资格。

## 训练可信度修正（2026-09-05）

- Stacking 复用单模型的逐日截面 RankIC 均值 / 标准差口径；删除用预测值标准差作 ICIR 分母的实现。指标不再随分数缩放而改变，旧 Stacking 指标不能直接用于比较新实验。
- 构造标签时保留实际结束日期；截面排名标签记录该日所有参与股票的最晚结束日期，避免停牌或稀疏序列使未来价格越过切分边界。主切分、WFA 和 OOF 共用隔离函数，数据不足时不再跳过隔离。
- WFA 和 OOF 从外层训练历史最后20%的日期另取早停集，拟合集与早停集也隔离。外层评估标签不参与选轮数；小窗口会跳过，不能靠取消隔离维持训练。
- 修正多日收益备用构造路径，把未来位移放回各股票分组内，防止跨股票串行。
- 上述修正只影响后续训练；此前的基线、模型、预测和回测产物保留原样。本次未重训全量历史模型。

## 尚未完成的优化

输入快照仍在执行后生成；后续应改为执行前冻结并确保训练、推理、回测实际读取同一快照。自动等权/单因子对照和全时段历史推理重放仍未实现，需要在新实验中先固定方案。之前已查看的测试区间应视为研究数据。

向量化回测的持仓漂移与费用口径、RiskGate 卖出和批量额度检查、完整 PIT 与历史交易规则覆盖仍需单独修正和验证，本流程继续使用事件驱动回测。WFA 窗口若用于反复调参，仍属于研究验证数据，不是最终独立测试。

## 中途记录

- 第一轮训练 `train_20260905024617_31a57afb` 因缺少torch失败，记录及配置位于 `results/baseline-20260905/` 和 `data/training_jobs/`。
- 第二轮 `train_20260905024830_c495aa5e` 完成，平台注册模型ID为 `mdl_cn_train_20260905024830_c495aa5e_89dcf5b4`。
- 首次独立推理用了训练任务ID，实际通过默认模型解析到了相同模型；原响应保存在 `attempt-02/initial-alias-inference/`，随后以正式模型ID重跑并验证。
- 直接访问引擎的401、默认user_id不匹配导致的403发生在提交回测前，修正客户端调用后才创建正式回测。
- 初始请求使用了无效的 `explain.enabled` 字段，平台实际按默认执行验证集SHAP。已保留原请求及实际配置，后续模板改为正确的显式 `enable_shap` 参数。

## 检查

```bash
python3 -m unittest discover -s scripts -p test_quant_baseline.py
docker exec -e QM_RESEARCH_TEST_OUTPUT=/data/research-integrity-20260905 quantmind python -m unittest discover -s /app/docker/training -p 'test_*.py'
```

13项检查通过：包括无PyTorch的真实LightGBM训练/预测、真实双模型Stacking及WFA、逐日ICIR独立重算和缩放不变性、标签日期及稀疏样本隔离、独立早停、费用与现金守恒、初始回撤、配置/API变更保护、丢失响应防重试和研究结论。

本次训练检查日志位于 `results/research-integrity-20260905/training-checks.log`；合成输入、OOF预测、元模型及指标保留在 `data/research-integrity-20260905/`。后续运行请将 `QM_RESEARCH_TEST_OUTPUT` 指向新目录，避免覆盖之前的检查产物。未运行整个项目测试套件、全量新回测或券商端验收。

本工具目前针对标准本地CN目录布局：`data/quantdb`、`db/qlib_data`、`data/training_jobs`。更换数据挂载位置前需要适配快照路径；不要把另一数据目录的快照当成本次运行输入。
