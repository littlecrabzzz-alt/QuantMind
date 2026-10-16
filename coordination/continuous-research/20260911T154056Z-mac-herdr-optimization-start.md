# Herdr 接现有数据的自动策略优化
- 进行中，Mac；用户纠正通用入门路线，要求agent使用系统数据自动优化策略。
- 范围：/Users/lizeyu/.local/share/quantmind/herdr-research/optimize-20260911T154056Z；复用scripts/agent_research_tool.py、固定本地模板；最多基线+2候选+1压力，4小时窗口，单实验900秒。
- 不改项目源码，不写正式数据/平台策略；会使用本地研究launch.lock及相同node label与已有worker协调重型计算。
- 本地工作台无queued/running任务；既有QuantDB恢复任务保留固定研究输入，与此独立。handoff因SSH被关失败，继续本地固定输入范围。
