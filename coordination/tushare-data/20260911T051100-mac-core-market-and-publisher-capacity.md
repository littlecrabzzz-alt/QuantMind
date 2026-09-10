# Tushare 核心行情补采与发布容量修复

- 第二次1440项精确波次已进入固定版`data-7be20672a3a9d0fbaecd571b0ce6da741da23e1257fe55f02d114b06e8865a09`；逐任务和4148个唯一物理引用验证通过，闭包SHA256 `55ca1d341ea1c6a44ec3ee26ed67f132a410c1ba9092f60045301d99225137dc`。
- 发布暴露`tushare-worker` 1GiB cgroup OOM；`f71e407a`将该专用worker提高到2GiB。安全排空后实际容器限制2147483648字节、healthy、restart0、OOM false，Beat单独恢复。
- Mac第144轮标准镜像新增11459文件、校验716614文件后exit 0追平新固定版；禁网、空Token、只读挂载的离线API/QuantBot读取与云端一致。
- 核心行情batch 1固定六API各60个共同开市日。90.103秒完成340次请求、339 done、20 pending、1 blocked，返回1529654行，等效226.408 rpm；`CURRENT`未切换，闭包SHA256 `ecba9e2f29da9b5b3e43ba4504697673e990d3eda9485bf49563588e658cbdca`。
- blocked项为`stk_limit@20251009`在保存5516行原始证据后于normalize阶段命中硬截止；20个未开始任务保持tries0，交由常规队列继续。完整历史、修订/PIT及RRG准入继续保持未完成。
- 代码已在master：`cb7fffa7`指数成分代码兼容，`056ad757`核心exact runner，`5a196944`真实job元数据修复，`f71e407a`发布容量修复。机器证据见`docs/tushare-exact-wave-fixed-release-20260911.evidence.json`、`docs/tushare-core-market-batch-20260911.evidence.json`和`docs/tushare-index-constituent-normalization-20260911.evidence.json`。
