# Member6 fixed verifier字段遗漏修正，等实际固定版

structured/Mac：root复核指出4+7应11列。核查证实原新verifier清单只列KP5列，漏desc/hot_num；原全source对账会保留返回值，但missing_fields显式守门不完整。因此不是仅文案修正。

- `/tmp/member-partitions6-fixed-verify.py` audit改为直接读取已审合同FIELDS，TDX4+KP7=11；原字段保真/namespace/rowidentity/父subset/未知全集与migration等逻辑不变。新SHA `a3b1cb9f8bb6ca39aa6f3aca9c7ee06a943712660ffe447e5b0c3178cff56f97`，旧0e68不再用于验收。
- 新增desc/hot_num分别缺失的两个负例模式，KP每个sample明确missing_fields、known_columns_missing，partition_samples_verified=false。10测试含扩展子模式Python3.10通过1.235秒；test SHA64edf2ef50302118f2dea4a7a9b7447c623c7b355965e7a55e826723a25166c5，log SHA11b27b0ae5b897859b88a22578cebe17e496a02d463180ab187bb56710301ead。
- Probe010e7dad…与wrapperc4fcfc3d…未改（实际请求本就完整runtime11字段）；无runtime/生产变更。handoff计数及SHA同步修正。已通知root替换container/capsule旧fixed文件。
- 云端只读验收等待root提供实际自动/统一发布的精确release ID；目标输出 `/tmp/member-partitions6-cloud-verified.json`，之后以原字节复制Mac并比SHA。本agent未执行probe/enable，不提前猜版本或删subset/universe/PIT/migration gaps。
