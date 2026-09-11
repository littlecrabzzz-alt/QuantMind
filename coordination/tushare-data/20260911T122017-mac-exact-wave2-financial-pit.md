# 2026-09-11 12:20 CST — exact wave 2 与财务PIT接续

- 固定版保持`data-82ece8a2297797f1f2508f4a782d897164d910a650b45c06df87ae8c24bb1838`；authority新增指数权重、基金行情、董秘问答共1080次、1123137行，未切换CURRENT。
- 指数权重第359项在响应文件落盘后遇SQLite读锁，按object/observation/Parquet哈希恢复引用且未重拉；第360项确认未调用后单独执行。整波闭包SHA为`8d1acfd1bfc65b89744bdb84d7da5a25c4045fec763352afaba3565dd0acc99e`。
- 并行审计读取authority时不得跨多个API长持有DELETE-journal连接；冻结、执行和闭包窗口内只允许主流程持有SQLite连接。只读分析改用固定release或提前完成后退出。
- 财务PIT下一步：提交共同叶优先、按API独立补齐的冻结器，云端对齐代码后重新prepare与plan-only；只执行当时仍为pending/tries0且无attempt的固定任务。所有结果等待正常publish-only，再做Mac单向镜像与禁网读取。
- RRG仍为`blocked_data`。只允许首次观察日起的forward-only候选映射；不得把当前成员、申万/东方财富/同花顺成员或PCF申赎篮子倒填成中信历史PIT证据。
