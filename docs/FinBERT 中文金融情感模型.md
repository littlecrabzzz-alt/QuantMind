# RSS FinBERT 情感识别

用途：安装可选情感模型、控制启用状态并区分模型可加载与新闻已实际使用。新闻情感不是投资建议，也不能代替收益预测。

## 链路与依赖

`backend/services/api/news/enricher.py` 将词典匹配与 `sentiment.py` 的 FinBERT 结果融合，写入 `news_article_enrichment`，供资讯与个股页面读取。默认模型来源为 `bardsai/finance-sentiment-zh-base`；权重来源及其使用许可应随下载版本核实，代码仓库许可不代替模型许可。

需要 `torch`、`transformers` 和本地权重。不能从镜像名称推断依赖已经安装；离线镜像可能跳过 PyTorch。不要在运行容器中临时 pip 安装来代替可复现镜像构建。

| 配置 | 行为 |
| --- | --- |
| `FINBERT_ZH_MODEL` | 本地模型目录；基础 Compose 指向 `/app/models/finbert-zh-base` |
| `FINBERT_DEVICE` | `-1` 为 CPU，`0` 为第一个 GPU；GPU 还需匹配 torch、驱动和容器设备权限 |
| `NEWS_USE_FINBERT` | 显式 `true/false` 覆盖设备默认值；未设置时仅 GPU 默认启用 |
| `FINBERT_TOGGLE_PATH` | 运行时开关文件，默认 `/data/finbert/enabled`；有效持久化开关优先于环境默认值 |
| `FINBERT_RETRY_AFTER` | 加载失败冷却秒数，默认 300 |

模型不可用时仍可产出词典情绪；不能因此声称 FinBERT 正常。CPU 可显式启用，但要评估 RSS worker 的吞吐和资源占用。

## 安装与启用

1. 确认目标实例及其模型挂载。Mac 隔离实例的模型位于 `.local-dev/project/models/`，不要误写根目录 `models/`。
2. 在受控构建环境补齐依赖。可选 Linux 安装入口为 `deploy/install-model-deps.sh`，会构建镜像且默认重启；维护前先读 [部署指南](部署指南.md)。不要在 Mac 上照抄 Linux 部署流程。
3. 下载脚本为 `backend/scripts/download_finbert.py`。例如在已确认的 Mac 隔离容器中执行：

   ```bash
   docker exec quantmind-dev python /app/backend/scripts/download_finbert.py
   ```

   这是联网下载并写入权重的操作，不是只读检查。离线部署应将可信来源的完整模型目录放入实例模型挂载，至少需要配置、权重和对应 tokenizer 文件；不要只拷一个权重文件。
4. 通过管理页的 FinBERT 开关或目标实例配置启用。环境变量变更必须按该实例维护流程应用；不要向 `/etc/profile.d` 追加变量来假装改变已运行 worker 的环境。

## 诊断

通过已登录客户端请求 `GET /api/v1/news/enrichment/finbert-status`，分别观察启用状态、模型/框架可用性、设备、错误提示及近 24 小时实际使用占比。该诊断可能触发模型加载/样例推理，不是零计算操作。

检查数据库时，只读查询：

```sql
SELECT model_version, COUNT(*)
FROM news_article_enrichment
GROUP BY model_version;
```

`model_version` 包含 `+finbert` 表示这些富化记录使用了 FinBERT；旧记录不带后缀并不证明当前模型故障。

| 现象 | 处理 |
| --- | --- |
| 未启用 | 检查持久化开关与环境默认值；CPU 默认关闭属于预期 |
| 已启用但不可用 | 检查实际运行镜像的依赖、本地模型目录和加载日志 |
| 可用但近 24 小时占比为零 | 检查是否有新资讯、富化任务/worker 是否运行；先处理小批量，不默认全量重算 |
| 持续加载失败 | 看具体依赖或权重错误；等待冷却并不能补齐缺失文件 |

`POST /api/v1/news/enrichment/run` 会写入富化结果；`rebuild-all` 会重算历史数据。两者不是健康检查，不应为确认页面状态而自动执行。
