# Mac 全量归档、云端研究子集

用户于 2026-09-16 确认以价格成本为优先：Mac 保存全量数据，以后迁移 NAS；云服务器从 Mac 取研究数据，不长期保留全量归档。业务数据库和 QuantDB 的既有日常采集链路不在此次 Tushare 迁移中改写。

## 供数入口

`scripts/tushare_research_cache.py serve --root <Mac归档目录>` 从已校验的固定 release 提取研究 API 的 Parquet 和其引用的 observation，独立校验后生成带 `source_release_id` 的子集 release。原始对象、附件、SQLite、配置与密钥不经此 HTTP 入口提供。服务仅监听 127.0.0.1，通过 SSH 反向端口转发供云服务器访问；不开放公网端口。

云服务器执行 `pull --root <独立研究缓存> --source http://127.0.0.1:18765`，核对固定版本与文件哈希后才更新 CURRENT。默认缓存预算 100 GiB、磁盘空闲保留 100 GiB；超限和 Mac 不在线时保留旧版并失败退出。初版不自动删除旧缓存文件，避免清除运行中研究输入；预算用尽必须显式安排已结束版本的回收。研究子集不声称历史完整，现有 reader 可按子集 release 查询，无 Tushare 回退。

默认提供 daily、index_daily、fund_daily、adj_factor、daily_basic、index_weight、ci_daily、sw_daily、stock_basic、index_basic、fund_basic、trade_cal 中源 release 已有的数据。接口集合可显式指定；这不是所有研究需求的永久白名单。

## 迁移门槛与容量

1. Mac 归档位于 `~/Library/Application Support/QuantMind/tushare`，与 `.local-dev` 研究沙盒分开。当前镜像成功只证明一个固定 release 可用，不证明云端所有未发布数据与采集状态已接收。
2. 在切换唯一采集者前，必须保存云端一致的采集/文档/归档 SQLite 检查点、权限配置及全部已采集文件，逐项校验。不得复制正在写入的 SQLite 文件来冒充迁移完成。
3. 切换后全量采集在归档节点进行；Mac 休眠时暂停，云端使用已缓存研究版本。NAS 迁移同样按校验、唯一写入者、原子切换流程执行。
4. Mac 至少预留 300 GiB；低于 500 GiB 时准备 NAS 迁移，达到保留线停止新采集/下载而非删除唯一归档。此处阈值是目标策略，采集迁移完成前不得声称已生效。
5. 云端原有 Tushare 全量目录只在全量迁移证据完成后回收；新子集缓存和旧全量目录在过渡期会暂时并存。当前代码没有自动删除云端全量数据的入口。
