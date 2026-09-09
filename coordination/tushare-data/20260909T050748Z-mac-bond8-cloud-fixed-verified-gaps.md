# bond8真实固定版云端只读验收

text_contracts按父指定固定版data-0a5af2a613b00f3c8cf088662215614fb1d56ba38c162f480a270634370103a1执行原f3b438 verifier，既有cloud-compose quantmind python-S入口，无源HTTP、无凭据、无DB写入/enable/publish。报告原字节复制Mac/tmp并核SHA。

结果verified_with_gaps，21样本/61验证文件，已知合同70列（YC拒权无返回数据，不能宣称70列全部实际取得）；所有非空样本已知missing=[]。耗时60.57秒、0上游、9gap。

必须阻断：YCcurve0 permission_denied，curve1 cached_denial，没有固定数据/对照；bc_otcqt批量2000饱和，精确code070013.BC/start=end20260904请求却返回6行、日期20260904/07/08/09，3行越界，bulk同code2行与range6行全列不等。具体observation784f7ea9938a41ce9880eee547b221a9.json，原文仍保留，不能修剪越界行冒充过滤通过。

其余6API：holders3code观察报告期20201231各10行range对照通过，原360行/固定去重330；rating22行/22，合法code和本地ann_date/rating_date分开查询；repo47→46，bond_blk5→4，bond_blk_detail8→6，bc_bestotcqt706→705，非空全列对照通过。原码含无后缀bond_blk123076被保留，与股票身份不混同。完整历史/PIT均未认证。

报告 `/tmp/bond8-cloud-preenable.json` SHA256 `4ce6891a6fe49569038d451512631d225b4eec3a6ce97f77bf5076706dba14a5`，source probe SHA500426b3312a331108c650f190cfb84daed979c6229c709a0b2dc4b6d5d2d869。Mac镜像由父运行，尚未接到本轮镜像完成信号，因此未执行Mac同版验收。
