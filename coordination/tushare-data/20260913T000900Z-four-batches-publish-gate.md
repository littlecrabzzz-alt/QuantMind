# Four-batch fixed-release gate after 960e

等待正常发布的四个authority闭包批次为：top10 holders第2批946引用、第3批952引用、index_daily第22批1063引用、fund_share第17批954引用。合并清单逐路径去重后仍为3915个唯一引用，交叉重复0，总计29307118字节：1440 object、1440 observation、1035 parquet。

合并清单SHA256为`dc694753ef483527c3251d9c9be0edc76c2772a20caea2a9fa6641e06a5c2f42`，本地文件在`docs/tushare-fixed-release-after-960e-four-batches-20260913/exact-refs.json`；authority create-only副本位于`validation/pending-release-20260913/960e-four-batches`。

四份独立负对照都证明960e manifest缺少各自全部新引用，因此发布前不会误报本地可用。后续必须由正常publish_only生成新固定版，再对同一3915项执行云端manifest/metadata/物理校验，Mac标准单向镜像，全量本地校验，以及空Token、禁网、只读镜像读取。完成前`release_published=false`、`Mac_available=false`。
