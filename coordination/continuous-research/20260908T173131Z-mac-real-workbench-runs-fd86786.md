# 双端真实研究已从页面发起
- Mac；任务 01a08188-b391-7fd3-aa2a-d7c9eef2689d；进行中，不能宣称完整验收通过。
- 接续 20260908T170810Z-mac-workbench-integration-497c267.md。实现已集成主树，增量分支提交至 fd86786。追加文件归属 electron/src/components/navigation/FloatingNavBar.tsx，仅将入口名改为研究工作台；无其他前端任务重叠记录。
- 云端课题 3ab07ef1635b45e89bc176dabff29ba9，当前窗口 4d4a7b86db494b8e8ef0c2d121a45533；本地课题 2a6f133bf01c41b19432eb9f0047d595，窗口 23db9b32b8b0477881d24de272646786。两者从真实页面创建、默认 Flash/2 小时/1 候选。云端早期环境/模型超时失败窗口均保留。
- 两端基线均真实完成训练、57 日独立推理、三组 CnExchange 回测与独立账务核验；云端模型第二次提案成功，确认 5526 tokens，第一次超时用量未知；本地 coordinator 重启后自动接回同课题并重试模型，未重复基线。
- 修复：建表 SQL 移到同步源码 scripts/research_workbench_v1.sql；后端镜像使用现成 Docker SDK；纯模型提案超时/5xx/429退避可重试，实际计算仍按幂等容器名/提交意图核对；页面连接失效清空旧节点操作。
- 模型超时重试的方案增量已写入 docs/research-workbench-operations.md：只生成提案，无执行副作用；未知用量保留，不能重复实验。
- 最近双端核对通过 b19e097，4300文件，摘要0a3ad859c5d490979f6017e1eb515bcf0ab536919a2ef066c37b79f5943caa15；Mac处于local-sandbox。
- 正在验证云端 E01 运行中重启研究 worker（原计算容器1ac9765dee3c10d4e523a1535723c7892fe6fc6d3969668a787ef60916bb7786），此时不重启 API/其他业务 worker。页面已关闭，等待两端完整候选/因子/压力/报告。
