# 12API云缓存验收与全范围审计
- 双端handoff --align-git mac已通过，HEAD5acec2a2、6663源文件一致，源码摘要cf48fd02d56a9b11a649cf62097963441b18623539d1eada9e4d96976d42a9f0；服务预检通过，快照仍独立待拉取。
- tushare-research-cache.service PID282224已成功退出，新增15692文件/722936377字节全量完成，CURRENT切至3a47d505（总43145文件、12API）。cloud quantmind内read_dataset实际读取daily/adj_factor/ci_daily各2行，均有tushare溯源metadata。应用router仍保持archive默认，尚未重启切换。
- 离线audit_tushare_scope_gaps已重跑，产物位于Mac ~/Library/Application Support/QuantMind/tushare-scope-audit-20260917.json：249命名范围，245已注册范围内API；另有2写操作、1SDK包装、1受限只读；246注册并有读取能力的总数含1范围外API。42无接口名页面仍保留，不以注册数宣称权限/完整历史已完成。
- 源pipeline-status最近记录SoftTimeLimitExceeded，publish_only请求0、publication pending。迁移后必须真实验证native发布跨越旧600秒限制、恢复采集吞吐，不能只看服务已启动。
- checkpoint PID253095继续运行，逻辑读取89.25GB、物理读取23.98GB、内存6.46GB，尚无COMPLETE；本地precopy三原PID继续存活，不重启。
- 源Tushare仍迁移暂停。剩余：完整检查点/预复制成功，sync-frozen/数据库安装/finalize/本地worker启用与实际发布采集验收；应用缓存切换前保留旧研究固定版本访问，未释放云全量数据。
