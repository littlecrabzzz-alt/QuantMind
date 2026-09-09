# Tushare 并行推进与本批增量
- 节点：Mac 父协调；代码 master 092dedf，云端200采集API/206读取dataset已部署；本记录不代表全目录完成。
- 用户希望缩短串行等待：保持 RRG 优先补数、其他接口开发、固定数据验收/镜像分线。生产采集仍共用账户额度与 pipeline 锁，云端唯一正式写入。
- RRG40 在05:01:54Z为14 done/26 pending，75992源行，空/失败0；固定e79fc1f4已含其中8项并经Mac文件SHA校验，另6已落盘待发布。完整240日日历、成员PIT和ETF映射仍待验收。证据 /tmp/tushare-rrg40-current-refresh-20260909.json（SHA278896d0c881e167791a6a95246cbe1731b28d68132b6796b96779ecb50e11e0）。
- bond8 初次11次调用/12结果：YC权限拒绝、OTC bulk2000保护阈值，其他日接口已有非空样本。修复有限CB发现后同epoch新增9次请求/382源行，holders/rating全部sample_ok；旧12项observation/object保持不变，累计20次调用/21结果。报告 /data/tushare/validation/bond8-probe.json SHA500426b3312a331108c650f190cfb84daed979c6229c709a0b2dc4b6d5d2d869。19项隔离测试通过，新helper SHA8bc8392b31e8b734054813e962d44a3c7559b3e4f176b62be65c08ad203bd55e，已存既有044559Z证据目录v2文件。
- member6真实请求完成，985源行；全字段核对器已补齐KP desc/hot_num，版本a3b1cb9f8bb6ca39aa6f3aca9c7ee06a943712660ffe447e5b0c3178cff56f97。全集/历史PIT/追加scope迁移缺口保留；未启用两个member API。
- 目前：父已启动bond/member统一发布，随后同固定版云端验收与Mac镜像并行；尚未启用bond family。remaining在独立worktree准备factor_list目录表头解析修复，structured完成上述只读RRG核查，text等待固定版bond验收。
- 不把接口注册、有限样本成功或已排队当完整历史完成。继续沿用 docs/tushare-progress.md 与覆盖台账，后续追加本批验收结果。
