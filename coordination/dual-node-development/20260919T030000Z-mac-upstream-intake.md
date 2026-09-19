# 原项目更新评估与第一批适配
- 上游 qusong0627/QuantMind master=bf65f66c（2.4.3），共同基线9ac3a544（2.3.3）。2026-09-19实际fetch与merge-tree：上游352个新增提交、902文件、17处冲突。
- 用户确认分批合入。第一批只适配f62b5210数值字符串读取/筛选；独立worktree /private/tmp/quantmind-upstream-sep19，codex/upstream-data-sep19。负责quantdb_hub.py、fundamental_aligner.py及已有测试文件。
- 冲突处理：不恢复本地已删除factor_factory.py，不引入依赖其他上游提交的fetch_ml_columns；只在现有归一入口转数值。分类编码保留文本前导零，非法数值不得通过排除筛选。
- 后续候选：训练取消、AI-IDE/Qlib路径、模拟交易修复；账号ID/数据库自动迁移、股票池重构、部署配置需单独沙盒验收。上游推理价格改从Parquet读取有价值，但其前复权回退不得直接当作交易价格采纳。
- 不执行上游整包部署、不启动数据库迁移、不改变运行中研究固定输入；第一批测试进行中。

- 第一批完成：候选fcc33a68（保留upstream f62b5210来源），3文件、64新增/1删除；既有FundamentalAligner回归与新增真实Parquet用例共2项通过，diff --check通过。未做进程重启或上游自动迁移；运行中研究保留当前进程代码，后续正常重载使用新代码。其余351个上游提交没有宣称已合入。
