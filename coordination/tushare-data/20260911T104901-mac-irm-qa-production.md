# 2026-09-11 10:49 CST — 董秘问答精确入口与首批生产

- 代码：`ee548878` 新增沪深董秘问答 prepare/runner/test，`32558212` 将跨 epoch 检查改为有界集合扫描；随后公共reader修复提交`38c579a9`。Mac、GitHub、云端 Git 与源码已对齐。
- 合同：只冻结 `history`、`pending`、`tries=0`、无任何 prior attempt/terminal sibling 的任务；四层为 SH/SZ × question/reply，优先拆分叶、短区间和较新 end。plan-only 的 authority、credentials、upstream、write、publish 标志全部为 false；两接口都锁定已购权限 500 rpm。
- 验证：Mac 与云端各 16 项组合测试通过，Python compile 和 diff check 通过。两端运行环境都没有 `ruff` 命令，作为工具缺口记录。旧 drain 模拟测试在应用容器内有两项子进程超时；真实云端排空两次均正常完成且没有 revoke/强杀。
- 首批：固定 `data-00177d548…`，360 项中 320 个拆分叶、40 个未拆历史窗；85.95 秒完成 360 次 HTTP 200、零 429，857441 行，133 done、40 empty、187 split_pending，并生成 374 个后续子任务。
- 物理闭包：360 object、360 observation、320 Parquet 的 SHA/字节全部正确，合计 689364476 字节；闭包 `validation/irm-qa-batch-20260911/batch-1-closure.json` SHA256 为 `bdafe46d30482cb4b68d8a12adf66a2ce034113d8826e9ad912893903e315a9e`。
- 运行时：API、Tushare worker、Beat 均恢复 healthy，restart0、OOM false；可用 228596420608 字节，高于 100 GiB 硬保留线。该批等待下一次固定发布和 Mac 单向镜像，不解除历史/PIT/RRG 缺口。
- 证据：`docs/tushare-irm-qa-production-20260911.evidence.json`。
