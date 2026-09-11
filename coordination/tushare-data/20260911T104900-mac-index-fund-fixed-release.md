# 2026-09-11 10:49 CST — 指数/基金精确波次固定发布

- 负责人：当前 Mac 集成人；正式 writer 仍为 `lzy-vm:/root/data/disk/quantmind/project/data/tushare`。
- 固定输入：`data-3eec661f…`；三份不可变清单分别执行 `index_daily` 第2批、`index_weight` 第5批、`fund_daily+fund_adj` 第9批。
- 结果：1080 次调用全部 HTTP 200、零 429，合计 312891 行；1080 个 object、1080 个 observation、1028 个 Parquet 逐实体校验通过，共 45724019 字节。
- 发布：10:30:25 CST 原子切换到 `data-00177d548289255711d171ddd8ffc86332f5078951ccb8a618792c82a0528288`。清单 295830034 字节，768829 个文件引用、101451 个数据集、100894 个缺口；全部引用存在且大小一致，抽样 1024 个 SHA 零错误。本波与 438 个 `fina_mainbz_vip` 任务均已进入固定版。
- 非阻塞项：财务 PIT 两种批量规模均没有足够共同待拉叶，零调用停止；旧 `index_weight` plan 缺 `would_write` 字段；原始文档 worker 继续等扩盘/headroom 验证。
- Mac：10:49:38 CST 第164轮标准镜像下载7439个缺失文件并原子追平；manifest SHA/字节及4363个本轮引用全部正确，stderr为空。在`--network none`、Token为空和镜像只读条件下，`index_daily`、`fund_daily`各读取3行且上游调用0。
- `38c579a9`补齐`fina_mainbz_vip`的公共reader注册；修复前固定版有299个Parquet但返回`Unknown dataset`，修复后云端与Mac同样禁网读取3行、上游调用0。只重启主API加载，采集worker与Beat未重启。
- 证据：`docs/tushare-index-fund-exact-wave-20260911.evidence.json`。
