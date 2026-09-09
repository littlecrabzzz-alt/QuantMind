# 并行优先级与 DC2 / interval 集成就绪

- 节点/任务：Mac，01a0817d-7378-7673-9b7f-59c302713981；接续 20260909T005014Z-mac-dc-interval-integration-start.md。
- 用户希望减少等待，继续并行开发和后台回补；RRG 所需最小数据优先，不把全量历史作为所有后续开发的前置条件。
- 父 codex/tushare-data-intake：0696772 + 6431305 + e87dc2b，DC2 runtime 与 interval 已集成并 push origin；425 项隔离 Tushare 测试 12.886 秒通过，Ruff/diff 通过。主线仍 d57db6c，尚未发布新代码、未启用 DC2、未改变生产 interval，未暂停采集。
- /tmp/tushare-dc-extra-probe.py 为 7 个共享门控真实探测的待执行脚本；/tmp/tushare-dc-accept.py 已编译，只在真实源/Parquet/过滤核对之后启用可用 API。两个固定版 API / Mac 验收脚本由 text 完成：/tmp/dc2-cloud-api-accept-20260909.py、/tmp/dc2-mac-offline-verify-20260909.py，支持宽窄重叠与 con_code 合法分批。均未执行生产验收。
- 并行分工：text 只读核对 RRG 最小缺口与现有固定镜像；structured 只读检查最新性能/共享配额，区分下载速度与开发并行；remaining 已 push 风险5纯合同 1e701c6，继续在 e87dc2b 基线独立 codex/tushare-risk-runtime 接运行。父冻结 pipeline/registry/store/mirror 代码供其工作，只持有当前 DC 部署/验收脚本和集成权。
- 下一步：备齐实际 interval 验收；检查任务窗口，短暂排空两个自有队列后发布 e87dc2b（保持其他任务），7 请求 DC 探测和审计、固定发布、尽早恢复采集，然后并行云 API / Mac 离线验收。900 秒仅为拟启用最小发布间隔，真实到期与区间新增证据保留需实际验证，不伪造时间，不承诺采集吞吐线性增加。全历史/修订/PDF/PIT仍未完成。
