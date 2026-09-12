# Tushare index_daily 第21批固定版本闭包

- 状态：`fixed_release_local_closure_passed`
- 固定版本：`data-960e25bcaa9e3205892094fdf54e9ec8ae20a25ef3593e30ab48624f7c3b193b`
- 正常 publisher：`publish_only`，上游调用 0，耗时 337.704 秒
- Manifest：447388279 字节，976965 个文件，135299 个数据集，保留 observations
- 指定验收集合：1006 个引用、15520675 字节；360 object、360 observation、286 parquet
- 云端校验：missing 0、metadata error 0、physical error 0
- Mac 校验：missing 0、metadata error 0、physical error 0；报告与云端逐字节一致
- Mac 标准 LaunchAgent 第273轮：下载2704个增量文件、验证976965项、退出码0、stderr为空，CURRENT已原子切换
- 离线验收：生产镜像、`--network none`、空Token、只读Mac镜像、socket/DNS/secret guard；`index_daily`读取3行17列，上游调用0
- 云端归档：`validation/fixed-release-20260912/960e-index-daily21`
- 容量：可用327990231040字节，距100 GiB硬保留线仍有220616048640字节

本闭包只证明第21批既定1006个引用已进入同一固定版本并可在Mac离线读取。74个真实空响应仍不证明历史完整；供应商修订、known_at/PIT、完整指数范围及RRG结论继续开放。正常采集、固定发布、Mac单向镜像继续按既有链路运行，QuantDB未停止。
