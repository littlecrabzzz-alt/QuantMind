# 训练运行资源

用途：维护本地 Mac 训练编排器与容器内 `train.py` 的配置、产物及资源控制合同，不是独立启动训练的教程。训练选择本地资源 `local`，由 `LocalDockerOrchestrator` 在本机 Docker Desktop 执行；训练镜像、数据挂载和依赖须在提交前核对。

## 输入与产物

`train.py` 读取 `--config <config.yaml>`；未传时尝试 `/tmp/config.yaml`。配置涵盖数据窗口/特征/来源、模型类型与参数、标签和执行上下文，字段以入口代码及编排器生成的 YAML 为准。

- `data.source_mode/local_dir` 决定数据读取；`pool_symbols` 是编排器解析后的股票池成员，不能用空池隐式扩大训练范围。
- `requested_features`、`auto_appended_features`、最终 `features/feature_columns` 分别表示提交、补齐与实际入模特征。因子目录已提供原始 QuantDB 字段的路径不自动补齐基础特征，不能将所有模式都描述成“固定加 6 个”。
- 模型、配置、预测、指标与元数据须与运行 ID 一起关联。`shap_summary.csv` 由可用的 LightGBM 解释路径产生；不是每种模型都承诺该产物。
- 回调、产物保存与模型注册是否成功应分别确认，不能只看容器退出码或旧验收报告。

## 资源控制

资源预算以本机 Docker Desktop 可用的 CPU、内存及训练镜像为准；不能把 Mac 宿主机的加速设备视为训练容器已可用。主业务的训练容器使用 `quantmind-local_quantmind-net` 网络，数据路径由当前受管快照的运行挂载解析，不直接指向 Main 开发数据。

| 环境变量 | 用途 |
|---|---|
| `TRAIN_IC_WORKERS` | 因子筛选 Rank IC 的并行进程数；`0/1` 走串行。未显式配置时还按剩余内存预算收缩 |
| `TRAIN_NTHREADS` | 树模型线程数，默认 `-1`；并行模型或内存紧张时应限制单模型线程 |

`parallel_utils.py` 必须与训练脚本同步交付。并行能力、数值一致性和性能须针对实际环境验证，历史单次加速比不是保证。训练会写产物、回调业务状态并占用本机资源，不用于文档冒烟检查。
