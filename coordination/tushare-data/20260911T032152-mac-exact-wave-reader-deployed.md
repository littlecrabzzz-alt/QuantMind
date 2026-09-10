# Tushare 精确补采与 reader 部署

- 主分支提交 `77c1a3faadab018a9a8c960413c0fb9c17133344` 已推送 GitHub；云端 GitHub fetch 超时后通过只含该提交的 Git bundle 快进到同一哈希。Syncthing 预先到达的三个目标文件先按明确路径暂存，快进后 SHA 一致再删除临时 stash；其他研究文件未暂存或改写。
- 生产镜像的 CLI/store/API/market 17 项测试通过。云端用 `--network none` 和空 Token、Mac 用阻断 socket/DNS 和未设置 Token，对固定版 `data-dbd1ef…` 分别以 `SH000003` 与 `000003.SH` 查询 `index_weight`，均返回 40 行；两端 7 行导出 SHA256 同为 `529084f1…`，上游调用为 0。
- 云端只重启 `quantmind` API 以加载 reader 代码，健康接口为 HTTP 200；Tushare worker、Beat、DB、Redis 均 healthy，采集服务未因 reader 修复重启。
- 双端 `handoff` 在同一 `77c1a3fa` 上通过，源码6091文件、摘要 `c26f2215…` 一致；数据权威仍为云端，Mac仍为本地沙盒和单向固定版镜像。
- 新一轮财务、指数权重、基金份额和基金净值共 1440 次精确请求，188.364 秒完成，折算 458.686 rpm；四批不可变收据和合并摘要位于 authority 的 `validation/`。
- 正常publisher原子切换到`data-f9c55787…`后触发软超时，下一任务以`verified_current_intent`无上游恢复并推进发布时钟。任务级闭包验证1440个task及4139个唯一物理引用，报告SHA `073eb220…`；Mac第140次LaunchAgent新增12426文件、完整校验705154文件后退出0并追平。
- 新固定版云端禁网和Mac禁socket/DNS读取一致：财务4行、指数内部/来源码各1369行、基金份额1015行、基金净值523行，全部0上游调用。最终authority约98.581GiB、Mac镜像约84.952GiB，云盘剩133.785GiB。
- 机器证据见 `docs/tushare-exact-wave-reader-20260911.evidence.json`。全局历史、修订/PIT与 RRG 数据准入仍未完成，不把吞吐和 reader 成功解释为全量完成。
